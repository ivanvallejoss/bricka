import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from .managers import ActiveUserManager, AllUsersManager


class UserGroup:
    """
    Constantes de grupos del sistema.
    Los grupos se crean via data migration — ver 0002_create_groups.
    
    Uso:
        user.groups.filter(name=UserGroup.SOCIO).exists()
        Group.objects.get(name=UserGroup.AGENTE)
    """
    SOCIO = "socio"
    AGENTE = "agente"

    ALL = [SOCIO, AGENTE]


class User(AbstractUser):
    """
    Usuario del sistema Bricka.

    Hereda AbstractUser — no hereda BaseModel porque AbstractUser
    ya define su propio PK y campos de auditoría (date_joined, last_login).
    UUID PK y deleted_at se declaran manualmente.

    Roles via Django Groups — ver UserGroup.
    Login por email o username (username se mantiene como campo auxiliar).

    Soft delete coordina deleted_at + is_active para garantizar
    que usuarios archivados no puedan autenticarse.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    phone = models.CharField(max_length=20, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActiveUserManager()
    all_objects = AllUsersManager()

    def soft_delete(self):
        """
        Archiva el usuario. Coordina dos mecanismos:
        - deleted_at: excluye del manager default
        - is_active = False: bloquea autenticación via auth backend de Django
        """
        self.deleted_at = timezone.now()
        self.is_active = False
        self.save(update_fields=["deleted_at", "is_active"])

    def restore(self):
        """
        Reactiva un usuario archivado.
        """
        self.deleted_at = None
        self.is_active = True
        self.save(update_fields=["deleted_at", "is_active"])

    def is_socio(self) -> bool:
        return self.groups.filter(name=UserGroup.SOCIO).exists()

    def is_agente(self) -> bool:
        return self.groups.filter(name=UserGroup.AGENTE).exists()

    class Meta:
        base_manager_name = "all_objects"
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"