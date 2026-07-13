from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from .forms import EmailAuthenticationForm

app_name = "users"

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="users/login.html",
            authentication_form=EmailAuthenticationForm,
            # Un autenticado que visita /login/ va directo a
            # LOGIN_REDIRECT_URL en vez de ver el form de nuevo.
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path(
        "logout/",
        # POST-only en Django 5.0 — el hook de UI debe ser un <form>,
        # nunca un <a>. Redirige a LOGOUT_REDIRECT_URL.
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            template_name="users/password_change.html",
            success_url=reverse_lazy("users:password-change-done"),
        ),
        name="password-change",
    ),
    path(
        "password/change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="users/password_change_done.html",
        ),
        name="password-change-done",
    ),
]