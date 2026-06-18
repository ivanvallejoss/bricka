from decimal import Decimal

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from apps.common.models import AuditableMixin


def _serialize_instance(instance) -> dict:
    """
    Serializa una instancia de modelo a dict JSON-compatible.
    Convierte UUIDs, datetimes y dates a strings.
    """
    data = {}
    for field in instance._meta.fields:
        value = getattr(instance, field.attname)
        if value is None:
            data[field.attname] = None
        elif hasattr(value, 'isoformat'):
            data[field.attname] = value.isoformat()
        elif hasattr(value, 'hex'):
            data[field.attname] = str(value)
        elif isinstance(value, Decimal):
            data[field.attname] = str(value)
        else:
            # int, str, bool - tipos nativos compatibles con
            # DjangoJSONEncoder que Django aplica al escribir en JSONField.
            data[field.attname] = value 
    return data


def _get_current(sender, pk):
    """
    Lee el estado actual de la DB antes de que se aplique el save.
    Usa all_objects si existe (SoftDeleteModel) para no fallar
    con registros soft-deleted. Fallback a objects para modelos
    sin soft delete (BillingDocument).
    """
    manager = getattr(sender, 'all_objects', sender.objects)
    try:
        return manager.get(pk=pk)
    except sender.DoesNotExist:
        return None


def _detect_action(before: dict | None, after: dict, created: bool) -> str:
    from apps.audit.models import AuditAction
    if created:
        return AuditAction.CREATE
    if before and after:
        before_deleted = before.get('deleted_at')
        after_deleted = after.get('deleted_at')
        if before_deleted and not after_deleted:
            return AuditAction.RESTORE
        if not before_deleted and after_deleted:
            return AuditAction.DELETE
    return AuditAction.UPDATE


@receiver(pre_save)
def capture_before(sender, instance, **kwargs):
    if not issubclass(sender, AuditableMixin):
        return
    if instance.pk:
        current = _get_current(sender, instance.pk)
        instance._audit_before = _serialize_instance(current) if current else None
    else:
        instance._audit_before = None


@receiver(post_save)
def log_change(sender, instance, created, **kwargs):
    if not issubclass(sender, AuditableMixin):
        return

    from apps.audit.models import AuditLog

    before = getattr(instance, '_audit_before', None)
    after = _serialize_instance(instance)
    action = _detect_action(before, after, created)

    actor_id = None
    if not created and hasattr(instance, 'updated_by_id'):
        actor_id = instance.updated_by_id
    elif hasattr(instance, 'created_by_id'):
        actor_id = instance.created_by_id

    AuditLog.objects.create(
        actor_id=actor_id,
        action=action,
        entity_type=sender.audit_entity_type(),
        entity_id=instance.pk,
        before=before,
        after=after,
    )