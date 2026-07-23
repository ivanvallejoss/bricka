
# Registro de decisiones (ADR)

Cada entrada: contexto, decisión y trade-off aceptado.

## Modelos base y herencia

### `BaseModel` — raíz de modelos de dominio

**Decisión:** Clase base abstracta para todos los modelos del sistema, directo
o vía `SoftDeleteModel`.

**Aporta:** UUID PK, `created_at`/`updated_at`, y FK nullable
`created_by`/`updated_by`.

**Convención de `null`:** en `created_by`/`updated_by`, `null` = acción
ejecutada por el sistema (Celery). Ver entrada dedicada.

**No aplicar a** tablas de infraestructura que necesiten bulk ops
(`InboundEvent`, `OutboundEvent`, `AuditLog`).

---

### `SoftDeleteModel` — soft delete + enforcement de audit

**Decisión:** Extiende `BaseModel` con `deleted_at` y dos managers.

- `objects`: manager filtrado (`deleted_at IS NULL`). Uso default.
- `all_objects`: manager sin filtro, para acceder a registros archivados.
- `base_manager_name = "all_objects"`: FK traversal nunca explota aunque el
  registro relacionado esté soft-deleted.
- `.update()` y `.delete()` en queryset levantan `AuditViolationError` —
  usar `instance.soft_delete()` o el service correspondiente.

**`soft_delete(actor=None)` / `restore(actor=None)`:** únicos puntos de
borrado/restauración. Disparan el `post_save` signal hacia el audit log.
`updated_by = actor` se asigna de forma incondicional (`None` = sistema).

**Soft delete en `User`** coordina dos mecanismos: `deleted_at` (excluye del
manager default) e `is_active = False` (bloquea autenticación).

---

### `TimestampModel` — base para tablas auxiliares

**Decisión:** Base mínima con UUID PK y timestamps, sin `created_by`/
`updated_by`.

**Usar cuando:** la tabla es append-only o sus filas se reemplazan en vez de
editarse, y `updated_by` no tendría semántica real (siempre sería null).

**Ejemplos:** `PropertyMedia`, `ListingPriceHistory`, `DealStageHistory`,
`RentAdjustment`. Donde se necesita saber quién creó la fila, `created_by` se
declara manualmente (ej: `PropertyMedia`, `ListingPriceHistory`).

---

### `AuditableMixin` — enforcement para modelos sin soft delete

**Decisión:** Aporta el manager auditado (`AuditedManager`) y el classmethod
`audit_entity_type()` a modelos que NO heredan `SoftDeleteModel`.

**Aplica solo cuando** el modelo no tiene soft delete (ej: `BillingDocument`).
Si hereda `SoftDeleteModel`, el enforcement ya está incluido.

---

### `User` — no hereda `BaseModel`

**Decisión:** `User` hereda `AbstractUser`. UUID PK y `deleted_at` se declaran
manualmente.

**Justificación:** `AbstractUser` ya define su propio PK entero. `BaseModel`
también define UUID PK. Django no puede resolver dos PKs en la misma jerarquía.

**Campos omitidos respecto a `BaseModel`:**

- `created_by` / `updated_by` — trazabilidad administrativa innecesaria para el
  caso de uso de Bricka en V1.
- `updated_at` — `AbstractUser` no lo tiene; `soft_delete()` usa
  `update_fields=["deleted_at", "is_active"]` explícitamente.

---

## Identidad y trazabilidad

### PKs — UUID sobre ULID

**Decisión:** `UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`
en todos los modelos.

**Contexto:** El documento original mencionaba ULIDs en requerimientos no
funcionales pero UUID en decisiones transversales. Contradicción resuelta a
favor de UUID.

**Justificación:** Bricka es una inmobiliaria mediana. El volumen no va a rozar
los límites de UUIDv4. La complejidad adicional de ULIDs (librería externa,
ordering temporal) no tiene retorno visible en este contexto.

---

### `tenant_id` — eliminado

**Decisión:** `tenant_id` no existe en ninguna tabla.

**Contexto:** El documento original lo incluía como preparación para
multi-tenancy futuro. Eliminado tras re-consultas con Bricka.

**Justificación:** Bricka no tiene perspectiva de expansión multi-tenant en el
corto plazo. Una columna con un único valor constante en todas las tablas es
infraestructura en desuso que agrega ruido sin retorno. Si en el futuro se
requiere multi-tenancy, la migración se diseña en ese momento con un caso de
uso real.

---

### `created_by` / `updated_by` — null = sistema

**Decisión:** FK a `users.User` con `null=True` y `on_delete=SET_NULL`.

**Convención:** `null` es semánticamente equivalente a "acción ejecutada por el
sistema" — específicamente tareas Celery que operan sin contexto de request. No
existe un "system user" especial.

**Implicancias:**

- Cualquier código que lea estos campos debe tratar `null` como origen del
  sistema, no como dato faltante.
- `related_name="+"` desactiva el related manager inverso en todos los casos.
- `SET_NULL` como `on_delete`: si un usuario se elimina físicamente (que con
  soft delete no debería ocurrir), el campo queda null en lugar de romper
  registros existentes.

**Excepción documentada:** `RentAdjustment.applied_by` es no nullable con
`PROTECT` — ver entrada correspondiente.

---

### `AuditLog.actor_id` — UUID sin FK

**Decisión:** `actor_id = UUIDField(null=True)` sin FK a `users.User`.

**Justificación:**

- FK + `SET_NULL` perdería la identidad del actor ante un borrado físico de
  usuario.
- FK + `PROTECT` impediría borrar usuarios con historial de auditoría.
- UUID preserva la identidad permanentemente sin restricciones.

`null` en `actor_id` indica acción ejecutada por Celery — misma convención que
`created_by`/`updated_by`.

---

### `RentAdjustment.applied_by` — excepción a la convención

**Decisión:** `applied_by` es FK no nullable con `on_delete=PROTECT`.

**Contexto:** Excepción explícita a la convención general de `SET_NULL` +
nullable.

**Justificación:** `applied_by` no es trazabilidad administrativa — es una
certificación. El registro dice "este ajuste fue aprobado por esta persona". Si
`applied_by` se pierde, el registro pierde su valor auditivo completo.

- **No nullable:** no existe un ajuste aprobado sin un aprobador.
- **PROTECT:** si alguien intenta borrar físicamente al usuario que aprobó
  ajustes, la DB lo frena. Con soft delete esto nunca se activa en la práctica.

---

## Modelado de dominio

### `ContactRole` — campo único en V1

**Decisión:** `role = CharField(choices=ContactRole.choices, blank=True)` en
lugar de JSONB array o booleanos por rol.

**Contexto:** El documento original usaba JSONB array para soportar múltiples
roles simultáneos por contacto.

**Justificación:** En V1 cada contacto tiene un solo rol simultáneo. JSONB
agrega complejidad de querying sin retorno. Booleanos múltiples son
sobreingeniería para un caso que no existe todavía.

**⚠️ Deuda documentada:** Si en el futuro un contacto puede ser propietario e
inquilino al mismo tiempo, este campo requiere migración a booleanos o tabla de
relación. Revisar antes de implementar esa funcionalidad.

---

### `assigned_agent` — semántica flexible

**Decisión:** `assigned_agent` es editable post-creación. La semántica es
deliberadamente flexible: puede indicar quién originó el contacto o quién lo
está trabajando actualmente.

**Contexto:** Bricka opera con pocos agentes donde cualquiera puede trabajar con
cualquier contacto. La inmobiliaria define su propio uso con la práctica.

**⚠️ Revisar en V2** si aparece necesidad de separar ambos conceptos en campos
distintos (`sourced_by` vs `assigned_to`).

---

### `PipelineStage` y `DealStageHistory` — inactivos en V1

**Decisión:** Las tablas existen y tienen migraciones aplicadas. `Deal.stage`
es nullable — ningún flujo de V1 requiere interacción con estas tablas.

**Contexto:** Bricka no está interesada en trackear etapas de deals en V1. Solo
les importa marcar el outcome final (won/lost/cancelled).

**Justificación:** Eliminar las tablas descartaría la estructura para V2.
Mantenerlas con `stage` nullable preserva la base sin generar fricción
operativa.

**Activación en V2:** Cuando se active el pipeline visual, `Deal.stage` pasa a
non-nullable mediante una migración que asigna la etapa default a los deals
existentes.

---

### `Deal.listing` — nullable con `external_property_notes`

**Decisión:** `listing` es FK nullable. Check constraint garantiza que
`listing` o `external_property_notes` debe estar presente.

**Contexto:** Bricka puede cerrar deals sobre propiedades de otras
inmobiliarias donde no quieren registrar el listing completo.

**Contrato:**

- Deal sobre propiedad propia → `listing` presente, `external_property_notes`
  vacío.
- Deal sobre propiedad ajena → `listing` null, `external_property_notes` con
  descripción mínima.

**Constraint en DB:**

```sql
CHECK (listing_id IS NOT NULL OR external_property_notes > '')
```

---

### Mora — cálculo derivado, sin persistencia

**Decisión:** La mora no tiene tabla propia ni campo de estado. Se calcula como
valor derivado en `contracts/selectors.py`.

**Campos agregados a `RentalContract`:**

- `payment_due_day`: día del mes en que vence el pago (rango 1-28).
- `late_fee_percent_daily`: porcentaje diario acumulable (default 2%).

**Flujo:**

1. Celery evalúa mora una vez por día comparando fecha actual vs
   `payment_due_day`.
2. El selector calcula el monto (fórmula compuesta diaria).
3. La mora se materializa únicamente en `billing_documents.concept` cuando el
   socio emite el recibo.

**`payment_due_day` limitado a 1-28** por check constraint — días 29, 30 y 31
no existen en todos los meses.

---

### `Listing.property` — nombre de campo

**Decisión:** El campo FK se llama `property`, no `property_id`.

**Contexto:** El modelo original declaraba `property_id = models.ForeignKey(...)`.
Django agrega `_id` automáticamente a la columna de DB para cualquier FK,
resultando en una columna `property_id_id` — error de nomenclatura.

**Corrección aplicada:** `RenameField` via migración `0002`. La columna en DB
pasó de `property_id_id` a `property_id`.

---

## Choices compartidos

### `Currency` — y choices compartidos — en `common/choices.py`

**Decisión:** `Currency` vive en `apps/common/choices.py`, no en `listings/`.

**Justificación:** `Currency` es usado por `listings`, `contracts`, `billing` y
`contacts`. Importar desde `listings` en `contracts` crearía una dependencia
estructural entre apps que no deben conocerse entre sí.

`listings/choices.py` re-exporta `Currency` con `noqa: F401` para no romper
código existente.

**Regla generalizada:** cualquier choice usado por más de una app vive en
`common/choices.py`. Ejemplo: `SearchPreference.currency` importa desde
`common/choices.py`, no declara un `CharField` suelto.

---

## Capa de services y selectors

### Cross-app — selectors como punto de entrada

**Decisión:** Cuando un service de la app A necesita datos de la app B, importa
del `selectors.py` de B — nunca del `models.py` de B directamente.

**Ejemplo canónico:**

```python
# contacts/services.py — correcto
from apps.deals.selectors import get_open_deals_for_contact

# contacts/services.py — incorrecto
from apps.deals.models import Deal
```

**Caso especial — `audit/`:** ninguna app importa `AuditLog` directamente. Toda
consulta al audit log pasa por `audit/selectors.py`.

---

### Imports cross-app de type hints — `TYPE_CHECKING`

**Decisión:** Cuando un service o selector necesita el tipo de un modelo de otra
app *solo para anotaciones* (sin queries en runtime), el import vive dentro del
bloque `TYPE_CHECKING`.

```python
from __future__ import annotations  # obligatorio — ver abajo
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.contracts.models import RentalContract
    from apps.contacts.models import Contact
    from apps.deals.models import Deal
```

**`from __future__ import annotations` es obligatorio** en cualquier módulo que
use este patrón. Sin él, Python evalúa las anotaciones en runtime y
`"RentalContract" | None` lanza `TypeError`. Con la importación futura activada,
todas las anotaciones se vuelven strings lazy y nunca se evalúan en runtime.

**Motivo de la regla:** importar `models.py` de otra app en runtime viola la
convención "cross-app solo via selectors/services/choices". Un import de type
hint no genera queries, pero establece una dependencia de importación que puede
crear imports circulares y acopla la estructura interna de apps. `TYPE_CHECKING`
resuelve el dilema: el type checker ve el tipo, el runtime no ejecuta el import.

**`User` — caso especial:** se importa vía `get_user_model()` en runtime (no
bajo `TYPE_CHECKING`) porque Django lo requiere para resolver `AUTH_USER_MODEL`.

```python
from django.contrib.auth import get_user_model
User = get_user_model()
```

**Aplica actualmente en:** `billing/services.py` y `billing/selectors.py`.
Cualquier vertical nueva que necesite tipos de otra app sin queries reales debe
seguir este patrón.

---

### Selectors — manejo de "no encontrado"

**Decisión:** Los selectors lanzan `Model.DoesNotExist` cuando una entidad no
existe o está soft-deleted. Nunca usan `get_object_or_404`.

**Justificación:** `get_object_or_404` acopla el selector a la capa HTTP — un
selector llamado desde un Celery task o un management command no tiene contexto
de request. El caller decide cómo manejar la ausencia del objeto.

**Patrón en views:**

```python
try:
    contact = get_contact_detail(contact_id)
except Contact.DoesNotExist:
    raise Http404
```

**Patrón en services:** dejar que `DoesNotExist` se propague — es un error de
programación del caller, no un caso de negocio.

---

### Filtros de selectors — dataclass sobre kwargs

**Decisión:** Los selectors que aceptan filtros opcionales usan un dataclass
dedicado en lugar de kwargs individuales.

```python
@dataclass
class ContactFilters:
    role: str | None = None
    source: str | None = None
    assigned_agent_id: UUID | None = None

def get_contact_list(filters: ContactFilters | None = None) -> QuerySet:
    ...
```

**Justificación:** Las vistas de lista en un CRM acumulan filtros con el tiempo.
Con kwargs explícitos, cada filtro nuevo modifica la firma del selector y todos
sus callers. Con dataclass, la firma es estable.

**Aplicar en:** cualquier selector que acepte más de dos filtros opcionales, o
que tenga perspectiva de crecer.

---

### Firmas de services — kwargs explícitos con `*`

**Decisión:** Los services usan kwargs explícitos con `*` en lugar de
`data: dict`.

```python
# correcto
def create_contact(*, full_name: str, email: str = "", actor: User) -> Contact:

# incorrecto
def create_contact(data: dict, actor: User) -> Contact:
```

**Justificación:** El contrato es explícito — el IDE lo completa, un campo
faltante falla en la llamada (no adentro del service), y no hay acoplamiento
implícito con la estructura del form.

**Desempaquetado en views:**

```python
if form.is_valid():
    d = form.cleaned_data
    create_contact(full_name=d["full_name"], email=d["email"], actor=request.user)
```

---

### `update_fields` — `updated_at` siempre explícito

**Decisión:** Cualquier `save(update_fields=[...])` en el proyecto incluye
`"updated_at"` en la lista. Sin excepciones.

**Justificación verificada empíricamente:** con `auto_now=True`, Django
actualiza `updated_at` automáticamente solo si NO se usa `update_fields`. En
cuanto se usa `update_fields`, el control es del desarrollador — omitir
`updated_at` lo deja con el valor anterior silenciosamente.

```python
contact.save(update_fields=[
    "full_name", "email",
    "updated_by", "updated_at",  # ← siempre explícito
])
```

---

### Funciones de contexto en views — `_build_*_context`

**Decisión:** Cuando una view necesita construir un diccionario de presentación
con lógica no trivial (colorización por días, textos condicionales), esa lógica
vive en una función privada `_build_*_context` en el módulo de views, no en el
template ni en el selector.

```python
def _build_adjustment_context(contract, today):
    days = (contract.next_adjustment_date - today).days
    if days < 0:
        return {"style": "danger", "text": f"Vencido hace {abs(days)} días", ...}
    ...
```

**Motivo:** los templates no deben contener lógica de negocio. Los selectors
devuelven datos del modelo, no decisiones de UI. Las views son el lugar correcto
para resolver "qué mostrar y cómo".

---

## Excepciones

### Excepciones — organización por módulo

**Decisión:** Las excepciones de negocio viven en `<app>/exceptions.py`. Las
excepciones transversales del sistema viven en `common/exceptions.py`.

**Contrato:**

- `contacts/exceptions.py` → `ContactHasOpenDeals`
- `listings/exceptions.py` → excepciones propias de listings
- `common/exceptions.py` → `AuditViolationError` y cualquier excepción que cruce
  fronteras de app

**Justificación:** Una excepción definida en `services.py` no puede ser
importada por la view sin crear acoplamiento circular. Con módulos propios, tanto
`services.py` como `views.py` importan de `exceptions.py` sin dependencias
circulares.

---

### Excepciones enriquecidas — adjuntar instancia conflictiva

**Decisión:** Cuando una excepción de negocio puede adjuntar el objeto que causó
el error, hacerlo en el `__init__` evita queries adicionales en la view.

```python
class ContractDateConflict(ContractValidationError):
    def __init__(self, message="", conflicting_contract=None):
        self.conflicting_contract = conflicting_contract
        super().__init__(message)
```

El service hace `select_related` antes del raise para que la instancia llegue
hidratada. La view extrae `e.conflicting_contract` del except y lo pasa al
template.

**Aplica cuando:** la excepción tiene contexto útil para el usuario final (qué
contrato, qué propiedad, qué fecha) que sería costoso reconstruir en la view.

---

## Auditoría

### `audit_entity_type()` — classmethod en `AuditableMixin`

**Decisión:** `AuditableMixin` expone un classmethod que devuelve el
identificador canónico del modelo para el audit log.

```python
@classmethod
def audit_entity_type(cls) -> str:
    return cls.__name__
```

**Regla que no se negocia:** el string de `entity_type` nunca se hardcodea.
Siempre se llama `Model.audit_entity_type()`.

**Motivo:** si el modelo se renombra, tanto escritura (signals) como lectura
(selectors) se actualizan desde un único punto. Bugs de mismatch imposibles por
construcción.

---

### AppConfig.ready() — registro de signals

**Decisión:** Cada app que tenga `signals.py` debe importarlo explícitamente en
`AppConfig.ready()`.

**Motivo:** Django no importa `signals.py` automáticamente. Sin este import, los
`@receiver` nunca se registran y los signals no disparan — sin error, sin
advertencia.

```python
# apps/<app>/apps.py
class <App>Config(AppConfig):
    name = "apps.<app>"

    def ready(self):
        import apps.<app>.signals  # noqa: F401
```

**Apps que actualmente requieren esto:** `audit`. Actualizar esta lista cuando
otras apps agreguen signals.

---

## Billing

### `BillingDocument.number` — PostgreSQL sequences

**Decisión:** Numeración correlativa por `document_type` vía `nextval()` de
PostgreSQL. El número se asigna en el service, no en el modelo.

**Sequences creadas:**

- `billing_rent_receipt_seq`
- `billing_commission_receipt_seq`
- `billing_expense_receipt_seq`
- `billing_owner_statement_seq` (migración `0005`)

**⚠️ Trade-off aceptado:** Posibilidad de gaps en la numeración si una
transacción hace rollback después de consumir `nextval()`. Aceptable para
comprobantes internos en V1.

**⚠️ Incompatible con AFIP:** Los comprobantes fiscales oficiales requieren
numeración correlativa sin gaps. Cuando se active la integración fiscal, este
mecanismo debe reemplazarse. Revisar en ese momento.

---

### Moneda de `OWNER_STATEMENT` — deriva a ARS, deuda conocida

**Decisión actual:** En `create_billing_document`, la moneda se resuelve como
`contract.currency if contract is not None else currency`. Para
`OWNER_STATEMENT` el contrato se pasa como `None` (la rendición no se ancla a un
contrato único — los contratos liquidados van en los renglones), por lo que cae
al kwarg `currency`, cuyo default es `Currency.ARS`. La view de emisión no pasa
`currency` para rendiciones.

**Efecto:** una rendición sobre un contrato en USD queda sellada con
`currency = ARS`. El `total_amount` es numéricamente correcto, pero el campo
`currency` no refleja la denominación real del dinero.

**Por qué se acepta en V1:** Bricka opera (con muy alta probabilidad) todos sus
alquileres en ARS. El caso no aparece en la práctica actual.

**⚠️ Deuda conocida — multi-moneda:** El día que se emita una rendición sobre un
alquiler en USD, el comprobante saldrá mal denominado sin señal de error. Antes
de habilitar ese caso hay que decidir:

- **Pregunta de negocio abierta:** ¿Bricka opera, o va a operar, alquileres en
  USD?
- ¿Se prohíbe mezclar monedas dentro de una misma rendición?
- ¿De dónde deriva la `currency` del documento — del primer renglón, de un
  parámetro explícito, de un invariante "todos los contratos de la rendición
  comparten moneda"?

Revisar esta entrada antes de implementar rendiciones multi-contrato con
monedas heterogéneas.

---

## Documentos

### `documents/` — app propia

**Decisión:** La documentación legal vive en una app `documents/`
independiente, no dentro de `contacts/`, `properties/`, ni ninguna otra app de
dominio.

**Justificación:** `Document` tiene FKs hacia `contacts`, `properties`, `deals`
y `contracts`. Si el modelo viviera en cualquiera de esas apps, esa app
adquiriría dependencias hacia las otras tres — violación directa de la regla de
fronteras del sistema.

```python
class Document(SoftDeleteModel, AuditableMixin):
    contact  = models.ForeignKey("contacts.Contact",  null=True, blank=True, ...)
    property = models.ForeignKey("properties.Property", null=True, blank=True, ...)
    deal     = models.ForeignKey("deals.Deal",         null=True, blank=True, ...)
    contract = models.ForeignKey("contracts.RentalContract", null=True, blank=True, ...)
```

---

### `Document` — soft delete + invariante de múltiples padres

**Decisión:**

- `Document` hereda `SoftDeleteModel` + `AuditableMixin`.
- Hard delete disponible únicamente desde vista de papelera — siempre R2
  primero, DB después.
- INVARIANTE: al menos una FK padre presente — puede asociarse a múltiples
  entidades simultáneamente.
- El service valida el invariante — no hay constraint en DB.

**Justificación:** un documento legal puede pertenecer a múltiples entidades
(escritura asociada a propiedad + propietario). Forzar un único padre obliga a
duplicar archivos o perder contexto operativo. El invariante de N FKs nullable
no es garantizable con un check constraint limpio; el service es el único punto
de entrada.

---

### Hard delete en `Document` — R2 primero, DB después

**Decisión:** Los documentos subidos por error pueden eliminarse físicamente. El
orden de operaciones es siempre R2 primero.

**Justificación:** si R2 falla, el registro sigue en DB — estado inconsistente
pero detectable. Si DB falla después de R2, el archivo desaparece pero el
registro persiste apuntando a una key inexistente — también detectable. El
escenario inverso (DB primero, R2 después) genera storage leaks silenciosos e
imposibles de rastrear.

**⚠️ Trade-off aceptado:** el hard delete bypasea el audit log. Los documentos
eliminados no dejan registro de auditoría.

---

### Batch upload — `.save()` individual en `atomic()`

**Decisión:** N archivos se guardan con N llamadas a `.save()` dentro de
`transaction.atomic()`. Sin `bulk_create`.

**Motivo principal:** `bulk_create` está bloqueado por
`AuditedSoftDeleteQuerySet` — no es una elección, es la única opción disponible.

**Implicancias aceptadas:**

- N round trips a DB en lugar de 1 — imperceptible para batches de 2-10
  archivos.
- Cada archivo genera su propia entrada en `AuditLog` — deseable.
- Fallo a mitad del batch → rollback de todos los anteriores — correcto.

**V2:** si el upload se vuelve lento, la solución es Celery en background, no
paralelismo en el web process.

---

### `categorize_document` — fuente de verdad en `documents/utils.py`

**Decisión:** La función `categorize_document(content_type: str) -> str` vive en
`apps/documents/utils.py`. Es la única fuente autorizada.

**Contexto:** durante el desarrollo inicial existía una copia en
`apps/common/storage.py`. Esa copia fue eliminada en la auditoría de coherencia
— `common/storage.py` se ocupa de acceso a R2 y generación de URLs, no de lógica
de presentación de documentos.

```python
# correcto
from apps.documents.utils import categorize_document

# incorrecto — la función ya no existe ahí
from apps.common.storage import categorize_document
```

**Callers:** `apps/properties/views.py` importa desde `documents/utils`. Este
import cross-app es una función pura sin queries — no rompe la regla de
"cross-app via selectors" en su intención. Si en el futuro la view de properties
acumula más imports de `documents`, evaluar consolidar la lógica de presentación
en un selector o context dedicado.

---

## Formularios

### Formularios con FK — `UUIDField` en lugar de `ModelChoiceField`

**Decisión:** Para formularios donde los campos FK referencian modelos con
muchos registros, se usa `forms.UUIDField` en lugar de `ModelChoiceField`.

```python
class RentalContractForm(forms.Form):
    property_id = forms.UUIDField(...)
    tenant_contact_id = forms.UUIDField(...)
```

El combobox con búsqueda live llena un `<input type="hidden">` con el UUID. El
form valida que sea un UUID válido. El service recibe el UUID y resuelve la
instancia — la validación de existencia ocurre a nivel de FK constraint en DB,
no en el form.

**Por qué no `ModelChoiceField`:** un `<select>` con 500 contactos es inviable
en producción. El combobox requiere que el form acepte el UUID directamente.

---

## Infraestructura y URLs

### HTMX — `django-htmx` como librería de integración

**Decisión:** Se usa `django-htmx` para detectar requests de HTMX en lugar de
chequear el header manualmente.

**Setup:**

```python
INSTALLED_APPS = [..., "django_htmx"]
MIDDLEWARE = [..., "django_htmx.middleware.HtmxMiddleware"]
```

**Patrón en views:**

```python
if request.htmx:
    return render(request, "contacts/partials/contact_list_table.html", context)
return render(request, "contacts/contact_list.html", context)
```

**Respuesta para acciones exitosas:**

```python
response = HttpResponse(status=204)
response["HX-Redirect"] = reverse("contact-list")
return response
```

**Respuesta para errores de negocio:**

```python
return render(request, "partials/modal_error.html", {"error": str(e)})
```

El partial reemplaza el contenido del modal. El modal no se cierra — muestra el
error en contexto. Ver `docs/decisions/frontend.md` para la convención completa
de modales.

---

### Estructura de URLs — `backoffice_urls.py` centralizado

**Decisión:** Un archivo `apps/backoffice_urls.py` centraliza los includes de
todas las apps del backoffice.

**Jerarquía:**

```bash
config/urls.py          ← separa contextos (backoffice, webhooks, portal)
apps/backoffice_urls.py ← agrega apps del backoffice
apps/<app>/urls.py      ← rutas internas de la app
```

**`config/urls.py`:**

```python
urlpatterns = [
    path("backoffice/", include("apps.backoffice_urls")),
    path("webhooks/", include("apps.integrations.urls")),
    path("", include("apps.portal.urls")),
]
```

**Justificación:** un único lugar donde están todas las rutas del backoffice.
Middleware o decoradores que apliquen a todo el backoffice se configuran en un
solo punto.

---

### Setup híbrido Docker

**Decisión:** Solo `db` (PostgreSQL) y `redis` corren en Docker. Django, Celery
worker y Celery beat corren directamente en el venv local.

**Contexto:** Problema de DNS en Docker sobre Arch Linux / Omarchy que impide que
los contenedores accedan a internet durante el build. El Dockerfile se mantiene
en el repo para producción.

**Puerto 5433 para PostgreSQL:** Conflicto con instalación local de PostgreSQL
en el host que ocupa el 5432. El contenedor expone 5433 → 5432 internamente.

**`DATABASE_URL`:** `postgis://bricka:bricka@localhost:5433/bricka`

**Workflow:**

```bash
docker compose up          # Terminal 1 — db + redis
python manage.py runserver  # Terminal 2
celery -A config worker -l info  # Terminal 3
celery -A config beat -l info    # Terminal 4 (cuando haya tareas periódicas)
```

---

## Storage — Cloudflare R2

### R2 — dos buckets por modelo de seguridad opuesto

**Decisión:** dos buckets en Cloudflare R2, con modelos de acceso opuestos:

- **`bricka-media`** (público): fotos de propiedades, logo de agencia. Custom
  domain de Cloudflare, URL estable sin firma. Sin datos sensibles — son
  archivos que van a portales públicos de todas formas.
- **`bricka-documents`** (privado): documentos legales. Nunca público. Solo
  presigned URLs de corta vida (default 300s).

**Por qué no un único bucket:** el acceso público en R2 es a nivel de bucket
entero — conectar un custom domain expone todo el bucket. Media de marketing y
documentos legales tienen modelos de seguridad opuestos y no pueden convivir.

**Costo:** dos buckets no cuestan más que uno. R2 factura por bytes y
operaciones, sin egress fee.

**⚠️ Pendiente operativo antes de producción:** `R2_PUBLIC_MEDIA_BASE_URL`
apunta al dominio `r2.dev` en dev/sandbox (rate-limited, no apto para
producción). Antes de la primera publicación real en ZonaProp: registrar
dominio en Cloudflare, conectar custom domain al bucket público, cambiar la
env var. Cero cambios de código.

---

### boto3 directo — sin `django-storages` ni `FileField`

**Decisión:** usar boto3 directamente. No se usa `django-storages`.

**Motivo:** `django-storages` está pensado para un bucket por backend, atado
a `FileField`. Los modelos de Bricka gestionan `r2_key` como `CharField`
manualmente — no hay `FileField` en ningún modelo de dominio. boto3 directo
da control fino sobre dos buckets, presigned URLs y la separación
público/privado.

**Consecuencia:** `STORAGES["default"]` de Django queda como
`FileSystemStorage`, usado solo por staticfiles. Las variables `AWS_*` en
settings fueron eliminadas.

---

### Bucket derivado del modelo, no almacenado por fila

**Decisión:** el bucket al que pertenece un archivo se deduce del tipo de
modelo, no se persiste en una columna por fila.

- `PropertyMedia` → siempre `bricka-media` (público)
- `Document` → siempre `bricka-documents` (privado)

**Por qué no un campo `bucket` por fila:** sería un estado que puede
desincronizarse del modelo real. La elección de bucket está codificada en el
nombre de la función que llama el service (`upload_public_media` vs
`upload_private_document`) — es imposible que diverja.

---

### Paridad dev/prod en la ruta de código de R2

**Decisión:** `DEBUG` no activa ningún path alternativo para media de negocio.
R2 corre con código idéntico en dev y prod.

**Justificación:** mantener `common/storage.py` sin ejercitar en dev dejaría
la ruta de mayor riesgo (servicio externo) sin cobertura real. Un filesystem
local en dev enmascara errores de configuración, permisos y naming de keys
que solo aparecerían en producción.

**El aislamiento de datos lo da el `.env`:** dev apunta a `bricka-media-dev`
y `bricka-documents-dev`; prod a los buckets reales. Paridad de
comportamiento, no de datos.

---

### Keys con prefijo legible + UUID no enumerable

**Decisión:**

- Media:      `properties/{property_id}/{uuid4}.{ext}`
- Documentos: `documents/{document_id}/{uuid4}.{ext}`

**Prefijo:** para findability operativa en la consola de R2 — localizar todos
los archivos de una propiedad o documento sin query a la DB.

**Leaf con UUID propio:** hace la key no enumerable. El bucket privado de
documentos está protegido por firma + expiración, pero el UUID agrega defensa
en profundidad: conocer el `document_id` no es suficiente para adivinar la key.

---

### Funciones delete en storage — lanzan, no tragan

**Decisión:** las funciones `delete_*` de `common/storage.py` propagan
cualquier excepción de R2; nunca la capturan en silencio.

**Por qué:** habilita el orden "R2 primero, DB después" en los services de
borrado. Si R2 falla, la excepción se propaga y el service nunca llega a
tocar la DB. Sin esto, una falla silenciosa dejaría filas en DB apuntando a
objetos inexistentes en R2.

Ver también [Hard delete en `Document`](#hard-delete-en-document--r2-primero-db-después)
para la aplicación concreta de este principio en `documents/`.

---

### Asimetría de costo — URL pública vs presigned

**Decisión:** dos funciones con costos radicalmente distintos, usadas en
contextos distintos:

- `get_public_media_url(r2_key)` → concatenación de string. Costo cero.
  La llama el handler de portales una vez por foto al armar el payload de
  publicación.
- `generate_document_download_url(r2_key, expires_in=300)` → firma S3
  (operación de CPU + llamada a AWS Signature). Solo corre cuando un usuario
  abre un documento en el backoffice.

**La asimetría es intencional:** no usar presigned URLs para fotos públicas
(overhead innecesario + las URLs cambiarían con cada request) y no exponer
documentos privados con URLs estables.

---

### Token de API de portales — Redis, no DB

**Decisión:** el `access_token` de `client_credentials` de la API de Navent
(ZonaProp) se cachea en Redis con TTL = expiración del token menos un margen
de seguridad.

**Por qué Redis y no DB:** el token no necesita persistencia entre reinicios
del proceso — si expira o se pierde, se refresca con una nueva llamada de
autenticación. Redis ya está en el stack como broker de Celery. Crear una
tabla para un valor efímero sería overhead de modelado sin beneficio.

## Pendientes de diseño

### Propiedades externas (`is_external`) — presentación pendiente

**Estado:** Decisión de modelado cerrada. Tratamiento de presentación
pendiente.

Las propiedades de otras inmobiliarias (`is_external = True`) viven en el mismo
modelo que las propias. En templates y selectors del backoffice necesitan
tratamiento diferenciado:

- Presentación visual distinta.
- Filtros separados en listados.
- Claridad para los socios sobre qué es cartera propia y qué es colaboración.

**Invariante asociado:** si `is_external = True`, debe existir exactamente una
fila en `ExternalPropertySource` con `property = self.id`. Lo mantiene
`properties.services` — no hay constraint en DB.

**⚠️ Definir convención de presentación antes de implementar las vistas de
`properties`.**

### Logo de agencia — pendiente de modelo de configuración

**Estado:** cabo suelto de storage. No bloquea ninguna funcionalidad actual.

El logo de agencia vive en `bricka-media` con su `logo_r2_key`. La convención
de storage (dónde almacenar esa key, qué modelo la referencia) depende de un
modelo de configuración de agencia que aún no existe.

**Consecuencia:** por ahora, `logo_r2_key` no tiene FK padre definido.
Definir el modelo de configuración de agencia antes de implementar cualquier
UI que muestre o permita cambiar el logo.

## Coordinación de estado cruzado

### Módulo `operations` — dueño de los efectos cruzados sin dueño

**Decisión:** los efectos que cruzan agregados —`Property.status` →
`Listing.status` → `ListingPublication`— viven en un módulo de coordinación
propio, `apps/operations/services.py`, no en el evento de negocio que los
dispara (`close_deal`, services de contrato) ni en `properties.services`.

**Punto de anclaje:** hay varias puertas que cambian `Property.status`
(`close_deal`, los cuatro services de contrato, el parámetro `status` de
`update_property`, el seed). El único punto donde convergen es `Property.status`
mismo. La cascada se ancla ahí, en `transition_property_status(...)`, y toda
puerta —presente o futura— la hereda por pasar por el orquestador. Colgarla del
evento obligaría a duplicarla en cada puerta.

**Por qué módulo aparte y no `properties.services`:** es donde van a vivir
*todos* los efectos cruzados sin dueño: `property→listing` hoy, `deal→billing`
(comisión al ganar) y `listing→publication` (integración de canales) después. El
nombre dice qué hospeda y no tienta a incrustar la comisión dentro de
`close_deal`.

**Módulo plano, NO en `INSTALLED_APPS`.** `operations` no tiene modelos ni los
va a tener —es coordinación pura—, así que no es una app Django: es un paquete
importable. pytest lo descubre por path igual. Registrarlo sería inofensivo pero
innecesario.

**Reparto de responsabilidades:** la *política* de la cascada (qué estado de
Property mapea a qué acción sobre listings) vive en `operations`. La *lectura*
del set a reconciliar sale de `listings/selectors`. La *mutación* pasa por
`listings/services` (`update_listing_status`), nunca por un bulk `.update()` —
`AuditedQuerySet` lo bloquea a propósito, así que la reconciliación es un loop
de llamadas al service, no un write masivo. El write de `Property.status` se
delega en `properties.services.update_property_status`.

**Cascada asimétrica:** bajar (cerrar/pausar) es automático; subir (republicar
en un canal externo) es manual —consume un slot finito y una llamada de API—.
La landing propia, gratis, vuelve sola porque su visibilidad es
`Listing.status == PUBLISHED`.

**Capa externa pasiva en V1 — "avisar, no actuar".** Sin la API del canal, el
orquestador no baja publicaciones: solo hace *surface* (logging) de las que
quedaron vivas tras cerrar/pausar su listing, dejando registro de una baja
manual pendiente. Cuando entre la integración de canales, `_surface_external_
publications` es el punto único a reemplazar por la baja automática o por una
tarea visible en la UI.

**Atomicidad:** `transition_property_status` abre su propio `transaction.atomic()`.
Cuando el caller ya abrió una (close_deal, contratos), anida como savepoint; sin
caller previo (withdraw/restore/remandate), el atomic propio garantiza la
atomicidad.

**El alquiler no se cierra en SOLD — se pausa.** "Vendido = fuera del mercado de alquiler" es una regla de negocio que la función no puede conocer: solo el agente sabe si el comprador es un inversor que sigue el mandato de alquiler. Cerrar el listing de alquiler automáticamente sería automatización de más. SOLD lo pausa (fuera de la landing, retiene el slot) y deja la decisión —reactivar o cerrar— como paso humano explícito. Esto resuelve el gap #7 con matiz: close_deal cierra la venta dentro de la transacción, pero el alquiler queda parkeado para el agente.
El cierre del listing de venta NO es efecto de la transición: es efecto deal→listing (settle_won_sale).

**La ocupación (RENTED) tiene precedencia sobre el evento de venta.** close_deal WON+SALE → settle_won_sale: cierra el listing de venta siempre; transiciona a SOLD solo si la propiedad estaba AVAILABLE. Una unidad alquilada que se vende sigue RENTED — el estado durativo no se pisa; el 'está vendida' se responde por el deal ganado + owner nuevo. Consecuencia: SOLD queda solo para vendidas-y-vacías, lo que hace limpio el guard de salida de SOLD.

**Guard de SOLD (implementado).** `transition_property_status` rechaza toda transición saliente de una propiedad SOLD con InvalidPropertyTransition. La única salida sancionada es remandate_property, que entra por el motor interno `_apply_property_transition` (sin guard). Patrón: función pública guardada / motor sin guard / la salida legítima entra por el motor. Como con precedencia SOLD queda solo para vendidas-y-vacías, el guard no tiene falsos positivos: no hay caminos incidentales legítimos que salgan de SOLD.

### Enmienda (jul 2026): condición extendida a estados no-cerrados

La condición original (`status IN (published, paused)`) resultó corta:
protegía la superficie visible pero permitía duplicados en draft y
pending_approval — el estado inválido era construible por doble-click,
concurrencia, POST directo o cualquier caller no-UI. La verificación
pre-migración lo confirmó empíricamente: la DB de dev contenía dos
drafts SALE duplicados creados durante pruebas manuales pre-S3b.

Condición nueva: `NOT closed AND deleted_at IS NULL`. Se escribe por
EXCLUSIÓN y no por lista, a propósito: un estado futuro agregado al enum
queda DENTRO de la constraint por defecto (sobre-bloqueo visible) en vez
de fuera (leak silencioso). `closed` es el único estado que libera el
slot; el soft-delete (`archive_listing`) es la otra vía de liberación.

El invariante queda en tres capas con funciones distintas:

1. Constraint parcial (DB) — la garantía; ningún caller la saltea.
2. Chequeo en create_listing — la experiencia; error temprano y legible
   que nombra el estado bloqueante.
3. Catch de IntegrityError (helper común violates_constraint) — el
   puente; traduce la carrera que el chequeo no ve al error de negocio.

Consecuencia: la unicidad-en-publish de update_listing_status pasó a
rama DEFENSIVA (inalcanzable por construcción) — log CRITICAL + error
genérico. Si se dispara, la constraint fue vulnerada.

### Guards de operaciones destructivas sobre buckets (S4)

**Contexto.** `cleanup_r2_orphans` (S4) es la primera operación del
codebase que elimina objetos de un bucket R2 en lote. El vector de
desastre no es un bug del diff sino un `.env` equivocado: un `--reset`
corrido con credenciales/bucket de producción configurados.

**Decisión.** Toda operación destructiva sobre un bucket exige DOS guards
independientes, verificados por la propia operación (no por el caller):
(1) `settings.DEBUG` activo; (2) el nombre del bucket con sufijo `-dev`.
Si cualquiera falla → `CommandError`: no corre y dice cuál falló. El
sufijo es contrato de nombres de infraestructura: los buckets de
desarrollo SIEMPRE terminan en `-dev`; producción nunca.

**Best-effort desde flujos compuestos.** Cuando la operación destructiva
es un paso final de un flujo mayor ya commiteado (el reset del seed), el
caller la trata como best-effort: captura CommandError (guard: hizo su
trabajo) y Exception (I/O) como warning, sin abortar el flujo. Corriendo
suelta, frena en seco.

**Consecuencias.** El comando es inservible en producción a propósito;
una futura limpieza productiva es OTRA decisión con OTROS guards (obs.#7 general). Los guards se testean como comportamiento: guard fallido → cero llamadas de borrado al cliente de storage.
