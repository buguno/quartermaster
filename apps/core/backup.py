"""Encrypted export and import of all application data.

The data is serialized with Django's own `dumpdata` (database independent, so a
backup can be restored on another machine) and encrypted with GnuPG using a
symmetric passphrase that is never stored. The result is a standard `.gpg`
file that `gpg --decrypt` can open anywhere.
"""

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.base import DeserializationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import BackupError

FORMAT = 'quartermaster-backup'
VERSION = 1
EXCLUDED = [
    'contenttypes',
    'sessions',
    'admin.logentry',
    'auth.permission',
]
GPG_TIMEOUT = 120


def filename(now: datetime | None = None) -> str:
    now = now or timezone.localtime()
    return f'quartermaster-{now:%Y%m%d-%H%M%S}.backup.gpg'


# --- GnuPG ----------------------------------------------------------------


def _gpg(arguments: list[str], data: bytes, passphrase: str) -> bytes:
    """Run gpg symmetrically; the passphrase travels over a private pipe."""
    gpg = shutil.which('gpg')
    if gpg is None:
        raise BackupError(_('GnuPG (gpg) is not installed on this machine.'))

    read_end, write_end = os.pipe()
    try:
        os.write(write_end, passphrase.encode())
        os.close(write_end)
        with tempfile.TemporaryDirectory() as home:
            os.chmod(home, 0o700)  # noqa: S103
            command = [
                gpg,
                '--batch',
                '--yes',
                '--quiet',
                '--no-options',
                '--homedir',
                home,
                '--pinentry-mode',
                'loopback',
                '--passphrase-fd',
                str(read_end),
                *arguments,
            ]
            try:
                result = subprocess.run(  # noqa: S603
                    command,
                    input=data,
                    capture_output=True,
                    pass_fds=(read_end,),
                    timeout=GPG_TIMEOUT,
                    check=False,
                )
            finally:
                subprocess.run(  # noqa: S603
                    [shutil.which('gpgconf') or 'gpgconf', '--homedir', home]
                    + ['--kill', 'gpg-agent'],
                    capture_output=True,
                    check=False,
                )
    finally:
        os.close(read_end)

    if result.returncode != 0:
        raise BackupError(
            _('Wrong passphrase, or the file is not a valid backup.')
        )
    return result.stdout


def encrypt(data: bytes, passphrase: str) -> bytes:
    return _gpg(
        ['--symmetric', '--cipher-algo', 'AES256', '--compress-algo', 'zlib'],
        data,
        passphrase,
    )


def decrypt(data: bytes, passphrase: str) -> bytes:
    return _gpg(['--decrypt'], data, passphrase)


# --- Data -----------------------------------------------------------------


def _schema_state() -> dict[str, str]:
    """Latest migration of every app: a backup only fits the same schema."""
    leaves = MigrationLoader(connection).graph.leaf_nodes()
    return dict(sorted(leaves))


def _dump_data() -> list:
    output = StringIO()
    call_command(
        'dumpdata',
        natural_foreign=True,
        natural_primary=True,
        exclude=EXCLUDED,
        stdout=output,
    )
    return json.loads(output.getvalue())


def export_backup(passphrase: str) -> bytes:
    """All data, serialized and encrypted with `passphrase`."""
    document = {
        'format': FORMAT,
        'version': VERSION,
        'created_at': timezone.now().isoformat(),
        'schema': _schema_state(),
        'data': _dump_data(),
    }
    return encrypt(json.dumps(document).encode(), passphrase)


def _read_document(encrypted: bytes, passphrase: str) -> dict:
    try:
        document = json.loads(decrypt(encrypted, passphrase))
    except (ValueError, UnicodeDecodeError) as error:
        raise BackupError(
            _('The file is not a Quartermaster backup.')
        ) from error

    valid = (
        isinstance(document, dict)
        and document.get('format') == FORMAT
        and document.get('version') == VERSION
        and isinstance(document.get('data'), list)
    )
    if not valid:
        raise BackupError(_('The file is not a Quartermaster backup.'))
    if document.get('schema') != _schema_state():
        raise BackupError(
            _('This backup was made by a different version of the system.')
        )
    return document


def restore_backup(encrypted: bytes, passphrase: str) -> None:
    """Replace ALL current data with the backup's, or change nothing."""
    document = _read_document(encrypted, passphrase)

    with tempfile.TemporaryDirectory() as folder:
        fixture = Path(folder) / 'backup.json'
        fixture.write_text(json.dumps(document['data']))
        try:
            with transaction.atomic():
                call_command('flush', interactive=False, verbosity=0)
                call_command('loaddata', str(fixture), verbosity=0)
        except (
            CommandError,
            DeserializationError,
            IntegrityError,
            ValueError,
            KeyError,
        ) as error:
            raise BackupError(
                _('The backup data is damaged and nothing was changed.')
            ) from error
