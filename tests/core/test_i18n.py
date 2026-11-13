import gettext
import re
from decimal import Decimal
from http import HTTPStatus
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import translation
from freezegun import freeze_time

from apps.inventory import services
from apps.inventory.exceptions import InvalidQuantity
from apps.inventory.models import Item

LOCALE_DIR = Path(settings.BASE_DIR) / 'locale'
PLACEHOLDER = re.compile(r'%\(\w+\)s')
STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _unescape(text):
    return re.sub(
        r'\\(.)',
        lambda m: {'n': '\n'}.get(m.group(1), m.group(1)),
        text,
    )


def _join(parts):
    return _unescape(''.join(parts))


def _read_po(lang):
    """Return {(context, msgid): msgstr} for a locale's .po file.

    Plural entries map to their forms joined with a NUL character.
    """
    entries, current, field = {}, {}, None

    def flush():
        if current.get('id'):
            forms = current.get('forms')
            text = (
                '\x00'.join(forms[i] for i in sorted(forms))
                if forms
                else current['str']
            )
            entries[(current.get('ctx', ''), current['id'])] = text
        current.clear()

    for line in (
        (LOCALE_DIR / lang / 'LC_MESSAGES/django.po')
        .read_text(encoding='utf-8')
        .splitlines()
    ):
        if not line.strip():
            flush()
            field = None
            continue
        match = re.match(
            r'(msgctxt|msgid_plural|msgid|msgstr)(\[(\d)\])? (.*)', line
        )
        if match:
            name, index, rest = match.group(1), match.group(3), match.group(4)
            value = _join(STRING.findall(rest))
            if name == 'msgstr' and index is not None:
                current.setdefault('forms', {})[int(index)] = value
                field = ('forms', int(index))
            else:
                key = {
                    'msgctxt': 'ctx',
                    'msgid': 'id',
                    'msgid_plural': 'plural',
                    'msgstr': 'str',
                }[name]
                current[key] = value
                field = (key, None)
        elif line.startswith('"') and field:
            extra = _join(STRING.findall(line))
            key, index = field
            if key == 'forms':
                current['forms'][index] += extra
            else:
                current[key] += extra
    flush()
    return entries


def _login_page(client, language):
    client.cookies.load({settings.LANGUAGE_COOKIE_NAME: language})
    return client.get(reverse('core:login')).content.decode()


@pytest.mark.parametrize(
    ('language', 'text', 'html_lang'),
    [
        ('pt-br', 'Entre para ver seu estoque.', 'pt-br'),
        ('en-us', 'Sign in to see your inventory.', 'en-us'),
    ],
)
def test_set_language_switches_the_interface(
    client, db, language, text, html_lang
):
    response = client.post(
        reverse('core:set_language'),
        {'language': language, 'next': reverse('core:login')},
    )
    page = client.get(reverse('core:login')).content.decode()

    assert response.status_code == HTTPStatus.FOUND
    assert response.cookies[settings.LANGUAGE_COOKIE_NAME].value == language
    assert text in page
    assert f'<html lang="{html_lang}">' in page


def test_set_language_ignores_unsupported_language(client, db):
    client.post(reverse('core:set_language'), {'language': 'es'})

    page = client.get(reverse('core:login')).content.decode()

    assert 'Entre para ver seu estoque.' in page


@pytest.mark.parametrize(
    ('header', 'text'),
    [
        ('en-GB,en;q=0.8', 'Sign in to see'),
        ('pt-PT', 'Entre para ver'),
        ('es-AR,es;q=0.9', 'Entre para ver'),
        ('fr-FR', 'Entre para ver'),
    ],
)
def test_browser_language_is_used_when_there_is_no_cookie(
    client, db, header, text
):
    response = client.get(
        reverse('core:login'), headers={'Accept-Language': header}
    )

    assert text in response.content.decode()


def test_login_page_language_switcher_marks_the_current_language(client, db):
    client.cookies.load({settings.LANGUAGE_COOKIE_NAME: 'en-us'})

    page = client.get(reverse('core:login')).content.decode()

    assert '<option value="en-us" selected>' in page
    assert 'name="language"' in page


def test_language_switcher_does_not_send_users_back_to_post_only_urls(
    client, db
):
    page = client.post(
        reverse('core:login'), {'username': 'nobody', 'password': 'x'}
    ).content.decode()

    assert re.search(r'name="next" value="/"', page)


def test_signed_in_pages_have_no_header_language_switcher(auth_client):
    page = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert 'name="language"' not in page


@freeze_time('2026-11-05 15:00')
@pytest.mark.parametrize(
    ('language', 'expected'),
    [
        ('pt-br', 'de Novembro de 2026'),
        ('en-us', 'November 5, 2026'),
    ],
)
def test_dashboard_date_follows_language(auth_client, language, expected):
    auth_client.cookies.load({settings.LANGUAGE_COOKIE_NAME: language})

    page = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert expected.lower() in page.lower()


@pytest.mark.parametrize(
    ('language', 'expected'),
    [('pt-br', '31/01/2030'), ('en-us', '01/31/2030')],
)
def test_short_dates_follow_language(auth_client, batch, language, expected):
    batch.expires_at = '2030-01-31'
    batch.save()
    auth_client.cookies.load({settings.LANGUAGE_COOKIE_NAME: language})

    page = auth_client.get(
        reverse('inventory:item_detail', args=[batch.item_id])
    ).content.decode()

    assert expected in page


def test_unit_symbols_are_translated(category):
    item = Item(unit='box')

    with translation.override('pt-br'):
        assert str(item.unit_symbol) == 'cx'
    with translation.override('en-us'):
        assert str(item.unit_symbol) == 'box'


def test_service_messages_follow_language(item, location):
    messages = {}
    for language in ('pt-br', 'en-us'):
        with (
            translation.override(language),
            pytest.raises(InvalidQuantity) as error,
        ):
            services.add_stock(item, location, Decimal(0))
        messages[language] = str(error.value)

    assert messages == {
        'pt-br': 'A quantidade deve ser maior que zero.',
        'en-us': 'Quantity must be greater than zero.',
    }


@pytest.mark.parametrize('lang', ['pt_BR'])
def test_catalog_is_complete(lang):
    entries = _read_po(lang)

    untranslated = [
        key for key, text in entries.items() if not all(text.split('\x00'))
    ]
    assert not untranslated


@pytest.mark.parametrize('lang', ['pt_BR'])
def test_catalog_keeps_placeholders(lang):
    broken = [
        key
        for (_, msgid), text in _read_po(lang).items()
        for key in [msgid]
        if set(PLACEHOLDER.findall(msgid)) != set(PLACEHOLDER.findall(text))
    ]

    assert not broken


@pytest.mark.parametrize('lang', ['pt_BR'])
def test_compiled_catalog_matches_the_po_file(lang):
    mo = LOCALE_DIR / lang / 'LC_MESSAGES/django.mo'
    compiled = gettext.GNUTranslations(mo.open('rb'))

    def compiled_text(key, text):
        context, msgid = key
        if '\x00' in text:  # plural: one form per count, 1 then 2, 3...
            forms = text.split('\x00')
            return '\x00'.join(
                compiled.ngettext(msgid, '', count)
                for count in range(1, len(forms) + 1)
            )
        if context:
            return compiled.pgettext(context, msgid)
        return compiled.gettext(msgid)

    stale = [
        key
        for key, text in _read_po(lang).items()
        if compiled_text(key, text) != text
    ]

    assert not stale
