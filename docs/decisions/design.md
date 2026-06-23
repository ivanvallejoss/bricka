# Decisiones de Diseño — Bricka CRM

Registro de decisiones técnicas tomadas durante el diseño e implementación.
Cada entrada incluye el contexto, la decisión, y el trade-off aceptado.

---

## PKs — UUID sobre ULID

**Decisión:** `UUIDField(primary_key=True, default=uuid.uuid4, editable=False)` en todos los modelos.

**Contexto:** El documento original mencionaba ULIDs en la sección de requerimientos
no funcionales pero UUID en la sección de decisiones transversales. Contradicción
resuelta a favor de UUID.

**Justificación:** Bricka es una inmobiliaria mediana. El volumen de datos no va
a rozar los límites de UUIDv4. La complejidad adicional de ULIDs (librería externa,
ordering temporal) no tiene retorno visible en este contexto.

---

## `tenant_id` — eliminado

**Decisión:** `tenant_id` no existe en ninguna tabla.

**Contexto:** El documento original incluía `tenant_id` como preparación para
multi-tenancy futuro. Eliminado tras re-consultas con Bricka.

**Justificación:** Bricka no tiene perspectiva de expansión multi-tenant en el
corto plazo. Una columna con un único valor constante en todas las tablas es
infraestructura en desuso que agrega ruido sin retorno. Si en el futuro se
requiere multi-tenancy, la migración se diseña en ese momento con un caso
de uso real.

---

## `created_by` / `updated_by` — FK nullable, null = sistema

**Decisión:** FK a `users.User` con `null=True` y `on_delete=SET_NULL`.

**Convención:** `null` es semánticamente equivalente a "acción ejecutada por
el sistema" — específicamente tareas Celery que operan sin contexto de request.
No existe un "system user" especial.

**Implicancias:**

- Cualquier código que lea estos campos debe tratar `null` como origen del sistema, no como dato faltante.
- `related_name="+"` desactiva el related manager inverso en todos los casos.
- `SET_NULL` como `on_delete`: si un usuario se elimina físicamente (que con
  soft delete no debería ocurrir), el campo queda null en lugar de romper
  registros existentes.

**Excepción documentada:** `RentAdjustment.applied_by` es no nullable con
`PROTECT` — ver sección correspondiente.

---

## `ContactRole` — campo único en V1

**Decisión:** `role = CharField(choices=ContactRole.choices, blank=True)`
en lugar de JSONB array o booleanos por rol.

**Contexto:** El documento original usaba JSONB array para soportar múltiples
roles simultáneos por contacto.

**Justificación:** En V1 cada contacto tiene un solo rol simultáneo. JSONB
agrega complejidad de querying sin retorno. Booleanos múltiples son
sobreingeniería para un caso que no existe todavía.

**⚠️ Deuda documentada:** Si en el futuro un contacto puede ser propietario
e inquilino al mismo tiempo, este campo requiere migración a booleanos
o tabla de relación. Revisar antes de implementar esa funcionalidad.

---

## `PipelineStage` y `DealStageHistory` — presentes pero inactivos en V1

**Decisión:** Las tablas existen y tienen migraciones aplicadas.
`Deal.stage` es nullable — ningún flujo de V1 requiere interacción
con estas tablas.

**Contexto:** Bricka no está interesada en trackear etapas de deals en V1.
Solo les importa marcar el outcome final (won/lost/cancelled).

**Justificación:** Eliminar las tablas completamente descartaría la estructura
para V2. Mantenerlas con `stage` nullable en `Deal` preserva la base sin
generar fricción operativa.

**Activación en V2:** Cuando se active el pipeline visual, `Deal.stage`
pasa a non-nullable mediante una migración que asigna la etapa default
a los deals existentes.

---

## `Deal.listing_id` — nullable con `external_property_notes`

**Decisión:** `listing` es FK nullable. Check constraint garantiza que
`listing` o `external_property_notes` debe estar presente.

**Contexto:** Bricka puede cerrar deals sobre propiedades de otras
inmobiliarias donde no quieren registrar el listing completo.

**Contrato:**

- Deal sobre propiedad propia → `listing` presente, `external_property_notes` vacío
- Deal sobre propiedad ajena → `listing` null, `external_property_notes` con
  descripción mínima

**Constraint en DB:**

```sql
CHECK (listing_id IS NOT NULL OR external_property_notes > '')
```

---

## Mora en contratos de alquiler — cálculo derivado, sin persistencia

**Decisión:** La mora no tiene tabla propia ni campo de estado.
Se calcula como valor derivado en `contracts/selectors.py`.

**Campos agregados a `RentalContract`:**

- `payment_due_day`: día del mes en que vence el pago (rango 1-28)
- `late_fee_percent_daily`: porcentaje diario acumulable (default 2%)

**Flujo:**

1. Celery evalúa mora una vez por día comparando fecha actual vs `payment_due_day`
2. El selector calcula el monto: `current_price × (late_fee_percent_daily × días_atraso)`
3. La mora se materializa únicamente en `billing_documents.concept`
   cuando el socio emite el recibo

**`payment_due_day` limitado a 1-28** por check constraint — días 29, 30 y 31
no existen en todos los meses.

---

## `BillingDocument.number` — PostgreSQL sequences

**Decisión:** Numeración correlativa por `document_type` via `nextval()`
de PostgreSQL. El número se asigna en el service, no en el modelo.

**Sequences creadas:**

- `billing_rent_receipt_seq`
- `billing_commission_receipt_seq`
- `billing_expense_receipt_seq`

**⚠️ Trade-off aceptado:** Posibilidad de gaps en la numeración si una
transacción hace rollback después de consumir `nextval()`. Aceptable
para comprobantes internos en V1.

**⚠️ Incompatible con AFIP:** Los comprobantes fiscales oficiales requieren
numeración correlativa sin gaps. Cuando se active la integración fiscal,
este mecanismo debe reemplazarse. Revisar en ese momento.

---

## `RentAdjustment.applied_by` — excepción a la convención general

**Decisión:** `applied_by` es FK no nullable con `on_delete=PROTECT`.

**Contexto:** Excepción explícita a la convención general de `SET_NULL` + nullable.

**Justificación:** `applied_by` no es trazabilidad administrativa — es una
certificación. El registro dice "este ajuste fue aprobado por esta persona".
Si `applied_by` se pierde, el registro pierde su valor auditivo completo.

- **No nullable:** no existe un ajuste aprobado sin un aprobador
- **PROTECT:** si alguien intenta borrar físicamente al usuario que aprobó
  ajustes, la DB lo frena. Con soft delete esto nunca se activa en la práctica.

---

## `AuditLog.actor_id` — UUID sin FK

**Decisión:** `actor_id = UUIDField(null=True)` sin FK a `users.User`.

**Justificación:**

- FK + SET_NULL perdería la identidad del actor ante un borrado físico de usuario
- FK + PROTECT impediría borrar usuarios con historial de auditoría
- UUID preserva la identidad permanentemente sin restricciones

`null` en `actor_id` indica acción ejecutada por Celery — misma convención
que `created_by`/`updated_by`.

---

## `Currency` — movido a `common/choices.py`

**Decisión:** `Currency` vive en `apps/common/choices.py`, no en `listings/`.

**Justificación:** `Currency` es usado por `listings`, `contracts`, `billing`
y `contacts`. Importar desde `listings` en `contracts` crearía una dependencia
estructural entre apps que no deben conocerse entre sí.

`listings/choices.py` re-exporta `Currency` con `noqa: F401` para no romper
código existente.

**Extensión de la regla:** cualquier choice usado por más de una app vive
en `common/choices.py`. Ejemplo identificado en Fase 2: `SearchPreference.currency`
debe importar desde `common/choices.py`, no declarar un `CharField` suelto.

---

## `User` — no hereda `BaseModel`

**Decisión:** `User` hereda `AbstractUser`. UUID PK y `deleted_at` se
declaran manualmente.

**Justificación:** `AbstractUser` ya define su propio PK entero. `BaseModel`
también define UUID PK. Django no puede resolver dos PKs en la misma jerarquía.

**Campos omitidos respecto a `BaseModel`:**

- `created_by` / `updated_by` — trazabilidad administrativa innecesaria para
  el caso de uso de Bricka en V1
- `updated_at` — `AbstractUser` no lo tiene; `soft_delete()` usa
  `update_fields=["deleted_at", "is_active"]` explícitamente

**Soft delete en `User` coordina dos mecanismos:**

- `deleted_at`: excluye del manager default
- `is_active = False`: bloquea autenticación via auth backend de Django

---

## Setup híbrido Docker — infraestructura en contenedor, Django local

**Decisión:** Solo `db` (PostgreSQL) y `redis` corren en Docker.
Django, Celery worker y Celery beat corren directamente en el venv local.

**Contexto:** Problema de DNS en Docker sobre Arch Linux / Omarchy que
impide que los contenedores accedan a internet durante el build. El
Dockerfile se mantiene en el repo para producción.

**Puerto 5433 para PostgreSQL:** Conflicto con instalación local de
PostgreSQL en el host que ocupa el puerto 5432. El contenedor expone
5433 → 5432 internamente.

**`DATABASE_URL`:** `postgis://bricka:bricka@localhost:5433/bricka`

**Workflow:**

```bash
# Terminal 1
docker compose up          # db + redis

# Terminal 2
python manage.py runserver

# Terminal 3
celery -A config worker -l info

# Terminal 4 (cuando haya tareas periódicas)
celery -A config beat -l info
```

---

## Propiedades externas (`is_external`) — tratamiento visual pendiente

**Estado:** Decisión de modelado cerrada. Tratamiento de presentación pendiente.

Las propiedades de otras inmobiliarias (`is_external = True`) viven en el
mismo modelo que las propias. En templates y selectors del backoffice
necesitan tratamiento diferenciado:

- Presentación visual distinta
- Filtros separados en listados
- Claridad para los socios sobre qué es cartera propia y qué es colaboración

**⚠️ Definir convención de presentación antes de implementar las vistas
de `properties`.**

---

## Excepciones — organización por módulo

**Decisión:** Las excepciones de negocio viven en `<app>/exceptions.py`.
Las excepciones transversales del sistema viven en `common/exceptions.py`.

**Contrato:**

- `contacts/exceptions.py` → `ContactHasOpenDeals`
- `listings/exceptions.py` → excepciones propias de listings
- `common/exceptions.py` → `AuditViolationError` y cualquier excepción
  que cruce fronteras de app

**Justificación:** Una excepción definida en `services.py` no puede ser
importada por la view sin crear acoplamiento circular. Con módulos
propios, tanto `services.py` como `views.py` importan de `exceptions.py`
sin dependencias circulares.

---

## `assigned_agent` en `Contact` — semántica flexible

**Decisión:** `assigned_agent` es editable post-creación. La semántica
es deliberadamente flexible: puede indicar quién originó el contacto
o quién lo está trabajando actualmente.

**Contexto:** Bricka opera con pocos agentes donde cualquiera puede
trabajar con cualquier contacto. La inmobiliaria define su propio uso
con la práctica.

**⚠️ Revisar en V2** si aparece necesidad de separar ambos conceptos
en campos distintos (`sourced_by` vs `assigned_to`).

---

## Dependencias cross-app — selectors como punto de entrada

**Decisión:** Cuando un service de app A necesita datos de app B,
importa del `selectors.py` de B — nunca del `models.py` de B directamente.

**Ejemplo canónico:**

```python
# contacts/services.py — correcto
from apps.deals.selectors import get_open_deals_for_contact

# contacts/services.py — incorrecto
from apps.deals.models import Deal
```

**Caso especial — `audit/`:** ninguna app importa `AuditLog` directamente.
Toda consulta al audit log pasa por `audit/selectors.py`.

---

## `audit_entity_type()` — classmethod en `AuditableMixin`

**Decisión:** `AuditableMixin` expone un classmethod que devuelve el
identificador canónico del modelo para el audit log.

```python
@classmethod
def audit_entity_type(cls) -> str:
    return cls.__name__
```

**Regla que no se negocia:** el string de `entity_type` nunca se
hardcodea. Siempre se llama `Model.audit_entity_type()`.

**Motivo:** si el modelo se renombra, tanto escritura (signals) como
lectura (selectors) se actualizan desde un único punto. Bugs de
mismatch imposibles por construcción.

---

## AppConfig.ready() — registro de signals

**Decisión:** Cada app que tenga `signals.py` debe importarlo
explícitamente en `AppConfig.ready()`.

**Motivo:** Django no importa `signals.py` automáticamente. Sin este
import, los `@receiver` nunca se registran y los signals no disparan
— sin error, sin advertencia.

**Patrón obligatorio para cualquier app con signals:**

```python
# apps/<app>/apps.py
from django.apps import AppConfig

class <App>Config(AppConfig):
    name = "apps.<app>"

    def ready(self):
        import apps.<app>.signals  # noqa: F401
```

**Apps que actualmente requieren esto:** `audit`.
Actualizar esta lista cuando otras apps agreguen signals.

---

## Selectors — manejo de "no encontrado"

**Decisión:** Los selectors lanzan `Model.DoesNotExist` cuando una
entidad no existe o está soft-deleted. Nunca usan `get_object_or_404`.

**Justificación:** `get_object_or_404` acopla el selector a la capa
HTTP — un selector llamado desde un Celery task o un management
command no tiene contexto de request. El caller decide cómo manejar
la ausencia del objeto.

**Patrón en views:**

```python
try:
    contact = get_contact_detail(contact_id)
except Contact.DoesNotExist:
    raise Http404
```

**Patrón en services:** dejar que `DoesNotExist` se propague —
es un error de programación del caller, no un caso de negocio.

---

## Filtros de selectors — dataclass sobre kwargs explícitos

**Decisión:** Los selectors que aceptan filtros opcionales usan un
dataclass dedicado en lugar de kwargs individuales.

**Patrón:**

```python
@dataclass
class ContactFilters:
    role: str | None = None
    source: str | None = None
    assigned_agent_id: UUID | None = None

def get_contact_list(filters: ContactFilters | None = None) -> QuerySet:
    ...
```

**Justificación:** Las vistas de lista en un CRM acumulan filtros con
el tiempo. Con kwargs explícitos, cada filtro nuevo modifica la firma
del selector y todos sus callers. Con dataclass, la firma es estable
— se agrega el campo al dataclass y el selector lo aplica.

**Aplicar en:** cualquier selector que acepte más de dos filtros
opcionales, o que tenga perspectiva de crecer.

---

## `update_fields` — `updated_at` siempre explícito

**Decisión:** Cualquier `save(update_fields=[...])` en el proyecto
incluye `"updated_at"` en la lista. Sin excepciones.

**Justificación verificada empíricamente:** con `auto_now=True`, Django
actualiza `updated_at` automáticamente solo si NO se usa `update_fields`.
En cuanto se usa `update_fields`, el control es completamente del
desarrollador — omitir `updated_at` lo deja con el valor anterior
silenciosamente.

```python
contact.save(update_fields=[
    "full_name", "email",
    "updated_by", "updated_at",  # ← siempre explícito
])
```

---

## Firmas de services — kwargs explícitos con `*`

**Decisión:** Los services usan kwargs explícitos con `*` en lugar
de `data: dict`.

```python
# correcto
def create_contact(*, full_name: str, email: str = "", actor: User) -> Contact:

# incorrecto
def create_contact(data: dict, actor: User) -> Contact:
```

**Justificación:** El contrato es explícito — el IDE lo completa, un
campo faltante falla en la llamada (no adentro del service), y no hay
acoplamiento implícito con la estructura del form.

**Desempaquetado en views:**

```python
if form.is_valid():
    d = form.cleaned_data
    create_contact(
        full_name=d["full_name"],
        email=d["email"],
        actor=request.user,
    )
```

---

## `documents/` — app propia

**Decisión:** La documentación legal vive en una app `documents/`
independiente, no dentro de `contacts/`, `properties/`, ni ninguna
otra app de dominio.

**Justificación:** `Document` tiene FKs hacia `contacts`, `properties`,
`deals` y `contracts`. Si el modelo viviera en cualquiera de esas apps,
esa app adquiriría dependencias hacia las otras tres — violación directa
de la regla de fronteras del sistema.

**Modelo:**

```python
class Document(SoftDeleteModel, AuditableMixin):
    contact  = models.ForeignKey("contacts.Contact",  null=True, blank=True, ...)
    property = models.ForeignKey("properties.Property", null=True, blank=True, ...)
    deal     = models.ForeignKey("deals.Deal",         null=True, blank=True, ...)
    contract = models.ForeignKey("contracts.RentalContract", null=True, blank=True, ...)

    original_filename = models.CharField(max_length=255)
    r2_key            = models.CharField(max_length=500, unique=True)
    content_type      = models.CharField(max_length=100)
    file_size         = models.PositiveIntegerField()
    description       = models.CharField(max_length=300, blank=True)
```

**Invariante:** exactamente un FK padre presente. No garantizable
con check constraint limpio para N FKs nullable. El service es el
único punto de entrada — garantiza el invariante.

---

## Hard delete en `Document` — R2 primero, DB después

**Decisión:** Los documentos subidos por error pueden eliminarse
físicamente. El orden de operaciones es siempre R2 primero.

**Justificación:** si R2 falla, el registro sigue en DB — estado
inconsistente pero detectable. Si DB falla después de R2, el archivo
desaparece pero el registro persiste apuntando a una key inexistente
— también detectable. El escenario inverso (DB primero, R2 después)
genera storage leaks silenciosos e imposibles de rastrear.

**⚠️ Trade-off aceptado:** el hard delete bypasea el audit log.
Los documentos eliminados no dejan registro de auditoría.

---

## Batch upload de documentos — `.save()` individual en `atomic()`

**Decisión:** N archivos se guardan con N llamadas a `.save()` dentro
de `transaction.atomic()`. Sin `bulk_create`.

**Motivo principal:** `bulk_create` está bloqueado por `AuditedSoftDeleteQuerySet`
— no es una elección, es la única opción disponible.

**Implicancias aceptadas:**

- N round trips a DB en lugar de 1 — imperceptible para batches de 2-10 archivos
- Cada archivo genera su propia entrada en `AuditLog` — deseable
- Fallo a mitad del batch → rollback de todos los anteriores — correcto

**V2:** si el upload se vuelve lento, la solución es Celery en background,
no paralelismo en el web process.

---

## HTMX — `django-htmx` como librería de integración

**Decisión:** Se usa `django-htmx` para detectar requests de HTMX
en lugar de chequear el header manualmente.

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

**Convención de respuesta para acciones exitosas:**

```python
response = HttpResponse(status=204)
response["HX-Redirect"] = reverse("contact-list")
return response
```

**Convención de respuesta para errores de negocio:**

```python
return render(request, "partials/modal_error.html", {"error": str(e)})
```

El partial reemplaza el contenido del modal. El modal no se cierra
— muestra el error en contexto.

Ver `docs/decisions/frontend.md` para la convención completa de modales.

---

## Estructura de URLs — `backoffice_urls.py` centralizado

**Decisión:** Un archivo `apps/backoffice_urls.py` centraliza los
includes de todas las apps del backoffice.

**Jerarquía:**

``` bash
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

**Justificación:** un único lugar donde están todas las rutas del
backoffice. Middleware o decoradores que apliquen a todo el backoffice
se configuran en un solo punto.

---

## `SoftDeleteModel` — deuda técnica en `soft_delete()` y `restore()`

**⚠️ DEUDA CONOCIDA:** cuando `actor=None`, `updated_by` no se limpia.
Si el modelo tenía `updated_by=user_X` de la última edición, el audit
log registra el soft delete con `actor=user_X`. Atribución incorrecta
para acciones ejecutadas por Celery.

**No se activa en:** `Contact` — archive siempre es acción humana.

**Se activa en:** `Listing` y `RentalContract` cuando Celery dispara
archivos automáticos.

**Fix pendiente antes de implementar esos flujos:**

```python
def soft_delete(self, actor=None):
    self.deleted_at = timezone.now()
    self.updated_by = actor  # incondicional — None = sistema
    self.save()
```

---

## `Listing.property` — corrección de nombre de campo

**Decisión:** El campo FK se llama `property`, no `property_id`.

**Contexto:** El modelo original declaraba `property_id = models.ForeignKey(...)`.
Django agrega `_id` automáticamente a la columna de DB para cualquier FK,
resultando en una columna `property_id_id` — error de nomenclatura.

**Corrección aplicada:** `RenameField` via migración `0002`. La columna
en DB pasó de `property_id_id` a `property_id`.

## `Document` — soft delete + invariante de múltiples padres

**Decisión anterior (reemplazada):** hard delete directo, exactamente un FK padre.

**Decisión actual:**

- `Document` hereda `SoftDeleteModel` + `AuditableMixin`
- Hard delete disponible únicamente desde vista de papelera — siempre R2 primero, DB después
- INVARIANTE: al menos una FK padre presente — puede asociarse a múltiples entidades simultáneamente
- El service valida el invariante — no hay constraint en DB

**Justificación:** un documento legal puede pertenecer a múltiples entidades
(escritura asociada a propiedad + propietario). Forzar un único padre
obliga a duplicar archivos o perder contexto operativo.

## Imports cross-app de type hints — `TYPE_CHECKING`

**Decisión:** Cuando un service o selector necesita el tipo de un modelo
de otra app *solo para anotaciones* (sin queries en runtime), el import
vive dentro del bloque `TYPE_CHECKING`.

**Patrón:**

```python
from __future__ import annotations  # obligatorio — ver abajo
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.contracts.models import RentalContract
    from apps.contacts.models import Contact
    from apps.deals.models import Deal

def create_billing_document(
    *,
    contract: RentalContract | None = None,
    recipient_contact: Contact | None = None,
    deal: Deal | None = None,
    ...
) -> BillingDocument:
```

**`from __future__ import annotations` es obligatorio** en cualquier
módulo que use este patrón. Sin él, Python evalúa las anotaciones en
runtime y `"RentalContract" | None` lanza `TypeError` porque `str | NoneType`
no es una operación válida. Con la importación futura activada, todas las
anotaciones del módulo se vuelven strings lazy y nunca se evalúan en runtime.

**Motivo de la regla:** importar `models.py` de otra app en runtime viola
la convención "cross-app solo via selectors/services/choices". Aunque
un import de type hint no genera queries, establece una dependencia
de importación entre módulos que puede crear imports circulares y acopla
la estructura interna de apps. `TYPE_CHECKING` resuelve el dilema:
el type checker ve el tipo, el runtime no ejecuta el import.

**`User` — caso especial:** `User` se importa via `get_user_model()` en
runtime (no bajo `TYPE_CHECKING`) porque Django lo requiere para resolver
`AUTH_USER_MODEL`. No va bajo `TYPE_CHECKING`.

```python
from django.contrib.auth import get_user_model
User = get_user_model()
```

**Aplica actualmente en:** `billing/services.py` y `billing/selectors.py`.
Cualquier vertical nueva que necesite tipos de otra app sin queries reales
debe seguir este patrón.

---

## `categorize_document` — fuente de verdad en `documents/utils.py`

**Decisión:** La función `categorize_document(content_type: str) -> str`
vive en `apps/documents/utils.py`. Es la única fuente autorizada.

**Contexto:** durante el desarrollo inicial existía una copia en
`apps/common/storage.py`. Esa copia fue eliminada en la auditoría de
coherencia — `common/storage.py` se ocupa de acceso a R2 y generación
de URLs, no de lógica de presentación de documentos.

**Callers:** `apps/properties/views.py` importa desde `documents/utils`.
Cualquier nueva view o template tag que necesite categorizar archivos
debe importar desde la misma fuente.

```python
# correcto
from apps.documents.utils import categorize_document

# incorrecto — la función ya no existe ahí
from apps.common.storage import categorize_document
```

Nota: este import cross-app (`properties` importando de `documents/utils`)
es una función pura sin queries — no rompe la regla de "cross-app via
selectors" en su intención. Aun así, si en el futuro la view de properties
acumula más imports de `documents`, conviene evaluar si la lógica de
presentación debería consolidarse en un selector o context dedicado.

---

## Formularios con FK — `UUIDField` en lugar de `ModelChoiceField`

Para formularios donde los campos FK referencian modelos con muchos
registros, se usa `forms.UUIDField` en lugar de `ModelChoiceField`.

```python
class RentalContractForm(forms.Form):
    property_id = forms.UUIDField(...)
    tenant_contact_id = forms.UUIDField(...)
```

El combobox con búsqueda live llena un `<input type="hidden">` con
el UUID. El form valida que sea un UUID válido. El service recibe el
UUID y resuelve la instancia — la validación de existencia ocurre
a nivel de FK constraint en DB, no en el form.

**Por qué no `ModelChoiceField`:** un `<select>` con 500 contactos
es inviable en producción. El combobox requiere que el form acepte
el UUID directamente.

---

## Funciones de contexto en views — `_build_*_context`

Cuando una view necesita construir un diccionario de presentación
con lógica no trivial (colorización por días, textos condicionales),
esa lógica vive en una función privada `_build_*_context` en el
módulo de views, no en el template ni en el selector.

```python
def _build_adjustment_context(contract, today):
    days = (contract.next_adjustment_date - today).days
    if days < 0:
        return {"style": "danger", "text": f"Vencido hace {abs(days)} días", ...}
    ...
```

**Motivo:** los templates no deben contener lógica de negocio.
Los selectors devuelven datos del modelo, no decisiones de UI.
Las views son el lugar correcto para resolver "qué mostrar y cómo".

---

## Excepciones enriquecidas — adjuntar instancia conflictiva

Cuando una excepción de negocio puede adjuntar el objeto que causó
el error, hacerlo en el `__init__` evita queries adicionales en la view:

```python
class ContractDateConflict(ContractValidationError):
    def __init__(self, message="", conflicting_contract=None):
        self.conflicting_contract = conflicting_contract
        super().__init__(message)
```

El service hace `select_related` antes del raise para que la instancia
llegue hidratada. La view extrae `e.conflicting_contract` del except
y lo pasa directamente al template.

**Aplica cuando:** la excepción tiene contexto útil para el usuario
final (qué contrato, qué propiedad, qué fecha) que sería costoso
o tedioso reconstruir en la view.
