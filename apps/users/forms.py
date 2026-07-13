from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User 

class EmailAuthenticationForm(AuthenticationForm):
    """
    AuthenticationForm con el campo re-tipado a email.

    El campo SIGUE llamandose 'username' - es el contrato del form con
    la cadena de backends (ver EmailBackend). Solo cambia que valida y
    como se presenta: EmailField agrega validacion de foramto en server
    y 'type="email"' en el browser (teclado de email en mobile).
    """

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={"autofocus": True, "autocomplete": "email"}
        ),
    )

    error_messages = {
        # El default interpola el verbose_name del USERNAME_FIELD y
        # dirigia "nombre de usuario". Mensaje propio y deliberadamente
        # ambiguo: no revela si el email existe o si fallo la password.
        "invalid_login": "Email o contraseña incorrectos.",
        "inactive": "Esta cuenta esta inactiva.",
    }


class AdminUserCreationForm(UserCreationForm):
    """
    Form de alta del UserAdmin. Única diferencia con el de Django:
    email obligatorio — sin email no hay login (EmailBackend), y el
    default lo dejaría pasar vacío en silencio.
    """

    email = forms.EmailField(label="Email", required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")