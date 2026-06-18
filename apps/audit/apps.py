# apps/audit/apps.py
from django.apps import AppConfig


class AuditConfig(AppConfig):
    name = "apps.audit"
    verbose_name = "Auditoría"

    def ready(self):
        import apps.audit.signals  # noqa: F401