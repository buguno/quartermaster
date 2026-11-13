import runpy
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings

ROOT = Path(settings.BASE_DIR)
PRODUCTION_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'
    },
}


def _load_gunicorn_config(monkeypatch, **env):
    for name in (
        'GUNICORN_BIND',
        'GUNICORN_WORKERS',
        'GUNICORN_THREADS',
        'GUNICORN_TIMEOUT',
        'GUNICORN_LOG_LEVEL',
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return runpy.run_path(str(ROOT / 'gunicorn.conf.py'))


def test_gunicorn_defaults_fit_a_raspberry_pi(monkeypatch):
    config = _load_gunicorn_config(monkeypatch)

    assert config['workers'] == 1
    assert config['threads'] == 2
    assert config['worker_class'] == 'gthread'
    assert config['bind'] == '0.0.0.0:8000'
    assert config['accesslog'] is None
    assert config['errorlog'] == '-'
    assert config['control_socket_disable'] is True
    assert config['max_requests'] > 0


def test_gunicorn_can_be_tuned_with_the_environment(monkeypatch):
    config = _load_gunicorn_config(
        monkeypatch,
        GUNICORN_BIND='127.0.0.1:9000',
        GUNICORN_WORKERS='2',
        GUNICORN_THREADS='4',
        GUNICORN_TIMEOUT='60',
        GUNICORN_LOG_LEVEL='warning',
    )

    assert config['bind'] == '127.0.0.1:9000'
    assert (config['workers'], config['threads']) == (2, 4)
    assert config['timeout'] == 60
    assert config['loglevel'] == 'warning'


def test_gunicorn_heartbeat_files_go_to_ram_when_possible(monkeypatch):
    monkeypatch.setattr(Path, 'is_dir', lambda self: str(self) == '/dev/shm')
    assert _load_gunicorn_config(monkeypatch)['worker_tmp_dir'] == '/dev/shm'

    monkeypatch.setattr(Path, 'is_dir', lambda self: False)
    assert _load_gunicorn_config(monkeypatch)['worker_tmp_dir'] is None


def test_static_files_collect_with_the_production_storage(tmp_path):
    """Same as `poetry collectstatic`; it once failed on Tailwind's source."""
    with override_settings(STORAGES=PRODUCTION_STORAGES, STATIC_ROOT=tmp_path):
        call_command('collectstatic', interactive=False, verbosity=0)

    collected = {path.name for path in tmp_path.rglob('*')}
    assert 'staticfiles.json' in collected
    assert any(
        name.startswith('tailwind.') and name != 'tailwind.css'
        for name in collected
    )
    assert 'input.css' not in collected


@pytest.mark.parametrize('environment', ['production', 'staging'])
def test_only_development_runs_with_debug(monkeypatch, environment):
    monkeypatch.setenv('ENVIRONMENT', environment)
    monkeypatch.setenv('SECRET_KEY', 'x')
    monkeypatch.setenv('ALLOWED_HOSTS', 'localhost')
    monkeypatch.setenv('DATABASE_URL', 'postgres://u:p@localhost/db')

    namespace = runpy.run_path(str(ROOT / 'config/settings.py'))

    assert namespace['DEBUG'] is False
    assert (
        namespace['STORAGES']['staticfiles']['BACKEND']
        == 'whitenoise.storage.CompressedManifestStaticFilesStorage'
    )


def test_development_keeps_the_default_static_storage(monkeypatch):
    monkeypatch.setenv('ENVIRONMENT', 'development')
    monkeypatch.setenv('SECRET_KEY', 'x')
    monkeypatch.setenv('ALLOWED_HOSTS', 'localhost')
    monkeypatch.setenv('DATABASE_URL', 'postgres://u:p@localhost/db')

    namespace = runpy.run_path(str(ROOT / 'config/settings.py'))

    assert namespace['DEBUG'] is True
    assert 'STORAGES' not in namespace
