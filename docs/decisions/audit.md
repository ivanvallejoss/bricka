# Convenciones de Audit Log — Bricka CRM

Registro de decisiones sobre trazabilidad, enforcement de integridad,
y comportamiento del audit log en el sistema.

---

## Modelos auditados vs modelos de infraestructura

No todos los modelos tienen audit. La distinción es funcional:

**Modelos auditados — heredan `SoftDeleteModel` + `AuditableMixin`:**

- `Property`
- `Listing`
- `Contact`
- `Deal`
- `RentalContract`

**Modelo auditable sin soft delete — hereda `BaseModel` + `AuditableMixin`:**

- `BillingDocument` — inmutable una vez emitido, pero sus emisiones
  y cancelaciones se registran

**Modelos de infraestructura — sin `AuditableMixin`:**

- `OutboundEvent` — Celery necesita `.update()` libremente
- `InboundEvent` — Celery necesita `.update()` libremente
- `AuditLog` — es el destino, no la fuente
- `ListingPriceHistory` — append-only, escrita atómicamente con `Listing`
- `DealStageHistory` — append-only, escrita atómicamente con `Deal`
- `RentAdjustment` — append-only, escrita atómicamente con `RentalContract`
- `PipelineStage` — configuración del sistema
- `PropertyMedia` — media, no sensible

---

## Enforcement de integridad — `AuditViolationError`

Los signals de Django **no disparan** en operaciones de queryset:
`.update()`, `.delete()`, `bulk_create()`. Sin enforcement activo,
estas operaciones dejarían el audit log silencioso sin ningún error.

**La restricción vive en runtime, no en documentación.**

`AuditableMixin` tiene dos responsabilidades independientes:

**1 — Enforcement de managers:**
Asigna `AuditedManager` como manager default. `AuditedManager` retorna
`AuditedQuerySet`, que sobreescribe `.update()` y `.delete()` lanzando
`AuditViolationError`. Para modelos que heredan `SoftDeleteModel`, este
enforcement ya está incluido via `AuditedSoftDeleteQuerySet` — pero
`AuditableMixin` se hereda igual por la segunda responsabilidad.

**2 — Marcador de clase para signals:**
`audit/signals.py` usa `issubclass(sender, AuditableMixin)` para
determinar si debe registrar cambios. Sin esta herencia, los signals
no disparan aunque el manager tenga el enforcement.

```python
# audit/signals.py
if not issubclass(sender, AuditableMixin):
    return  # sin este check, el signal dispara para TODOS los modelos
```

**`AuditableMixin` siempre se hereda explícitamente en modelos auditados,
incluso cuando `SoftDeleteModel` ya incluye el enforcement de managers.**

**Patrón canónico:**

```python
class Property(SoftDeleteModel, AuditableMixin): ...    # soft delete + audit
class BillingDocument(BaseModel, AuditableMixin): ...   # sin soft delete + audit
class OutboundEvent(TimestampModel): ...                # sin restricción
```

---

## Soft delete — único punto de borrado

`.delete()` en queryset lanza `AuditViolationError`. El único camino
válido para borrar una entidad auditada es:

```python
instance.soft_delete(actor=request.user)  # acción humana
instance.soft_delete()                     # acción del sistema (Celery)
```

`soft_delete()` emite un `UPDATE` sobre `deleted_at` y dispara
`post_save` signal → audit log. La fila nunca se elimina físicamente.

**Sin `actor` no significa dato faltante — significa acción del sistema.**

---

## Restricción de bulk ops — casos legítimos

Hay casos donde bulk ops son legítimos y necesarios:

**Management commands de migración inicial:**

```python
# apps/properties/management/commands/import_properties.py
# _default_manager bypasea AuditableManager explícitamente.
# Documentado como excepción — solo en comandos de migración inicial.
Property._default_manager.bulk_create(properties)
```

`_default_manager` en un service es una señal de alerta inmediata.
Su uso está permitido **únicamente** en management commands de
migración con justificación explícita en el código.

---

## Captura de `before` / `after`

El audit log registra el estado completo del objeto antes y después
de cada operación. Esto permite responder:

- ¿Quién cambió el precio de este listing y de cuánto a cuánto?
- ¿Cuál era el status de este contrato antes de archivarlo?
- ¿Qué campos exactamente modificó este usuario en esta operación?

**Implementación via dos signals en `audit/signals.py`:**

`pre_save` — captura el estado actual de la DB antes de que se
aplique el save. Lo almacena en `instance._audit_before` como
atributo temporal.

⚠️ `pre_save` emite una `SELECT` adicional por cada save en entidades
auditadas. Aceptable para el volumen de Bricka. En tests con loops
de saves el contador de queries puede ser sorprendente si no se anticipa.

```python
@receiver(pre_save)
def capture_before(sender, instance, **kwargs):
    if not issubclass(sender, AuditableMixin):
        return
    if instance.pk:
        current = _get_current(sender, instance.pk)
        instance._audit_before = _serialize_instance(current) if current else None
    else:
        instance._audit_before = None
```

`post_save` — lee `instance._audit_before`, serializa el estado
actual, detecta la acción, y escribe en `AuditLog`.

**Detección automática de acción:**

- `created=True` → `CREATE`
- `deleted_at` pasa de `null` a valor → `DELETE`
- `deleted_at` pasa de valor a `null` → `RESTORE`
- Cualquier otro caso → `UPDATE`

---

## Estrategia de serialización — `_serialize_instance`

Función custom que itera `instance._meta.fields`. Comportamiento explícito:

- **Solo campos locales** — sin joins, sin queries adicionales, sin riesgo de N+1
- **FKs como IDs raw** — `created_by_id` serializado como UUID string,
  no el objeto relacionado. El nombre del campo en el JSON es `created_by_id`,
  no `created_by`.
- **`datetime`/`date`** → ISO 8601 string via `.isoformat()`
- **`UUID`** → string via `.str()` - formato estandar con guiones.
- **`Decimal`** → `json.dumps` no maneja Decimal nativamente por lo que se debe convertir con `str(value)`
- **Atributos temporales** como `_audit_before` no son campos del modelo
  — no se incluyen
- **Campos de contraseña** — no aplica en este sistema. `User` no hereda
  `AuditableMixin` y por lo tanto nunca se serializa.

---

## `actor_id` — quién ejecutó la acción

El audit log resuelve el actor desde los campos del modelo:

```python
actor_id = instance.updated_by_id  # update/delete/restore
actor_id = instance.created_by_id  # create
actor_id = None                     # acción de Celery
```

No se usan thread-locals ni middleware de inyección de usuario.
El actor se pasa explícitamente al service, que lo asigna a
`updated_by` antes de llamar `.save()`.

**Responsabilidad del service:**

```python
def update_contact(contact: Contact, data: dict, actor: User) -> Contact:
    contact.updated_by = actor
    # ... aplicar cambios
    contact.save()  # dispara signal → audit log con actor correcto
    return contact
```

---

## `AuditLog` — modelo sin base class

`AuditLog` declara todos sus campos explícitamente sin heredar
de `BaseModel`, `TimestampModel` ni ninguna clase de `common/`.

**Motivos:**

- No tiene `updated_at` — es completamente append-only
- No tiene `created_by`/`updated_by` — tiene `actor_id` propio
  con semántica específica
- No tiene `deleted_at` — nunca se borra
- `actor_id` es UUID sin FK — ver `docs/decisions/design.md`

---

## Índices en `AuditLog`

```python
indexes = [
    models.Index(fields=["entity_type", "entity_id"]),  # consulta por entidad
    models.Index(fields=["actor_id"]),                   # consulta por actor
    models.Index(fields=["created_at"]),                 # consulta temporal
]
```

Las consultas más frecuentes son "dame el historial de esta entidad"
y "dame todas las acciones de este usuario". Los índices están
optimizados para esos dos patrones.
