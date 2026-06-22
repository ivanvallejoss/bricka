# Decisiones de Frontend — Bricka CRM

Registro de decisiones técnicas y de diseño tomadas durante la
implementación de la capa de templates. Complementa `design.md`
(decisiones de backend) y `audit.md`.

---

## Stack y herramientas

- **Django Templates** — capa de renderizado
- **HTMX 2.0.4** — interactividad sin SPA, via `django-htmx`
- **Alpine.js 3.14.9** — estado local en componentes
- **Tailwind v4** — utility-first CSS, compilado con `bun run dev`
- **Flowbite v3** — componentes UI sobre Tailwind v4

El CSS de producción se genera con `bun run build`. La fuente de
verdad del sistema de diseño es `static/src/input.css` — nunca
asumir valores de tokens sin verificarla.

---

## Convenciones de color — estados semánticos

Los colores de estado tienen semántica fija. No intercambiar.

| Estado | Token | Uso |
| -------- | ------- | ----- |
| Disponible | `success-bg/text` | Propiedad disponible |
| Alquilada | `alquiler-bg/text` | Propiedad con contrato activo |
| Vendida | `venta-bg/text` | Propiedad vendida |
| No disponible | `surface-container / on-surface-variant` | Sin actividad |
| Pago (billing) | `success-bg/text` | Recibo emitido en el período |
| Pendiente (billing) | `warning-bg/text` | Sin recibo, dentro del plazo |
| En mora (billing) | `danger-bg/text` | Sin recibo, fuera del plazo |

**Regla que no se negocia:** `warning-bg/text` está reservado para
PENDING de billing. "Alquilada" usa `alquiler-bg/text` (azul), no
warning (amarillo) — amarillo comunica precaución, no estado operativo.

---

## `PropertyStatus` — comparaciones en templates

`PropertyStatus` persiste en lowercase en la DB:

```python
AVAILABLE   = "available"
RENTED      = "rented"
SOLD        = "sold"
UNAVAILABLE = "unavailable"
```

Los templates **siempre** comparan con minúsculas:

```html
{% if property.status == 'rented' %}   {# correcto #}
{% if property.status == 'RENTED' %}   {# incorrecto — nunca es True #}
```

---

## Patrones HTMX establecidos

### Full page vs partial

Cada view soporta los dos modos:

```python
if request.htmx:
    return render(request, "app/partials/_componente.html", context)
return render(request, "app/full_page.html", context)
```

### Acción exitosa (POST que redirige)

```python
response = HttpResponse(status=204)
response["HX-Redirect"] = reverse("nombre-url")
return response
```

### Error de negocio

```python
return render(request, "partials/modal_error.html", {"error": str(e)})
```

---

## `hx-trigger="revealed"` vs `hx-trigger="load"`

**El problema:** `revealed` usa `IntersectionObserver` con el viewport
del browser como root. Cuando el scroll ocurre dentro de un contenedor
propio (`overflow-y-auto`) en lugar del window, los elementos "debajo
del fold" dentro de ese contenedor son visibles para el observer aunque
el usuario no los vea todavía.

**Regla:**

- `hx-trigger="revealed"` — usar cuando el scroll es del **window**,
  o cuando el contenedor scrollable es suficientemente pequeño que los
  elementos realmente quedan fuera del viewport visible (ej: el panel
  del slide-over).
- `hx-trigger="load"` — usar en `property_detail.html` y cualquier
  página donde el scroll ocurre dentro de `<main class="overflow-y-auto">`.

**Síntoma del bug:** el spinner desaparece y el contenido carga al
abrir DevTools — el reflow fuerza una reevaluación del observer.

---

## Slide-over — arquitectura

El slide-over vive en `#slide-over-container`, un div vacío al final
del content area en `base.html`. Se carga via HTMX con `hx-swap="innerHTML"`.

**Shell (`_slide_over.html`):** Alpine controla la animación de entrada/
salida y el backdrop. Al cerrar, espera 200ms antes de limpiar el
container para que la animación de salida complete.

**Secciones internas:** todas las secciones dentro del panel usan
`hx-trigger="revealed"` — el panel es más pequeño que el viewport,
por lo que el observer funciona correctamente.

**Estructura del panel:**

```mermaid
┌─ Header con cover de fondo (shrink-0) ──────┐
│  Zona 1: imagen cover + título               │
│  Zona 2: badges + precio                     │
├─ Características (shrink-0) ────────────────┤
├─ Secciones lazy (flex-1, overflow-y-auto) ──┤
│  Publicaciones                               │
│  Billing (condicional — solo si alquilada)  │
│  Contactos                                   │
│  Documentos                                  │
├─ Action bar (shrink-0) ─────────────────────┘
```

**Convención de mobile:** en viewport < 768px, el click en una row
de la lista navega a `property_detail` directamente — sin slide-over.
El slide-over es desktop-only por diseño.

```javascript
// _property_rows.html
window.innerWidth >= 768
    ? htmx.ajax('GET', slideUrl, { target: '#slide-over-container' })
    : (window.location.href = detailUrl)
```

---

## Badge contextual en listas — patrón `BadgeContext`

Cuando una card o row necesita un badge computado (no derivable
directamente del modelo), se usa `BadgeContext`:

```python
# apps/properties/contexts.py
@dataclass
class BadgeContext:
    text: str
    style: str  # 'success' | 'warning' | 'danger'
```

El badge se resuelve en la view, nunca en el template. El template
solo decide el color según `badge.style`:

```html
{% if ctx.contextual_badge %}
    {% with badge=ctx.contextual_badge %}
        <span class="...
            {% if badge.style == 'success' %}border border-success-text text-success-text
            {% elif badge.style == 'warning' %}border border-warning-text text-warning-text
            {% elif badge.style == 'danger' %}border border-danger-text text-danger-text
            {% endif %}">
            {{ badge.text }}
        </span>
    {% endwith %}
{% endif %}
```

**Nota de diseño:** los badges de disponibilidad usan estilo filled
(`bg-*`). Los badges de billing usan estilo outlined (solo `border` +
`text-*`, sin fondo). Esto permite distinguir visualmente las dos
capas de información en la misma row.

---

## Building blocks de prefetch — patrón establecido

Los prefetch reutilizables se exportan como funciones desde sus
selectors. El caller los inyecta en el queryset sin conocer los
detalles internos.

```python
# apps/listings/selectors.py
def active_listings_prefetch() -> Prefetch: ...

# apps/contracts/selectors.py
def active_contracts_prefetch() -> Prefetch: ...
```

Uso en `get_property_list`:

```python
qs = Property.objects.prefetch_related(
    active_listings_prefetch(),
    active_contracts_prefetch(),
    Prefetch("media", ...),
)
```

El resultado se accede via `to_attr`:

- `prop.active_listings` — listings publicados o pausados
- `prop.active_contracts_list` — contratos ACTIVE

---

## Precio en `property_detail` — fuente de verdad

La fuente del precio depende del estado de la propiedad:

| Estado | Fuente | Campo |
| -------- | -------- | ------- |
| `rented` | Contrato activo | `active_contract.current_price` |
| Cualquier otro | Listings activos | `listing.price` |

**Motivo:** cuando una propiedad está alquilada, el listing puede estar
cerrado o no existir. El precio contractual actual es `current_price`
en `RentalContract` — se actualiza en cada ajuste de alquiler.

---

## Cross-app en views — prohibición de acceso directo a modelos

Las views no importan modelos de otras apps directamente. Todo acceso
cross-app pasa por el selector correspondiente.

```python
# incorrecto
from apps.billing.models import BillingDocument
count = BillingDocument.objects.filter(contract=contract).count()

# correcto
from apps.billing.selectors import get_billing_document_count_for_contract
count = get_billing_document_count_for_contract(contract.id)
```

Esta regla ya existía para services — se extiende explícitamente a views.

---

## Imports en views — nivel de módulo

Los imports van al bloque de imports del módulo, nunca dentro de
funciones. Las constantes que se recalcularían en cada request van
a nivel de módulo.

```python
# incorrecto — se recrea en cada request
def property_list(request):
    from apps.billing.choices import PaymentStatus
    _BADGE_MAP = { ... }

# correcto
from apps.billing.choices import PaymentStatus

_BADGE_MAP = {
    PaymentStatus.PAID:    BadgeContext(text="Pago",      style="success"),
    PaymentStatus.PENDING: BadgeContext(text="Pendiente", style="warning"),
    PaymentStatus.OVERDUE: BadgeContext(text="En mora",   style="danger"),
}
```

---

## Layout `property_detail` — dos columnas desktop, single-column mobile

```mermaid
Desktop (lg+):
┌─ Columna principal (1fr) ─┬─ Sidebar (320px, sticky) ─┐
│ Hero                       │ Card estado + precio       │
│ Descripción                │ Card resumen (docs/facts)  │
│ Galería                    │ Card contactos             │
│ Publicaciones              │ Card acciones              │
│ Documentos                 │                            │
│ Facturación                │                            │
└───────────────────────────┴────────────────────────────┘

Mobile (< lg):
Hero → Sidebar inline → Descripción → Galería → Publicaciones
→ Documentos → Facturación
```

El sidebar se renderiza dos veces en el HTML con visibilidad
controlada por clases:

```html
{# Mobile — inline después del hero #}
<div class="lg:hidden">
    {% include "properties/partials/_detail_sidebar.html" %}
</div>

{# Desktop — sticky en segunda columna #}
<div class="hidden lg:block">
    <div class="sticky top-6">
        {% include "properties/partials/_detail_sidebar.html" %}
    </div>
</div>
```

**Consecuencia para el sidebar:** no poner contenido en el sidebar
que deba aparecer después de la columna principal en mobile. El sidebar
siempre aparece antes en el DOM. Los documentos y comprobantes van
en la columna principal — el sidebar muestra solo un resumen con
contador y anchor link.

---

## Spacing entre elementos — `flex flex-col gap-*` vs `space-y-*`

En Tailwind v4, `space-y-*` puede no aplicarse correctamente en
ciertos contextos. Usar `flex flex-col gap-*` para separación entre
cards o elementos apilados — es más predecible y directo.

```html
{# preferido #}
<div class="flex flex-col gap-4">

{# evitar para separación entre cards #}
<div class="space-y-4">
```

---

## Trabajo pendiente al cierre de esta ventana

### Mobile

**Bottom nav (`base.html`):**
El bloque existe como comentario vacío. Implementar navegación inferior
con los mismos destinos que el sidebar desktop: Inicio, Propiedades,
Contactos, Publicaciones, Contratos, Facturación.

Patrón esperado:

```html
{# ── Bottom nav — mobile only ─────────────────────────────────── #}
<nav class="md:hidden fixed bottom-0 left-0 right-0 z-30
            bg-primary border-t border-white/10 pb-safe">
    {# 5 items máximo — iconos + label corto #}
</nav>
```

**Verificaciones responsive pendientes:**

- `property_list` en mobile — la tabla puede necesitar simplificarse
  (columnas de precio y acciones pueden ocultarse o colapsarse)
- `property_detail` — el layout single-column ya está implementado
  via `lg:hidden` / `hidden lg:block`, verificar que fluya correctamente

### Verticales restantes

Una vez cerrado mobile, el orden natural de implementación es:

1. **`contacts/`** — lista con filtros, detalle, formulario de creación/edición
2. **`contracts/`** — lista, detalle con historial de ajustes
3. **`billing/`** — lista de comprobantes, emisión de recibo
4. **`listings/`** — lista, detalle, cambio de estado
5. **`deals/`** — pipeline, detalle

Cada vertical sigue el mismo patrón establecido en `properties/`:
lista con filtros + slide-over (o modal) + detail page.

---

## Sesión 3 — Mobile + Vertical Contacts

---

## OOB elements — posición en partials con target de tabla

**Convención que no se negocia:** cuando el partial es la respuesta a un
swap HTMX cuyo target es un elemento de tabla (`<tbody>`, `<tr>`), los
elementos `hx-swap-oob` deben ubicarse **siempre al final** del partial,
después de todo el contenido de tabla.

**Causa del bug:** el browser parsea la respuesta antes de que HTMX la
procese. Un `<span hx-swap-oob>` al principio de la respuesta es HTML
inválido dentro de `<tbody>`. El browser lo extrae automáticamente,
destruyendo la estructura de la tabla en el proceso. HTMX recibe un
DOM ya roto.

**Patrón correcto:**

```html
{# _property_rows.html — correcto #}
{% for prop in properties %}
<tr>...</tr>
{% endfor %}

{# sentinel de infinite scroll #}
{% if page_obj.has_next %}
<tr hx-get="..." hx-trigger="revealed" ...>...</tr>
{% endif %}

{# OOB SIEMPRE AL FINAL #}
{% if request.htmx %}
<span id="property-counter" hx-swap-oob="true">
    {{ total_count }} propiedad{{ total_count|pluralize:"es" }}
</span>
{% endif %}
```

**Aplica a:** `_property_rows.html`, `contact_list_table.html`, y
cualquier partial futuro con target de tabla.

---

## Tablas HTMX — `table-fixed` + `<colgroup>` obligatorio

Las tablas con swap HTMX usan siempre `table-fixed` con `<colgroup>`
explícito. `table-auto` recalcula anchos desde el contenido después de
cada swap y puede colapsar columnas.

```html
<table class="w-full table-fixed">
    <colgroup>
        <col class="w-12">          {# ancho fijo #}
        <col>                        {# flex fill #}
        <col class="w-0 md:w-28">   {# oculto mobile → fijo desktop #}
    </colgroup>
```

Los `<th>` y `<td>` de columnas ocultas en mobile usan
`hidden md:table-cell`. La `<col>` correspondiente usa `w-0 md:w-XX`
para no reservar espacio en mobile.

---

## Mobile — precio inline en columna de título

Cuando una columna de precio se oculta en mobile (`hidden md:table-cell`),
el precio se muestra inline debajo del título en la celda de nombre:

```html
<td class="py-3 pl-3 pr-5 md:px-3 min-w-0">
    <p class="text-[13px] md:text-[15px] font-medium text-on-surface truncate">
        {{ property.title|default:property.address_line }}
    </p>
    {% if property.title %}
    <p class="hidden md:block text-xs text-on-surface-variant truncate mt-0.5">
        {{ property.address_line }}
    </p>
    {% endif %}
    {% if ctx.display_price %}
    <p class="md:hidden text-xs font-medium text-on-surface tabular-nums mt-0.5">
        ${{ ctx.display_price|floatformat:0 }}
    </p>
    {% endif %}
</td>
```

El precio nunca desaparece — siempre está visible, cambia de columna
a texto inline en mobile.

---

## Bottom nav mobile — convenciones

Implementado en `base.html`. Patrón establecido:

```html
<nav class="md:hidden fixed bottom-0 left-0 right-0 z-30
            bg-primary border-t border-white/10 pb-safe">
    <div class="h-16 grid grid-cols-5">
        {# 5 items: icono 17px + label text-[10px] #}
    </div>
</nav>
```

**`pb-safe`** es una custom utility en `input.css`:

```css
@utility pb-safe {
  padding-bottom: env(safe-area-inset-bottom, 0px);
}
```

Requiere `viewport-fit=cover` en el meta viewport:

```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
```

`<main>` usa `pb-28 md:pb-6` para compensar la altura del nav (h-16 = 64px)
más la safe area de iOS (hasta 34px).

**Active state:** usar `request.resolver_match.app_name` si la app tiene
`app_name` declarado. Para apps sin namespace, usar `request.path`.

**Items actuales:** Propiedades / Contactos / Publicaciones / Contratos /
Facturación. Inicio se maneja como `/backoffice/` separado — no ocupa
slot en el nav.

---

## `app_name` — obligatorio para navegación

Toda app con templates que aparezca en la navegación (sidebar o bottom nav)
**debe** declarar `app_name` en su `urls.py`. Sin esto, el active state
nunca funciona porque `request.resolver_match.app_name` devuelve `''`.

Consecuencia en views: todos los `reverse()` deben usar el namespace:

```python
reverse("contacts:contact-list")   # correcto
reverse("contact-list")            # incorrecto si app_name está declarado
```

**Apps con `app_name` activo:** `properties` (properties), `contacts` (contacts).
**Apps pendientes de declarar:** `contracts`, `listings`, `billing`, `deals`.

---

## Middleware de backoffice — reemplaza `@login_required`

En lugar de decorar cada view con `@login_required`, el acceso al
backoffice se controla via middleware transversal:

```python
# config/middleware.py
from django.conf import settings
from django.http import HttpResponseRedirect


class BackofficeLoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.path.startswith("/backoffice/")
            and not request.user.is_authenticated
        ):
            return HttpResponseRedirect(
                f"{settings.LOGIN_URL}?next={request.path}"
            )
        return self.get_response(request)
```

Registrado en `settings.py` como `"config.middleware.BackofficeLoginRequiredMiddleware"`.

**Consecuencia en services:** `actor=request.user` es siempre un `User`
válido dentro del backoffice — el middleware garantiza autenticación
antes de llegar a cualquier view.

---

## `base.html` — elementos de infraestructura agregados

Tres elementos añadidos durante esta sesión que todas las verticales usan:

```html
{# id para targets HTMX desde otras vistas #}
<main id="main-content" class="...">

{# Container para modales — al final del body, antes de scripts #}
<div id="modal-container"></div>
```

El `#modal-container` recibe el HTML del modal via HTMX swap. El modal
se construye autosuficiente con Alpine: incluye backdrop, animación de
entrada/salida, y limpia el container al cerrarse:

```javascript
$watch('open', v => {
    if (!v) setTimeout(() => {
        document.getElementById('modal-container').innerHTML = ''
    }, 200)
});
```

---

## Modal — patrón establecido

Creación y edición se manejan con un único template de modal
(`contact_form_modal.html`) que recibe `is_create` y `contact` del
contexto. La view detecta `request.htmx` y devuelve el modal o la
full page según corresponda.

Flujo HTMX:

- GET → view devuelve modal HTML → HTMX inyecta en `#modal-container`
- POST éxito → `HX-Redirect` → modal desaparece con redirect
- POST error → view re-renderiza modal con errores inline → HTMX
  reemplaza `#modal-container`

El CSRF se inyecta via el header global en `<body>`:

```html
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
```

---

## Archivado two-step — patrón Alpine inline

Para acciones destructivas sin modal separado:

```html
<div x-data="{ confirming: false }">
    <button x-show="!confirming" @click="confirming = true" ...>
        Archivar
    </button>
    <div x-show="confirming" x-cloak class="flex items-center gap-2">
        <span class="text-sm text-on-surface-variant">¿Confirmar?</span>
        <button @click="confirming = false" ...>No</button>
        <button hx-post="..."
                hx-target="#archive-error"
                hx-swap="innerHTML"
                @click="confirming = false" ...>
            Sí
        </button>
    </div>
</div>
<div id="archive-error"></div>
```

Errores de negocio (ej: `ContactHasOpenDeals`) se muestran inline en
`#archive-error` via `partials/modal_error.html`.

---

## `partials/modal_error.html` — partial compartido

Vive en `templates/partials/` (no dentro de ninguna app). Usado por
cualquier view que devuelva errores de negocio via HTMX:

```html
<div class="p-4 rounded-md bg-danger-bg border border-danger-text/20">
    <p class="text-sm font-medium text-danger-text">{{ error }}</p>
</div>
```

---

## Estado de verticales al cierre de sesión 3

| Vertical | Lista | Detail | Crear | Editar | Archivar | Mobile |
| ---------- | ------- | -------- | ------- | -------- | ---------- | -------- |
| `properties/` | ✅ | ✅ | — | — | — | ✅ |
| `contacts/` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `contracts/` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `billing/` | ❌ | ❌ | ❌ | — | — | ❌ |
| `listings/` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `deals/` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

---

## Gaps deliberadamente diferidos

**Contact restore:** no hay UI para restaurar contactos archivados.
Diferido hasta que exista una vista de contactos archivados o papelera.

**`contact_detail_panel.html`:** existe como stub vacío. El partial
HTMX para cargar detalle de contacto en `#main-content` desde otras
vistas no está implementado — no hay caso de uso activo todavía.

**Thumbnail mobile en `property_list`:** la columna de thumbnail
usa `shadow-[inset_-4px_0_6px_rgba(0,11,32,0.06)]` que puede no
renderizar igual en todos los browsers. Pendiente de verificación en
dispositivo real.

**Sidebar `_detail_sidebar.html`** (`properties/`): corregidos
`space-y-4` → `flex flex-col gap-4` y atributo HTML inválido
`space-y-2` suelto. Verificar que los dos fixes fueron aplicados.

**Anchor links en `property_detail`:** `#documentos` y `#facturacion`
del sidebar inline apuntan a elementos dentro de `<main
class="overflow-y-auto">`. Funcionan en browsers modernos. No requieren
fix por ahora.

**`properties/` — `w-0` en `<col>`:** el mismo patrón de columnas
ocultas con `w-0 md:w-XX` que se usó en `contact_list` existe también
en `property_list`. Si el colapso de columnas aparece en properties
tras algún cambio de HTMX, aplicar el mismo fix de OOB al final.

**`docs/decisions/frontend.md` no se actualiza automáticamente:** las
convenciones de cada sesión deben agregarse manualmente al cierre.
Abriendo una nueva ventana de contexto, adjuntar este documento
actualizado junto al prompt de sesión.
