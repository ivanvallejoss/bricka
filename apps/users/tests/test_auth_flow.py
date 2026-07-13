import pytest
from django.urls import reverse

from apps.contacts.tests.factories import UserFactory
from apps.users.forms import EmailAuthenticationForm

pytestmark = pytest.mark.django_db

PASSWORD = "correcto-horizonte-42"
NEW_PASSWORD = "otro-horizonte-mas-largo-77"


@pytest.fixture
def credentialed_user():
    """
    A diferencia de `actor` (pensada para force_login), esta fixture
    tiene una password conocida: los tests de flujo atraviesan el
    stack completo de authenticate(), que force_login saltea.
    """
    user = UserFactory(email="socio@bricka.com")
    user.set_password(PASSWORD)
    user.save()
    return user


class TestLoginFlow:
    def test_login_with_valid_credentials_redirects_to_default(
        self, client, credentialed_user
    ):
        response = client.post(
            reverse("users:login"),
            {"username": "socio@bricka.com", "password": PASSWORD},
        )
        assert response.status_code == 302
        assert response.url == reverse("properties:list")

    def test_login_respects_next_parameter(self, client, credentialed_user):
        response = client.post(
            reverse("users:login"),
            {
                "username": "socio@bricka.com",
                "password": PASSWORD,
                "next": "/backoffice/contacts/",
            },
        )
        assert response.status_code == 302
        assert response.url == "/backoffice/contacts/"

    def test_login_discards_external_next(self, client, credentialed_user):
        # url_has_allowed_host_and_scheme en acción: el next hostil
        # se descarta y gana LOGIN_REDIRECT_URL.
        response = client.post(
            reverse("users:login"),
            {
                "username": "socio@bricka.com",
                "password": PASSWORD,
                "next": "https://malicioso.com/",
            },
        )
        assert response.status_code == 302
        assert response.url == reverse("properties:list")

    def test_login_with_wrong_password_shows_ambiguous_error(
            self, client, credentialed_user
        ):
        response = client.post(
            reverse("users:login"),
            {"username": "socio@bricka.com", "password": "incorrecta"},
        )
        assert response.status_code == 200
        expected = EmailAuthenticationForm.error_messages["invalid_login"]
        # Mecanismo: el error es non-field (postura ambigua — no revela
        # si la casilla existe) y llega al form del contexto.
        assert list(response.context["form"].non_field_errors()) == [expected]
        # Renderizado: el template efectivamente lo muestra.
        assert expected in response.content.decode()

    def test_authenticated_user_visiting_login_is_redirected(self, auth_client):
        # redirect_authenticated_user=True
        response = auth_client.get(reverse("users:login"))
        assert response.status_code == 302


class TestLogoutFlow:
    def test_logout_via_post_ends_session(self, client, credentialed_user):
        client.force_login(credentialed_user)
        response = client.post(reverse("users:logout"))
        assert response.status_code == 302
        assert response.url == reverse("users:login")
        # La sesión murió de verdad: el próximo request al backoffice
        # vuelve a rebotar en el middleware.
        assert client.get("/backoffice/contacts/").status_code == 302

    def test_logout_via_get_is_rejected(self, client, credentialed_user):
        # Django 5: LogoutView es POST-only. Si esto falla algún día,
        # alguien puso un <a> donde va un <form>.
        client.force_login(credentialed_user)
        assert client.get(reverse("users:logout")).status_code == 405


class TestPasswordChangeFlow:
    def test_password_change_requires_authentication(self, client):
        response = client.get(reverse("users:password-change"))
        assert response.status_code == 302

    def test_password_change_rejects_weak_password(self, client, credentialed_user):
        client.force_login(credentialed_user)
        response = client.post(
            reverse("users:password-change"),
            {
                "old_password": PASSWORD,
                "new_password1": "1",
                "new_password2": "1",
            },
        )
        assert response.status_code == 200  # re-render con errores
        assert credentialed_user.check_password("1") is False

    def test_password_change_succeeds_and_keeps_session(
        self, client, credentialed_user
    ):
        client.force_login(credentialed_user)
        response = client.post(
            reverse("users:password-change"),
            {
                "old_password": PASSWORD,
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )
        assert response.status_code == 302
        assert response.url == reverse("users:password-change-done")
        credentialed_user.refresh_from_db()
        assert credentialed_user.check_password(NEW_PASSWORD)
        # PasswordChangeView llama update_session_auth_hash: cambiar
        # la propia contraseña NO cierra la sesión actual (sí las demás).
        assert client.get("/backoffice/contacts/").status_code == 200