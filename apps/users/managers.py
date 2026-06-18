from django.contrib.auth.models import UserManager


class ActiveUserManager(UserManager):
    """
    Manager default. Filtra usuarios soft-deleted.
    Extiende UserManager para preservar create_user y create_superuser.
    El auth backend usa este manager — usuarios soft-deleted no pueden autenticarse.
    """
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class AllUsersManager(UserManager):
    """
    Manager sin filtro. Uso explícito y FK traversal (base_manager_name).
    """
    pass