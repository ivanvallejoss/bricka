# Decisiones de Diseño — Bricka CRM

Convenciones técnicas y registro de decisiones del backend.

Este documento tiene dos partes con ciclos de vida distintos:

- **Parte 1 — Convenciones activas.** Las reglas que se siguen al escribir
  código, agrupadas por dominio. Enunciado terso + enlace al registro
  completo. Es la sección de consulta diaria.
- **Parte 2 — Registro de decisiones.** El contexto, la justificación y el
  trade-off de cada decisión. Formato ADR, append-only. Se lee una vez para
  entender el *por qué*; rara vez después.

Cuando una convención y su decisión coexisten, el enunciado vive en la
Parte 1 y el rationale completo en la Parte 2. No se duplica.

> El día que este archivo se parta en dos, el corte es exactamente la línea
> entre Parte 1 (`conventions.md`) y Parte 2 (`decisions.md`).

---

# Parte 1 — Convenciones activas

## Modelos base y herencia

- **`BaseModel`** es la raíz de todos los modelos del sistema (directo o vía
  `SoftDeleteModel`). Aporta UUID PK, timestamps y `created_by`/`updated_by`.
  → [ADR](#basemodel--raíz-de-modelos-de-dominio)
- **`SoftDeleteModel`** extiende `BaseModel` con `deleted_at`, doble manager
  (`objects` filtrado / `all_objects` sin filtro) y enforcement de audit.
  → [ADR](#softdeletemodel--soft-delete--enforcement-de-audit)
- **`TimestampModel`** es la base mínima (UUID + timestamps, sin trazabilidad
  de usuario) para tablas append-only o de reemplazo: `PropertyMedia`,
  `ListingPriceHistory`, `DealStageHistory`, `RentAdjustment`.
  → [ADR](#timestampmodel--base-para-tablas-auxiliares)
- **`AuditableMixin`** aporta enforcement de audit a modelos que NO heredan
  `SoftDeleteModel` (ej: `BillingDocument`). → [ADR](#auditablemixin--enforcement-para-modelos-sin-soft-delete)
- **`User` no hereda `BaseModel`** — hereda `AbstractUser` y declara UUID PK
  y `deleted_at` manualmente. → [ADR](#user--no-hereda-basemodel)

## Identidad y trazabilidad

- **PKs: UUIDv4** (`UUIDField(primary_key=True, default=uuid.uuid4)`) en todos
  los modelos. No se usa ULID. → [ADR](#pks--uuid-sobre-ulid)
- **No existe `tenant_id`** en ninguna tabla. → [ADR](#tenant_id--eliminado)
- **`created_by` / `updated_by`: FK nullable, `SET_NULL`, `related_name="+"`.**
  `null` significa "acción ejecutada por el sistema" (tareas Celery sin
  request). No hay un "system user". → [ADR](#created_by--updated_by--null--sistema)
- **`AuditLog.actor_id` es `UUIDField` sin FK** — snapshot histórico, no
  referencia viva. → [ADR](#auditlogactor_id--uuid-sin-fk)
- **Excepción a `SET_NULL`: `RentAdjustment.applied_by`** es no nullable con
  `PROTECT` — certifica quién aprobó el ajuste. → [ADR](#rentadjustmentapplied_by--excepción-a-la-convención)

## Modelado de dominio

- **`ContactRole`: campo único (`CharField`) en V1.** Un contacto tiene un
  solo rol simultáneo. → [ADR](#contactrole--campo-único-en-v1)
- **`assigned_agent` en `Contact`: semántica flexible.** Editable
  post-creación; la inmobiliaria define su uso. → [ADR](#assigned_agent--semántica-flexible)
- **`PipelineStage` y `DealStageHistory`: tablas presentes, inactivas en V1.**
  `Deal.stage` es nullable; el pipeline visual se difiere a V2.
  → [ADR](#pipelinestage-y-dealstagehistory--inactivos-en-v1)
- **`Deal.listing` nullable + `external_property_notes`.** Check constraint
  garantiza presencia de uno u otro. → [ADR](#deallisting--nullable-con-external_property_notes)
- **Mora: cálculo derivado, sin persistencia.** Se computa en
  `contracts/selectors.py`; se materializa solo en `billing_documents.concept`
  al emitir. → [ADR](#mora--cálculo-derivado-sin-persistencia)
- **`Listing.property`** — el campo FK se llama `property`, no `property_id`
  (Django agrega `_id` solo). → [ADR](#listingproperty--nombre-de-campo)

## Choices compartidos

- **Todo choice usado por más de una app vive en `common/choices.py`.**
  `Currency` es el caso canónico (usado por listings, contracts, billing,
  contacts). → [ADR](#currency--y-choices-compartidos--en-commonchoicespy)

## Capa de services y selectors

- **Cross-app via selectors.** Un service de la app A que necesita datos de B
  importa del `selectors.py` de B, nunca del `models.py`.
  → [ADR](#cross-app--selectors-como-punto-de-entrada)
- **Imports de type hints cross-app van bajo `TYPE_CHECKING`** (con
  `from __future__ import annotations`). `User` es la excepción: se importa
  vía `get_user_model()` en runtime. → [ADR](#imports-cross-app-de-type-hints--type_checking)
- **Selectors lanzan `Model.DoesNotExist`**, nunca `get_object_or_404`. El
  caller decide cómo manejar la ausencia. → [ADR](#selectors--manejo-de-no-encontrado)
- **Selectors con más de dos filtros opcionales usan un `dataclass`**, no
  kwargs individuales. → [ADR](#filtros-de-selectors--dataclass-sobre-kwargs)
- **Services usan kwargs explícitos con `*`**, no `data: dict`.
  → [ADR](#firmas-de-services--kwargs-explícitos-con-)
- **Todo `save(update_fields=[...])` incluye `"updated_at"`.** Sin excepción.
  → [ADR](#update_fields--updated_at-siempre-explícito)
- **Funciones puras de presentación viven en `_build_*_context` en views**,
  no en templates ni selectors. → [ADR](#funciones-de-contexto-en-views--_build__context)

## Excepciones

- **Excepciones de negocio en `<app>/exceptions.py`**; transversales en
  `common/exceptions.py`. → [ADR](#excepciones--organización-por-módulo)
- **Excepciones enriquecidas: adjuntar la instancia conflictiva en
  `__init__`** para evitar queries extra en la view.
  → [ADR](#excepciones-enriquecidas--adjuntar-instancia-conflictiva)

## Auditoría

- **`entity_type` nunca se hardcodea** — siempre `Model.audit_entity_type()`.
  → [ADR](#audit_entity_type--classmethod-en-auditablemixin)
- **Ninguna app importa `AuditLog` directamente** — todo pasa por
  `audit/selectors.py`. → [ADR](#cross-app--selectors-como-punto-de-entrada)
- **`.update()` y `.delete()` en queryset de modelos auditados lanzan
  `AuditViolationError`.** Usar `instance.soft_delete()` o el service.
  → [ADR](#softdeletemodel--soft-delete--enforcement-de-audit)
- **Apps con `signals.py` deben importarlo en `AppConfig.ready()`.** Hoy
  aplica a `audit`. → [ADR](#appconfigready--registro-de-signals)

## Billing

- **`BillingDocument.number`: PostgreSQL sequences por `document_type`.**
  Número asignado en el service, lo más tarde posible.
  → [ADR](#billingdocumentnumber--postgresql-sequences)
- **Moneda de `OWNER_STATEMENT` deriva a ARS por defecto** — deuda conocida
  para multi-moneda. → [ADR](#moneda-de-owner_statement--deriva-a-ars-deuda-conocida)

## Documentos

- **`documents/` es app propia** — `Document` tiene FK a contacts, properties,
  deals y contracts; no puede vivir en ninguna de ellas.
  → [ADR](#documents--app-propia)
- **Invariante de `Document`: al menos una FK padre presente.** Garantizado
  por el service, no por constraint. → [ADR](#document--soft-delete--invariante-de-múltiples-padres)
- **Hard delete de `Document`: R2 primero, DB después.**
  → [ADR](#hard-delete-en-document--r2-primero-db-después)
- **Batch upload: `.save()` individual dentro de `atomic()`**, sin
  `bulk_create` (bloqueado por el queryset auditado).
  → [ADR](#batch-upload--save-individual-en-atomic)
- **`categorize_document` vive solo en `documents/utils.py`.** Fuente única.
  → [ADR](#categorize_document--fuente-de-verdad-en-documentsutilspy)

## Formularios

- **Formularios con FK de alto volumen usan `forms.UUIDField`**, no
  `ModelChoiceField`. El combobox llena un hidden con el UUID.
  → [ADR](#formularios-con-fk--uuidfield-en-lugar-de-modelchoicefield)

## Infraestructura y URLs

- **HTMX vía `django-htmx`** (`request.htmx`), no chequeo manual de headers.
  → [ADR](#htmx--django-htmx-como-librería-de-integración)
- **URLs del backoffice centralizadas en `apps/backoffice_urls.py`.**
  → [ADR](#estructura-de-urls--backoffice_urlspy-centralizado)
- **Setup local híbrido:** solo `db` y `redis` en Docker; Django/Celery en
  venv local. PostgreSQL en puerto 5433. → [ADR](#setup-híbrido-docker)

## Pendientes de diseño

Decisiones de modelado cerradas cuya capa de presentación o flujo aún no está
definida. No son convenciones activas — son recordatorios de qué acordar antes
de implementar.

- **`is_external` — tratamiento visual.** Las propiedades de otras
  inmobiliarias necesitan presentación, filtros y claridad diferenciados.
  Definir convención antes de las vistas de properties.
  → [ADR](#propiedades-externas-is_external--presentación-pendiente)

---

# Parte 2 — Registro de decisiones (ADR)

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
