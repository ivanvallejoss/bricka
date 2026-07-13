import pytest
from django.contrib.auth import authenticate
from django.db import IntegrityError

from apps.contacts.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "s8-session-pass"


def _user_with_password(**kwargs):
    user = UserFactory(**kwargs)
    user.set_password(PASSWORD)
    user.save()
    return user


class TestEmailBackend:
    def test_authenticate_succeeds_with_valid_email_and_password(self):
        user = _user_with_password(email="socio@bricka.com")
        assert authenticate(username="socio@bricka.com", password=PASSWORD) == user

    def test_authenticate_is_case_insensitive_on_email(self):
        user = _user_with_password(email="socio@bricka.com")
        assert authenticate(username="SOCIO@Bricka.COM", password=PASSWORD) == user

    def test_authenticate_fails_with_wrong_password(self):
        _user_with_password(email="socio@bricka.com")
        assert authenticate(username="socio@bricka.com", password="otra") is None

    def test_authenticate_fails_with_unknown_email(self):
        assert authenticate(username="nadie@bricka.com", password=PASSWORD) is None

    def test_authenticate_fails_with_empty_email(self):
        _user_with_password(email="")
        assert authenticate(username="", password=PASSWORD) is None

    def test_authenticate_fails_for_soft_deleted_user(self):
        user = _user_with_password(email="archivado@bricka.com")
        user.soft_delete()
        assert authenticate(username="archivado@bricka.com", password=PASSWORD) is None


class TestEmailUniqueness:
    def test_save_normalizes_email_to_lowercase(self):
        user = UserFactory(email="Socio@Bricka.COM")
        user.refresh_from_db()
        assert user.email == "socio@bricka.com"

    def test_create_duplicate_email_raises_integrity_error(self):
        UserFactory(email="socio@bricka.com")
        with pytest.raises(IntegrityError):
            UserFactory(email="SOCIO@bricka.com")

    def test_multiple_users_with_empty_email_are_allowed(self):
        UserFactory(email="")
        UserFactory(email="")  # no debe explotar: constraint parcial