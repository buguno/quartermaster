from django.conf import settings
from django.core.management import call_command


def test_timezone_and_language():
    assert settings.TIME_ZONE == 'America/Sao_Paulo'
    assert settings.LANGUAGE_CODE == 'pt-br'


def test_django_check_passes():
    call_command('check')


def test_database_is_postgres(db):
    assert settings.DATABASES['default']['ENGINE'].endswith('postgresql')
