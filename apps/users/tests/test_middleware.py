import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

PROTECTED_URL = "/backoffice/contacts/"


class TestBackofficeLoginRequiredMiddleware:
    def test_anonymous_request_to_protected_path_redirects_with_next(self, client):
        response = client.get(PROTECTED_URL)
        assert response.status_code == 302
        assert response.url == f"{reverse('users:login')}?next={PROTECTED_URL}"

    def test_login_path_is_exempt_for_anonymous(self, client):
        # El test que mata el loop: antes de S8, esto redirigía a sí mismo.
        response = client.get(reverse("users:login"))
        assert response.status_code == 200

    def test_authenticated_request_passes_through(self, auth_client):
        assert auth_client.get(PROTECTED_URL).status_code == 200

    def test_non_backoffice_path_is_ignored(self, client):
        # /admin/ tiene su propia puerta; nuestro middleware no interviene.
        response = client.get("/admin/")
        assert response.status_code == 302
        assert response.url.startswith("/admin/login/")

    def test_htmx_request_with_expired_session_returns_hx_redirect(self, client):
        response = client.get(
            PROTECTED_URL,
            headers={
                "HX-Request": "true",
                "HX-Current-URL": "http://testserver/backoffice/contacts/?page=2",
            },
        )
        assert response.status_code == 200
        assert "HX-Redirect" in response.headers

    def test_htmx_next_points_to_current_url_not_partial_path(self, client):
        # El usuario está parado en la lista paginada; el partial que
        # disparó el request es otro path. El next debe volver a la
        # página, no al fragmento.
        response = client.get(
            "/backoffice/contacts/rows/algo/",
            headers={
                "HX-Request": "true",
                "HX-Current-URL": "http://testserver/backoffice/contacts/?page=2",
            },
        )
        assert response.headers["HX-Redirect"] == (
            f"{reverse('users:login')}?next=/backoffice/contacts/%3Fpage%3D2"
        )

    def test_htmx_request_with_foreign_current_url_omits_next(self, client):
        # Origen ajeno → current_url_abs_path es None → login sin next.
        response = client.get(
            PROTECTED_URL,
            headers={
                "HX-Request": "true",
                "HX-Current-URL": "https://malicioso.com/backoffice/",
            },
        )
        assert response.headers["HX-Redirect"] == reverse("users:login")