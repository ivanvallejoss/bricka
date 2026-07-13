from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class EmailBackend(ModelBackend):
    """
    Autentica por email (case-insensitive) delegando la verificación
    de password y de is_active en ModelBackend.

    Contrato de la cadena de backends: AuthenticationForm siempre pasa
    lo tipeado como `username=`, sin importar qué representa. Acá ese
    valor es el email.

    Invariantes de las que depende:
    - Unicidad case-insensitive de email (constraint parcial en User,
      migración 0003) — sin ella, email__iexact puede devolver 2 filas.
    - User.objects es ActiveUserManager: los soft-deleted quedan fuera
      del lookup. Doble candado con is_active=False vía
      user_can_authenticate().
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            # Sin esta guarda, email="" matchearía a los usuarios sin
            # email cargado (excluidos del constraint parcial).
            return None
        try:
            user = User.objects.get(email__iexact=username)
        except User.DoesNotExist:
            # Mismo patrón que ModelBackend: correr el hasher igual,
            # para que "email inexistente" y "password incorrecta"
            # tarden lo mismo y no se pueda enumerar casillas por timing.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None