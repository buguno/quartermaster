import json
import shutil
import subprocess
from datetime import datetime
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.urls import reverse

from apps.core import backup
from apps.core.exceptions import BackupError
from apps.core.models import UserProfile
from apps.inventory import services
from apps.inventory.models import Batch, Category, Item, Location
from tests.inventory.factories import (
    CategoryFactory,
    ItemFactory,
    LocationFactory,
)

PASSPHRASE = 'correct horse battery'

needs_gpg = pytest.mark.skipif(
    shutil.which('gpg') is None, reason='gpg is not installed'
)


@pytest.fixture
def stocked(db, user):
    """A small but connected data set: user, profile, stock, history."""
    UserProfile.objects.create(user=user, language='pt-br', theme='dark')
    category = CategoryFactory(name='Food')
    category.save()
    location = LocationFactory(name='Pantry')
    location.save()
    item = ItemFactory(
        category=category, name='Rice', unit='kg', kcal_per_unit=Decimal(3600)
    )
    item.save()
    services.add_stock(item, location, Decimal('5'), user=user)
    services.remove_stock(item, Decimal('2'), user=user)
    _settle()
    return item


def _settle():
    """Fire deferred constraint triggers so TRUNCATE can run in a test.

    Tests wrap everything in one transaction; a real restore never does.
    """
    connection.check_constraints()


def _wipe():
    from apps.inventory.models import StockMovement  # noqa: PLC0415

    StockMovement.objects.all().delete()
    Batch.objects.all().delete()
    Item.objects.all().delete()
    Category.objects.all().delete()
    Location.objects.all().delete()
    _settle()


# --- Helpers --------------------------------------------------------------


def test_filename_is_timestamped():
    name = backup.filename(datetime(2026, 11, 5, 9, 30, 15))

    assert name == 'quartermaster-20261105-093015.backup.gpg'


def test_filename_defaults_to_now():
    assert backup.filename().startswith('quartermaster-')


def test_missing_gpg_is_reported(monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda name: None)

    with pytest.raises(BackupError, match='GnuPG'):
        backup.encrypt(b'data', PASSPHRASE)


# --- Encryption -----------------------------------------------------------


@needs_gpg
def test_encrypt_then_decrypt_round_trips():
    encrypted = backup.encrypt(b'secret data', PASSPHRASE)

    assert b'secret data' not in encrypted
    assert backup.decrypt(encrypted, PASSPHRASE) == b'secret data'


@needs_gpg
def test_the_file_is_a_standard_gpg_file(tmp_path):
    encrypted = backup.encrypt(b'portable', PASSPHRASE)
    source = tmp_path / 'file.gpg'
    source.write_bytes(encrypted)
    home = tmp_path / 'home'
    home.mkdir(mode=0o700)

    result = subprocess.run(  # noqa: S603
        [
            'gpg',
            '--batch',
            '--homedir',
            str(home),
            '--pinentry-mode',
            'loopback',
            '--passphrase',
            PASSPHRASE,
            '--decrypt',
            str(source),
        ],
        capture_output=True,
        check=False,
    )

    assert result.stdout == b'portable'


@needs_gpg
def test_wrong_passphrase_is_rejected():
    encrypted = backup.encrypt(b'secret', PASSPHRASE)

    with pytest.raises(BackupError, match='Senha incorreta'):
        backup.decrypt(encrypted, 'another passphrase')


@needs_gpg
def test_a_tampered_file_is_rejected():
    encrypted = bytearray(backup.encrypt(b'secret' * 50, PASSPHRASE))
    encrypted[-5] ^= 0xFF

    with pytest.raises(BackupError):
        backup.decrypt(bytes(encrypted), PASSPHRASE)


# --- Export and restore ---------------------------------------------------


@needs_gpg
def test_restore_brings_everything_back(stocked, user):
    exported = backup.export_backup(PASSPHRASE)
    _wipe()
    get_user_model().objects.all().delete()
    _settle()
    assert not Item.objects.exists()

    backup.restore_backup(exported, PASSPHRASE)

    item = Item.objects.get(name='Rice')
    restored_user = get_user_model().objects.get(username=user.username)
    assert item.kcal_per_unit == Decimal(3600)  # noqa: PLR2004
    assert services.get_stock(item) == Decimal(3)
    assert item.batches.get().movements.count() == 2  # noqa: PLR2004
    assert restored_user.check_password('s3cret-pass')
    assert restored_user.profile.theme == 'dark'
    assert item.batches.get().movements.first().user == restored_user


@needs_gpg
def test_restore_replaces_what_is_there_now(stocked):
    exported = backup.export_backup(PASSPHRASE)
    extra = ItemFactory(category=stocked.category, name='Added later')
    extra.save()
    _settle()

    backup.restore_backup(exported, PASSPHRASE)

    assert not Item.objects.filter(name='Added later').exists()
    assert Item.objects.filter(name='Rice').exists()


@needs_gpg
def test_new_rows_get_fresh_ids_after_a_restore(stocked):
    exported = backup.export_backup(PASSPHRASE)
    backup.restore_backup(exported, PASSPHRASE)

    created = ItemFactory(category=Category.objects.get(), name='New')
    created.save()

    assert Item.objects.count() == 2  # noqa: PLR2004


@needs_gpg
def test_restore_with_the_wrong_passphrase_changes_nothing(stocked):
    exported = backup.export_backup(PASSPHRASE)

    with pytest.raises(BackupError):
        backup.restore_backup(exported, 'nope nope nope')

    assert Item.objects.filter(name='Rice').exists()


@needs_gpg
@pytest.mark.parametrize(
    'payload',
    [
        b'not json at all',
        b'\xff\xfe',
        json.dumps([1, 2]).encode(),
        json.dumps({'format': 'something-else'}).encode(),
        json.dumps({
            'format': backup.FORMAT,
            'version': 99,
            'data': [],
        }).encode(),
    ],
)
def test_files_that_are_not_backups_are_rejected(stocked, payload):
    encrypted = backup.encrypt(payload, PASSPHRASE)

    with pytest.raises(BackupError, match='não é um backup'):
        backup.restore_backup(encrypted, PASSPHRASE)

    assert Item.objects.filter(name='Rice').exists()


@needs_gpg
def test_a_backup_from_another_schema_is_rejected(stocked):
    document = {
        'format': backup.FORMAT,
        'version': backup.VERSION,
        'schema': {'inventory': '0001_old'},
        'data': [],
    }
    encrypted = backup.encrypt(json.dumps(document).encode(), PASSPHRASE)

    with pytest.raises(BackupError, match='outra versão'):
        backup.restore_backup(encrypted, PASSPHRASE)

    assert Item.objects.filter(name='Rice').exists()


@needs_gpg
@pytest.mark.parametrize(
    'data',
    [
        [
            {
                'model': 'inventory.item',
                'fields': {
                    'name': 'Broken',
                    'category': ['missing'],
                    'unit': 'un',
                    'min_stock': '0',
                },
            }
        ],
        [{'model': 'inventory.nothing', 'fields': {}}],
        [{'no': 'model'}],
    ],
)
def test_damaged_data_is_rolled_back(stocked, data):
    document = {
        'format': backup.FORMAT,
        'version': backup.VERSION,
        'schema': backup._schema_state(),  # noqa: SLF001
        'data': data,
    }
    encrypted = backup.encrypt(json.dumps(document).encode(), PASSPHRASE)

    with pytest.raises(BackupError, match='nada foi alterado'):
        backup.restore_backup(encrypted, PASSPHRASE)

    assert Item.objects.filter(name='Rice').exists()
    assert services.get_stock(Item.objects.get(name='Rice')) == Decimal(3)


# --- Views ----------------------------------------------------------------


@pytest.fixture
def superuser(user):
    user.is_superuser = user.is_staff = True
    user.save()
    return user


def _backup_data(**overrides):
    data = {'passphrase': PASSPHRASE, 'passphrase_again': PASSPHRASE}
    return data | overrides


def test_backup_section_is_for_superusers_only(auth_client, user):
    plain = auth_client.get(reverse('core:settings')).content.decode()
    user.is_superuser = True
    user.save()
    admin = auth_client.get(reverse('core:settings')).content.decode()

    assert reverse('core:backup_export') not in plain
    assert reverse('core:backup_export') in admin
    assert reverse('core:backup_restore') in admin


@pytest.mark.parametrize('name', ['backup_export', 'backup_restore'])
def test_regular_users_cannot_use_backups(auth_client, name):
    response = auth_client.post(reverse(f'core:{name}'), {})

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize('name', ['backup_export', 'backup_restore'])
def test_backup_endpoints_require_post(auth_client, superuser, name):
    response = auth_client.get(reverse(f'core:{name}'))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.parametrize(
    'overrides',
    [
        {'passphrase': 'short', 'passphrase_again': 'short'},
        {'passphrase_again': 'does not match at all'},
        {'passphrase': 'line\nbreak here', 'passphrase_again': 'x'},
        {'passphrase': ''},
    ],
)
def test_export_validates_the_passphrase(auth_client, superuser, overrides):
    response = auth_client.post(
        reverse('core:backup_export'), _backup_data(**overrides)
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.context['backup_form'].errors


@needs_gpg
def test_export_downloads_an_encrypted_file(auth_client, superuser, stocked):
    response = auth_client.post(reverse('core:backup_export'), _backup_data())

    assert response.status_code == HTTPStatus.OK
    assert response['Content-Type'] == 'application/octet-stream'
    assert '.backup.gpg"' in response['Content-Disposition']
    assert b'Rice' not in response.content
    decrypted = json.loads(backup.decrypt(response.content, PASSPHRASE))
    assert decrypted['format'] == backup.FORMAT


def test_restore_validates_the_form(auth_client, superuser):
    response = auth_client.post(reverse('core:backup_restore'), {})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert set(response.context['restore_form'].errors) == {
        'backup_file',
        'passphrase',
        'confirm',
    }


@needs_gpg
def test_restore_requires_the_confirmation(auth_client, superuser, stocked):
    exported = backup.export_backup(PASSPHRASE)

    response = auth_client.post(
        reverse('core:backup_restore'),
        {
            'backup_file': SimpleUploadedFile('b.gpg', exported),
            'passphrase': PASSPHRASE,
        },
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.context['restore_form'].errors['confirm']


@needs_gpg
def test_restore_view_replaces_data_and_signs_everyone_out(
    auth_client, superuser, stocked
):
    exported = backup.export_backup(PASSPHRASE)
    extra = ItemFactory(category=stocked.category, name='Added later')
    extra.save()
    _settle()

    response = auth_client.post(
        reverse('core:backup_restore'),
        {
            'backup_file': SimpleUploadedFile('b.gpg', exported),
            'passphrase': PASSPHRASE,
            'confirm': 'on',
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('core:login')
    assert not Item.objects.filter(name='Added later').exists()
    assert Item.objects.filter(name='Rice').exists()
    after = auth_client.get(reverse('inventory:dashboard'))
    assert after.status_code == HTTPStatus.FOUND  # the session is gone


@needs_gpg
def test_restore_view_reports_a_wrong_passphrase(
    auth_client, superuser, stocked
):
    exported = backup.export_backup(PASSPHRASE)

    response = auth_client.post(
        reverse('core:backup_restore'),
        {
            'backup_file': SimpleUploadedFile('b.gpg', exported),
            'passphrase': 'wrong wrong wrong',
            'confirm': 'on',
        },
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert 'Senha incorreta' in response.content.decode()
    assert Item.objects.filter(name='Rice').exists()
