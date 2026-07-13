from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import AdminUserCreationForm
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Herramienta de alta y gestión de usuarios (política S8: solo
    superuser entra al admin). Extiende el UserAdmin de Django para
    conservar el manejo de passwords (hash, form de cambio, link
    "este formulario no muestra la contraseña").

    Muestra también los soft-deleted (all_objects): archivar/restaurar
    pasa por soft_delete()/restore() del modelo — nunca por el delete
    del admin, que sería hard delete.
    """

    add_form = AdminUserCreationForm

    list_display = (
        "username", "email", "first_name", "last_name",
        "is_active", "deleted_at",
    )
    list_filter = ("is_active", "groups")
    readonly_fields = ("deleted_at", "last_login", "date_joined")
    actions = ("archive_users", "restore_users")

    fieldsets = BaseUserAdmin.fieldsets + (
        ("Bricka", {"fields": ("phone", "deleted_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "password1", "password2", "groups"),
            },
        ),
    )

    def get_queryset(self, request):
        # El admin es la única superficie que ve archivados.
        return User.all_objects.all()

    @admin.action(description="Archivar usuarios seleccionados")
    def archive_users(self, request, queryset):
        for user in queryset:
            user.soft_delete()

    @admin.action(description="Restaurar usuarios seleccionados")
    def restore_users(self, request, queryset):
        for user in queryset:
            user.restore()