import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from testcontainers.postgres import PostgresContainer

from tests.inventory.factories import (
    BatchFactory,
    CategoryFactory,
    ItemFactory,
    LocationFactory,
)


@pytest.fixture(scope='session')
def django_db_modify_db_settings_parallel_suffix():
    return None


@pytest.fixture(scope='session', autouse=True)
def _postgres_container():
    with PostgresContainer('postgres:17', driver=None) as postgres:
        db = settings.DATABASES['default']
        db.update(
            HOST=postgres.get_container_host_ip(),
            PORT=postgres.get_exposed_port(5432),
            NAME=postgres.dbname,
            USER=postgres.username,
            PASSWORD=postgres.password,
        )
        yield postgres


@pytest.fixture
def category(db):
    obj = CategoryFactory()
    obj.save()
    return obj


@pytest.fixture
def location(db):
    obj = LocationFactory()
    obj.save()
    return obj


@pytest.fixture
def item(category):
    obj = ItemFactory(category=category)
    obj.save()
    return obj


@pytest.fixture
def batch(item, location):
    obj = BatchFactory(item=item, location=location)
    obj.save()
    return obj


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username='ana', password='s3cret-pass'
    )


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client
