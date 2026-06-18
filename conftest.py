import pytest

from apps.contacts.tests.factories import UserFactory


@pytest.fixture
def actor(db):
    return UserFactory()


@pytest.fixture
def auth_client(client, actor):
    client.force_login(actor)
    return client
