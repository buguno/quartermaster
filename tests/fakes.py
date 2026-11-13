"""Fake data for the tests, so no password or passphrase is written in them."""

from faker import Faker

fake = Faker()

PASSWORD = fake.password(length=20)
NEW_PASSWORD = fake.password(length=20)
PASSPHRASE = fake.password(length=20)
