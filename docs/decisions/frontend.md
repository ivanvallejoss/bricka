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
