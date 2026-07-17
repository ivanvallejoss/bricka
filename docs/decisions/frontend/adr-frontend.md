# Parte 2 — Registro de decisiones (ADR)

Cada entrada: contexto, decisión y trade-off aceptado.

## Stack y tooling

### Stack de frontend — librerías y versiones

**Decisión:** Django Templates + HTMX 2.0.4 + Alpine.js 3.14.9 + Tailwind v4

+ Flowbite v3 (CDN 3.1.2).

**Integración HTMX:** vía `django-htmx`. Setup:

```python
INSTALLED_APPS = [..., "django_htmx"]
MIDDLEWARE = [..., "django_htmx.middleware.HtmxMiddleware"]
```

Permite usar `request.htmx` en las views en lugar de chequear el header
`HX-Request` manualmente.

**Alpine.js:** carga con `defer` obligatorio — debe evaluarse post-DOM.

**Tailwind v4:** el CSS se compila con `bun run dev` (watch) y `bun run build`
(producción). La fuente de verdad del design system es `static/src/input.css`.
Nunca asumir valores de tokens sin verificarla; el archivo es corto y legible.

**Flowbite:** el plugin se importa en `input.css` (`@plugin "flowbite/plugin"`)
pero el JS de componentes interactivos viene del CDN. La versión del CDN es
3.1.2 aunque el paquete se llame Flowbite v3.

**Por qué esta combinación:** evitar un SPA (React/Vue) para un CRM interno de
escritorio operado por usuarios no técnicos. HTMX cubre el 90% de la
interactividad (listas filtradas, carga lazy, swaps). Alpine cubre el estado
local de componentes (animaciones de modal, toggle de confirmación). El
servidor sigue siendo la fuente de verdad del estado.

---

## Tokens y color

### Tokens semánticos de color

**Decisión:** todos los colores de estado se expresan con tokens semánticos
definidos en `input.css`, nunca con valores hex directos.

Los tokens de estado semántico disponibles son:

```css
--color-success-bg / --color-success-text   /* verde claro / verde oscuro */
--color-warning-bg / --color-warning-text   /* amarillo claro / ámbar */
--color-danger-bg  / --color-danger-text    /* rojo claro / rojo oscuro */
--color-info-bg    / --color-info-text      /* azul claro / azul oscuro */
--color-alquiler-bg / --color-alquiler-text /* azul — igual a info, semántica distinta */
--color-venta-bg    / --color-venta-text    /* violeta */
```

**Regla que no se negocia:** `warning-bg/text` está reservado exclusivamente
para el estado PENDING de billing. "Alquilada" usa `alquiler-bg/text` (azul),
no `warning` (amarillo) — amarillo comunica precaución, no estado operativo.
Un socio que ve una propiedad "alquilada" en amarillo asume que algo está mal.

**Trade-off aceptado:** `alquiler-bg/text` y `info-bg/text` tienen los mismos
valores hex en `input.css`. La distinción es semántica, no visual. Si el diseño
evoluciona, info y alquiler pueden diferenciarse sin cambiar templates.

---

### `PropertyStatus` — comparaciones en minúsculas

**Decisión:** `PropertyStatus` persiste en la DB en lowercase
(`available`, `rented`, `sold`, `unavailable`). Los templates comparan siempre
con minúsculas.

```html
{% if property.status == 'rented' %}   {# correcto #}
{% if property.status == 'RENTED' %}   {# incorrecto — nunca es True #}
```

**Motivo:** Django guarda el value del choice, no el label. El value está
definido en minúsculas. Comparar con mayúsculas siempre falla en silencio.

---

## Patrones HTMX

### Full page vs partial — patrón base

**Decisión:** cada view que sirve contenido renderizable soporta los dos modos.
La view detecta `request.htmx` y devuelve el partial o la full page:

```python
if request.htmx:
    return render(request, "app/partials/_componente.html", context)
return render(request, "app/full_page.html", context)
```

**Justificación:** permite navegación directa vía URL (full page) y
actualización parcial vía HTMX sin duplicar la lógica de la view. El partial
puede ser incluido (`{% include %}`) en la full page para el render inicial.

---

### Respuesta de acción exitosa — HTTP 204 + HX-Redirect

**Decisión:** un POST que procesa correctamente y debe redirigir devuelve
`HttpResponse(status=204)` con el header `HX-Redirect`:

```python
response = HttpResponse(status=204)
response["HX-Redirect"] = reverse("nombre-url")
return response
```

**Por qué 204 y no 200:** HTMX por defecto intenta hacer swap con el cuerpo
de la respuesta. Un 204 (No Content) indica explícitamente que no hay cuerpo
— HTMX procesa solo los headers de respuesta. `HX-Redirect` es el header que
dispara la navegación del browser.

**Alternativa descartada:** devolver un 200 con cuerpo vacío y confiar en que
HTMX no haga nada — frágil si el target tiene contenido anterior.

---

### Respuesta de error de negocio

**Decisión:** cuando un POST encuentra un error de negocio (excepción de
dominio), la view devuelve el partial de error compartido:

```python
return render(request, "partials/modal_error.html", {"error": str(e)})
```

El partial reemplaza el contenido del modal (o el target designado). El modal
no se cierra — muestra el error en contexto. Ver
[`modal_error.html`](#modal_errorhtml--partial-compartido) para la ubicación.

**Trade-off:** el mensaje de error es el `str(e)` de la excepción. Requiere
que todas las excepciones de negocio tengan mensajes legibles para el usuario
final, no mensajes técnicos.

---

### `hx-trigger` — "load" vs "revealed"

**Contexto del bug:** `revealed` usa `IntersectionObserver` con el viewport
del browser como root. Cuando el scroll ocurre dentro de un contenedor propio
(`overflow-y-auto`) en lugar del window, los elementos que están "debajo del
fold" dentro de ese contenedor son visibles para el observer aunque el usuario
no los vea todavía. El resultado: los spinners desaparecen y el contenido se
carga al abrir la página, sin que el usuario haya hecho scroll.

**Síntoma adicional:** el spinner reaparece al abrir DevTools — el reflow
fuerza una reevaluación del observer.

**Regla resultante:**

+ `hx-trigger="load"` — en `property_detail.html` y cualquier página donde
  el scroll ocurre dentro de `<main class="overflow-y-auto">`. El elemento
  está técnicamente visible desde el principio para el observer.
+ `hx-trigger="revealed"` — en el slide-over y en contenedores con scroll
  propio donde el panel es más pequeño que el viewport. Los elementos debajo
  del fold del panel realmente están fuera del viewport visible.

---

### OOB elements — posición en partials de tabla

**Convención que no se negocia:** cuando el partial es la respuesta a un swap
HTMX cuyo target es un elemento de tabla (`<tbody>`, `<tr>`), los elementos
`hx-swap-oob` deben ubicarse **siempre al final** del partial.

**Causa:** el browser parsea la respuesta antes de que HTMX la procese. Un
`<span hx-swap-oob>` al principio de la respuesta es HTML inválido dentro de
`<tbody>`. El browser lo extrae automáticamente, rompiendo la estructura del
DOM antes de que HTMX pueda actuar.

**Patrón correcto:**

```html
{# _property_rows.html #}
{% for prop in properties %}
<tr>...</tr>
{% endfor %}

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

**Aplica a:** `_property_rows.html`, `contact_list_table.html`, y cualquier
partial futuro con target de tabla.

---

### Lista multi-sección con scroll independiente

**Contexto:** la vertical `contracts/` tiene estados cualitativamente distintos
(activo / programado / finalizado) con información y acciones distintas.

**Decisión:** en lugar de un único listado con pills de filtro, la lista se
divide en secciones con `hx-get`, `hx-trigger` y `hx-swap="innerHTML"` propios.
El filtro global usa `hx-include` para pasar el query a las tres secciones
simultáneamente vía un evento Alpine:

```javascript
search() {
    htmx.trigger(document.getElementById('section-active'),    'refresh');
    htmx.trigger(document.getElementById('section-scheduled'), 'refresh');
    htmx.trigger(document.getElementById('section-closed'),    'refresh');
}
```

La view detecta `request.GET["section"]` y devuelve el partial correspondiente.
La sección primaria usa `hx-trigger="load"` — las secundarias usan `revealed`.

**Cuándo aplicar:** cuando los estados tienen información y acciones
cualitativamente distintas y el usuario necesita verlos simultáneamente sin
cambiar de tab.

**Cuándo no aplicar:** cuando los estados son variantes del mismo objeto con
la misma estructura de datos — usar pills de filtro con un único listado.

---

### Forma de respuesta de una mutación — JSON, HTML o 204

**Decisión:** un endpoint de mutación elige su forma de respuesta por un solo
criterio — **qué necesita el cliente después**, no qué le resulta cómodo al
servidor:

+ **JSON** cuando la respuesta son *datos que el cliente va a consumir para
  actuar*. Ej.: `sign` devuelve `{key, url}` para que la cola haga el PUT a R2.
+ **HTML server-rendered** cuando la respuesta es *presentación de estado ya
  persistido*. Ej.: `confirm` devuelve el card de la foto (+ contador OOB);
  `set_cover` / `delete` devuelven la galería completa.
+ **204 (No Content)** cuando *no hay ni datos ni presentación nueva* — el
  cliente ya tiene la verdad que impuso. Ej.: `reorder` exitoso (el DOM
  optimista del drag ya es correcto; re-renderizar 35 cards no aporta nada).

**Principio (el que decide los casos de borde):** el cliente nunca re-deriva
una regla que el servidor es dueño de aplicar. La regla "quién es portada",
"cuántas fotos van", "qué orden es válido" vive en el servidor. Por eso el
**camino de error re-materializa la verdad** en vez de pedirle al cliente que
la recalcule: un `reorder` con set desincronizado devuelve `200` + la galería
re-renderizada (re-sync del DOM optimista a la verdad de DB), no un JSON que
obligaría al JS a reconstruir el orden. Éxito silencioso (204), error que
corrige (HTML).

**Fork A descartado — "JSON que muta":** que las mutaciones devolvieran JSON y
el cliente aplicara los cambios al DOM (mover el badge de portada, decrementar
el contador). Se descartó porque **duplica la regla de negocio en el JS**: el
badge de portada, la promoción del heredero al borrar, el contador del gate —
todas reglas que el servidor ya aplica y que el cliente tendría que reimplementar
para pintar el resultado. Dos implementaciones de la misma regla divergen. Es el
mismo argumento de no-duplicar validación entre form y service, un nivel más
abajo.

**Trade-off:** las mutaciones que devuelven HTML (`set_cover`, `delete`)
re-renderizan la galería entera (hasta 35 cards) en cada acción, no solo el card
afectado. Aceptado: el costo es chico frente al beneficio de que la galería
salga siempre de una sola fuente (DB), sin estado de DOM que reconciliar.

**Relación con los ADR vecinos:** el 204 acá es el mismo mecanismo que
[Acción exitosa](#respuesta-de-acción-exitosa--http-204--hx-redirect) (HTMX no
swapea sin cuerpo), pero sin `HX-Redirect` — no hay navegación, solo "no hay
nada nuevo que mostrar". El error acá NO usa
[`modal_error`](#respuesta-de-error-de-negocio): un `reorder` es un drag, no hay
modal en el DOM; su re-render de galería ES la recuperación.

---

## Layout y spacing

### Dos columnas desktop — sidebar renderizado dos veces

**Contexto:** `property_detail` necesita un sidebar sticky en desktop y el
mismo contenido inline en mobile.

**Decisión:** renderizar el sidebar dos veces en el HTML con visibilidad
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

**Consecuencia crítica para el sidebar:** no poner en el sidebar contenido que
deba aparecer después de la columna principal en mobile. El sidebar llega
primero en el DOM (`lg:hidden` está antes de la columna principal). Los
documentos y comprobantes van en la columna principal; el sidebar muestra solo
un resumen con contador y anchor link.

**Trade-off aceptado:** el HTML contiene el sidebar duplicado. Para un sidebar
de ~5 cards de resumen, el overhead es despreciable.

---

### Separación entre elementos — flex gap sobre space-y

**Contexto:** durante la implementación de `property_list`, `space-y-*` generó
comportamiento inesperado al ajustar tablas para mobile en Tailwind v4.

**Decisión resultante:** usar `flex flex-col gap-*` como convención principal
para separación entre cards o elementos apilados en el layout principal:

```html
{# preferido para separación entre cards #}
<div class="flex flex-col gap-4">

{# aceptable en sub-componentes internos acotados #}
<div class="space-y-2">
```

`space-y-*` es aceptable en sub-componentes internos acotados (listas de items
dentro de una card) donde el contexto es predecible. No es una prohibición
absoluta — es una preferencia que evita el caso problemático documentado.

---

### Tablas HTMX — `table-fixed` + `<colgroup>` obligatorio

**Decisión:** las tablas con swap HTMX usan siempre `table-fixed` con
`<colgroup>` explícito.

**Por qué:** `table-auto` recalcula los anchos desde el contenido después de
cada swap y puede colapsar columnas. Con `table-fixed`, el browser respeta los
anchos definidos en `<colgroup>` sin importar el contenido swapeado.

```html
<table class="w-full table-fixed">
    <colgroup>
        <col class="w-12">          {# ancho fijo #}
        <col>                        {# flex fill #}
        <col class="w-0 md:w-28">   {# oculto mobile → fijo desktop #}
    </colgroup>
```

**Columnas ocultas en mobile:** `hidden md:table-cell` en `<th>` y `<td>`.
La `<col>` correspondiente usa `w-0 md:w-XX`. Para más de 3 columnas, preferir
el dual layout de la siguiente entrada.

---

### Dual layout — cards mobile + tabla desktop

**Decisión:** para tablas con más de 3 columnas donde alguna debe ocultarse
en mobile, usar dos layouts explícitos:

```html
{# Mobile — cards con divide-y #}
<div class="md:hidden divide-y divide-outline">
    {% for doc in page_obj.object_list %}
    <div class="px-4 py-3">
        {# Una card por item — toda la info relevante #}
    </div>
    {% endfor %}
</div>

{# Desktop — tabla con table-fixed #}
<table class="hidden md:table w-full table-fixed">
    ...
</table>
```

El sentinel de infinite scroll va dentro de cada layout:

+ Mobile: `hx-target="closest .divide-y"` + `hx-swap="beforeend"`
+ Desktop: `hx-target="closest tbody"` + `hx-swap="beforeend"`

**Justificación:** dos layouts explícitos son más predecibles que depender del
colapso de columnas con `w-0`, cuyo comportamiento varía entre browsers.

---

## Componentes

### Slide-over — arquitectura y posicionamiento

**Decisión:** el slide-over vive en `#slide-over-container`, un div vacío al
final del content area en `base.html` (dentro del div `.flex-1`). Se carga
vía HTMX con `hx-swap="innerHTML"`.

**Por qué dentro del content area y no del body:** el slide-over usa `absolute
inset-0` — se posiciona sobre el área de contenido solamente. El sidebar
desktop queda visible. Un `fixed inset-0` cubriría también el sidebar, que no
es el comportamiento deseado para un panel de detalle.

**Shell (`_slide_over.html`):** Alpine controla la animación de entrada/salida
y el backdrop. Al cerrar, espera 200ms antes de limpiar el container:

```javascript
$watch('open', v => {
    if (!v) setTimeout(() => {
        document.getElementById('slide-over-container').innerHTML = ''
    }, 200)
});
```

**Secciones internas:** todas las secciones lazy del panel usan
`hx-trigger="revealed"` — el panel es más pequeño que el viewport, por lo que
el observer funciona correctamente.

**Estructura del panel:**

``` mermaid
┌─ Header con cover de fondo (shrink-0) ──────┐
│  Zona 1: imagen cover + título               │
│  Zona 2: badges + precio                     │
├─ Características (shrink-0) ────────────────┤
├─ Secciones lazy (flex-1, overflow-y-auto) ──┤
│  Publicaciones                               │
│  Cobro (condicional — solo si rented)        │
│  Contactos                                   │
│  Documentos                                  │
├─ Action bar (shrink-0) ─────────────────────┘
```

**Convención mobile:** en viewport < 768px, el click en una row navega a
`property_detail` directamente — sin slide-over:

```javascript
window.innerWidth >= 768
    ? htmx.ajax('GET', slideUrl, { target: '#slide-over-container' })
    : (window.location.href = detailUrl)
```

---

### Modal simple — shell Alpine + limpieza automática

**Decisión:** el modal genérico (creación, edición) vive en `#modal-container`.
Flujo completo:

+ `GET` → view devuelve HTML del modal → HTMX inyecta en `#modal-container`
+ `POST` éxito → `HX-Redirect` → reload completo; modal desaparece
+ `POST` error → view re-renderiza modal con errores inline → HTMX reemplaza
  `#modal-container`

El shell Alpine limpia el container al cerrar (delay 200ms):

```javascript
$watch('open', v => {
    if (!v) setTimeout(() => {
        document.getElementById('modal-container').innerHTML = ''
    }, 200)
});
```

Un único template de modal recibe `is_create` y el objeto de contexto para
manejar creación y edición desde el mismo template.

---

### Two-step modal — target interno

**Contexto:** el flujo de emisión de comprobantes en billing tiene dos pasos:
selector de tipo de documento → formulario de renglones.

**Decisión:** el shell Alpine (backdrop, animación, botón close, header
persistente) se carga en el paso 1 y nunca se toca. Solo el contenido interno
hace swap vía HTMX contra un `id` interno:

```html
{# Shell — se carga una vez, no se toca entre steps #}
<div x-data="{ open: false }" ...>
    {# Backdrop + panel #}
    <div id="emit-modal-content">
        {# Step 1 — selector de tipo (carga inicial) #}
        {# Step 2 — formulario (swap HTMX, solo este div) #}
    </div>
</div>
```

URLs del two-step:

``` python
GET  /backoffice/billing/emit/<contract_id>/              → step 1 (shell + step 1)
GET  /backoffice/billing/emit/<contract_id>/<doc_type>/   → step 2 (solo contenido)
POST /backoffice/billing/emit/<contract_id>/<doc_type>/   → procesamiento
```

El botón "volver" en step 2 usa `hx-get` al step 1 con
`hx-target="#emit-modal-content"` — el shell no se toca.

**Por qué no recargar el shell entre pasos:** el backdrop y la animación de
Alpine tienen su propio estado. Recargar el shell entre pasos resetea el estado
de `open`, causando un flash de cierre/apertura.

---

### Archivado two-step — Alpine inline

**Decisión:** para acciones destructivas sin modal separado (ej: archivar un
contacto), usar Alpine inline en el mismo componente:

```html
<div x-data="{ confirming: false }">
    <button x-show="!confirming" @click="confirming = true">Archivar</button>
    <div x-show="confirming" x-cloak class="flex items-center gap-2">
        <span class="text-sm text-on-surface-variant">¿Confirmar?</span>
        <button @click="confirming = false">No</button>
        <button hx-post="..."
                hx-target="#archive-error"
                hx-swap="innerHTML"
                @click="confirming = false">Sí</button>
    </div>
</div>
<div id="archive-error"></div>
```

Los errores de negocio se muestran inline en `#archive-error` vía
`partials/modal_error.html`.

**Cuándo usar vs modal separado:** cuando la acción tiene una sola
confirmación sin inputs adicionales. Si la acción requiere inputs o contexto
(fecha, motivo), usar modal.

---

### Badge contextual — patrón `BadgeContext`

**Decisión:** cuando una card o row necesita un badge computado (no derivable
directamente del modelo), se usa el dataclass `BadgeContext`:

```python
# apps/properties/contexts.py
@dataclass
class BadgeContext:
    text: str
    style: str  # 'success' | 'warning' | 'danger'
```

El badge se resuelve en la view (o en un `_BADGE_MAP` a nivel de módulo). El
template solo decide el color según `badge.style`:

```html
{% if ctx.contextual_badge %}
    {% with badge=ctx.contextual_badge %}
        <span class="...
            {% if badge.style == 'success' %}border border-success-text text-success-text
            {% elif badge.style == 'warning' %}border border-warning-text text-warning-text
            {% elif badge.style == 'danger' %}border border-danger-text text-danger-text
            {% endif %}">{{ badge.text }}</span>
    {% endwith %}
{% endif %}
```

**Filled vs outlined:** los badges de disponibilidad usan estilo filled
(`bg-*`). Los badges de billing usan estilo outlined (solo `border` + `text-*`,
sin fondo). Esto permite distinguir visualmente las dos capas de información en
la misma row sin confundir el estado de la propiedad con el estado de cobro.

---

### Combobox Alpine + HTMX

**Decisión:** para FK de alto volumen en formularios, el combobox tiene esta
arquitectura:

``` python
[Input texto visible]  →  hx-get="/backoffice/<app>/search/?q=..."
                          hx-trigger="input changed delay:300ms"
                          hx-target="#<field>-results"

[Hidden input: <field>_id]  ← el UUID que realmente envía el form
[Dropdown de resultados]    ← partial HTML, no JSON
```

El estado vive en Alpine: `{ id: '', text: '', open: false }`.
La condición `:readonly="field.id !== ''"` bloquea el input una vez elegido,
requiriendo el botón X para limpiar.

**Endpoints dedicados** (`/search/`) son preferibles a reutilizar los endpoints
de lista — responsabilidad única, partial con formato exacto para el dropdown,
sin annotations ni prefetch pesados.

**Auto-fill entre campos:** cuando seleccionar un registro puede pre-rellenar
otro (propiedad → propietario), la lógica vive en la función de selección con
guarda `if (!this.owner.id)` para no sobreescribir campos que el usuario ya
completó. La comunicación usa `window.dispatchEvent`:

```javascript
// En el partial HTMX (onclick nativo):
onclick="window.dispatchEvent(new CustomEvent('property-selected', {
    detail: { id: '{{ prop.pk }}', text: '{{ prop.address_line }}' }
}))"

// En el componente Alpine estático:
@property-selected.window="selectProperty($event.detail.id, $event.detail.text)"
```

Ver también [Alpine sobre contenido HTMX](#alpine-sobre-contenido-htmx--windowdispatchevent).

**Deuda activa:** el auto-fill de propietario al seleccionar propiedad en
`contract_create` no funciona correctamente. Registrado como deuda V1.1.

---

### Builder de renglones Alpine

**Contexto:** el formulario de emisión de comprobantes maneja una lista
dinámica de renglones (alquiler, mora, expensas, ajuste, otros).

**Decisión:** el builder vive en Alpine. Cada renglón tiene `active`, `sign`,
`amount`, `description` y `requires_description`. El total se computa en tiempo
real:

```javascript
get total() {
    return this.lines
        .filter(l => l.active)
        .reduce((sum, l) => sum + (parseFloat(l.amount) || 0) * l.sign, 0);
}
```

Los renglones activos se serializan a JSON en un `<input type="hidden">` antes
del submit. El server reconstruye `ConceptLine` desde ese JSON.

**Signos:** los define la view según `document_type`, inline en los bloques
`if document_type ==` de `billing/views.py`. El template no conoce la lógica
de signos — recibe el array ya armado con el campo `sign` por renglón.

**Trade-off:** el server confía en el JSON serializado por el cliente. La
validación de `ConceptLine` (amount positivo, description requerida) ocurre en
el service, no en Alpine.

---

## Mobile

### Bottom nav — convenciones

**Decisión:** navegación inferior mobile en `base.html`. Patrón:

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

Requiere `viewport-fit=cover` en el meta viewport (ya presente en `base.html`):

```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
```

**`<main>`** usa `pb-28 md:pb-6` para compensar la altura del nav (`h-16` =
64px) más la safe area de iOS (hasta 34px).

**Active state:** `request.resolver_match.app_name`. El bottom nav y el sidebar
comparten la misma variable `app` vía `{% with app=request.resolver_match.app_name %}`.

**Items actuales:** Propiedades / Contactos / Publicaciones / Contratos /
Facturación. Inicio se maneja como `/backoffice/` separado — no ocupa slot.

---

### Precio inline en mobile

**Decisión:** cuando la columna de precio se oculta en mobile
(`hidden md:table-cell`), el precio aparece bajo el título en la celda de
nombre usando `md:hidden`:

```html
<td class="py-3 pl-3 pr-5 md:px-3 min-w-0">
    <p class="text-[13px] md:text-[15px] font-medium text-on-surface truncate">
        {{ property.title|default:property.address_line }}
    </p>
    {% if ctx.display_price %}
    <p class="md:hidden text-xs font-medium text-on-surface tabular-nums mt-0.5">
        ${{ ctx.display_price|floatformat:0 }}
    </p>
    {% endif %}
</td>
```

**Invariante:** el precio nunca desaparece del todo — siempre está visible,
cambia de columna a texto inline según el viewport.

---

## Patrones de view/template

### `BadgeContext` y `PropertyListContext` — dataclasses de presentación

**Decisión:** los context objects de presentación son dataclasses tipados,
resueltos en la view. Viven en `apps/<app>/contexts.py`.

```python
# apps/properties/contexts.py
@dataclass
class BadgeContext:
    text: str
    style: str  # 'success' | 'warning' | 'danger'

@dataclass
class PropertyListContext:
    property: Property
    cover_url: str | None
    display_price: Decimal | None
    contextual_badge: BadgeContext | None = None
```

El template recibe el `PropertyListContext` como `ctx` y accede a
`ctx.property`, `ctx.display_price`, `ctx.contextual_badge`. El modelo no se
accede directamente desde el template para propiedades computadas.

**Por qué dataclass y no dict:** el tipado hace explícito qué fields existen,
evita typos silenciosos en el template, y es introspectable con mypy.

---

### Prefetch building blocks

**Decisión:** los prefetch reutilizables se exportan como funciones desde sus
selectors. El caller los inyecta en el queryset sin conocer los detalles
internos:

```python
# apps/listings/selectors.py
def active_listings_prefetch() -> Prefetch: ...

# apps/contracts/selectors.py
def active_contracts_prefetch() -> Prefetch: ...
```

Uso en `get_property_list`:

```python
qs = Property.objects.prefetch_related(
    active_listings_prefetch(),    # to_attr="active_listings"
    active_contracts_prefetch(),   # to_attr="active_contracts_list"
    Prefetch("media", ...),
)
```

**Justificación:** encapsula el queryset del prefetch (filtros, `select_related`
anidado) en el selector de cada app. Si cambia la definición de "activo" en
listings, solo cambia `listings/selectors.py`.

---

### Precio — fuente de verdad por estado de propiedad

**Decisión:** el precio a mostrar depende del estado de la propiedad:

| Estado | Fuente | Campo |
| -------- | -------- | ------- |
| `rented` | Contrato activo | `active_contract.current_price` |
| Cualquier otro | Listings activos | `listing.price` |

**Motivo:** cuando una propiedad está alquilada, el listing puede estar cerrado
o no existir. El precio contractual actual es `current_price` en
`RentalContract` — se actualiza en cada ajuste de alquiler y es la única
fuente confiable del precio vigente.

---

### Cross-app en views — selectors como única puerta

**Decisión:** las views no importan modelos de otras apps directamente. Todo
acceso cross-app pasa por el selector correspondiente:

```python
# incorrecto
from apps.billing.models import BillingDocument
count = BillingDocument.objects.filter(contract=contract).count()

# correcto
from apps.billing.selectors import get_billing_document_count_for_contract
count = get_billing_document_count_for_contract(contract.id)
```

Esta regla ya existía para services (`design.md`) — se extiende explícitamente
a views.

**Motivo:** las views son consumidoras de datos, igual que los services. Acceso
cross-app directo en views crea el mismo acoplamiento que en un service.

---

### Imports a nivel de módulo

**Decisión:** los imports y las constantes que no cambian entre requests van al
bloque de imports del módulo, nunca dentro de funciones:

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

**Motivo:** los imports locales y los dicts que se recrearían en cada request
son overhead innecesario. Los imports a nivel de módulo se ejecutan una sola
vez al cargar el módulo.

---

### Billing — capacidad transversal sin dashboard propio

**Decisión:** `billing/` no tiene un dashboard de estado que detecte pendientes
para todos los contratos. Los puntos de entrada son contextuales por vertical:

+ `contract_detail` → `RENT_RECEIPT`, `EXPENSE_RECEIPT`, `OWNER_STATEMENT`
+ `deal_detail` → `COMMISSION_RECEIPT` (cuando `deals/` tenga URLs activas)
+ `contact_detail` → `OWNER_STATEMENT` (futuro)

La vista global `/backoffice/billing/` es historial de consulta — todos los
comprobantes emitidos, sin límite, sin detección de pendientes. Organizada por
dirección del dinero: **Cobros** (lo que paga el inquilino) / **Pagos** (lo
que recibe el propietario).

**Justificación:** no existe una señal determinista en el sistema para "este
contrato tiene un recibo pendiente este mes". El socio conoce sus contratos —
la UI debe facilitarle la emisión desde el detalle del contrato, no deducir la
intención.

---

## Convenciones de código

### `app_name` — obligatorio para navegación

**Decisión:** toda app con templates que aparezca en la navegación (sidebar o
bottom nav) debe declarar `app_name` en su `urls.py`. Sin esto,
`request.resolver_match.app_name` devuelve `''` y el active state nunca
funciona.

```python
# primer línea de urls.py de la app
app_name = "contacts"
```

Consecuencia en todos los `reverse()` de la app: usar el namespace:

```python
reverse("contacts:contact-list")   # correcto
reverse("contact-list")            # incorrecto si app_name está declarado
```

**Estado al cierre de sesión 5 → corregido:**

| App | `app_name` |
| ----- | ------------ |
| `properties` | ✅ `"properties"` |
| `contacts` | ✅ `"contacts"` |
| `contracts` | ✅ `"contracts"` — ~~era deuda de sesión 4~~ RESUELTO |
| `billing` | ✅ `"billing"` — ~~era deuda de sesión 5~~ RESUELTO |
| `listings` | pendiente — sin `urls.py` activo aún |
| `deals` | pendiente — sin `urls.py` activo aún |

---

### Orden de `except` — específica primero

**Regla que no se negocia:** la excepción más específica (hija) siempre va
primero. Una clase hija capturada por el `except` de la clase padre nunca
llega al bloque correcto.

```python
# CORRECTO — específica primero
except ContractDateConflict as e:      # hija
    ...
except ContractValidationError as e:   # padre
    ...

# INCORRECTO — la hija nunca se ejecuta
except ContractValidationError as e:   # padre captura todo
    ...
except ContractDateConflict as e:      # inalcanzable
    ...
```

---

### `name=` en `urls.py` — error silencioso de alto impacto

**Contexto:** un `name=` incorrecto hace que `{% url 'app:name' %}` resuelva
al path equivocado sin ningún error de template. El bug solo se manifiesta en
runtime como comportamiento inesperado.

```python
# Ejemplo del bug: name="detail" en la URL de terminate
path("<uuid:contract_id>/terminate/", views.contract_terminate, name="detail")
# Efecto: todos los {% url 'contracts:detail' %} resuelven a /terminate/
```

**Convención:** verificar `name=` al agregar cualquier URL nueva,
especialmente en copypaste de una línea adyacente con path similar.

---

### Alpine sobre contenido HTMX — `window.dispatchEvent`

**Problema:** `x-on:click` en elementos insertados por HTMX no es garantizado.
Alpine inicializa su scope al cargar; el partial HTMX llega después y Alpine no
re-evalúa los listeners de los elementos nuevos.

**Solución robusta:** `onclick` nativo en el partial + `window.dispatchEvent`

+ escucha con `@evento.window` en el componente Alpine estático:

```javascript
// En el partial HTMX (onclick nativo — siempre funciona):
onclick="window.dispatchEvent(new CustomEvent('property-selected', {
    detail: { id: '{{ prop.pk }}', text: '{{ prop.address_line }}' }
}))"

// En el componente Alpine estático (siempre tiene el scope):
@property-selected.window="selectProperty($event.detail.id, $event.detail.text)"
```

El componente Alpine estático siempre tiene control total sobre su scope.
El partial solo dispara el evento — no necesita scope Alpine propio.

---

### Acciones destructivas — form nativo sobre HTMX

**Decisión:** las acciones destructivas (rescindir, terminar contrato,
archivar con redirect) usan `<form method="post">` nativo en lugar de `hx-post`.

```html
<form method="post" action="{% url 'contracts:terminate' contract.pk %}">
    {% csrf_token %}
    <button type="submit">Sí</button>
</form>
```

La view devuelve `redirect()` estándar en lugar de `HX-Redirect`.

**Motivo:** en layouts con sidebar renderizado dos veces (mobile + desktop),
`hx-target` puede quedar duplicado en el DOM, generando comportamiento
inconsistente en HTMX (dos targets reciben el swap). El form nativo evita
cualquier dependencia de IDs únicos en el DOM.

**Trade-off:** la acción causa una recarga completa de página. Para acciones
destructivas con confirmación, esto es aceptable — el usuario ya pasó por el
two-step de confirmación.

---

## Infraestructura de templates

### Middleware de backoffice — `BackofficeLoginRequiredMiddleware`

**Decisión:** en lugar de decorar cada view con `@login_required`, el acceso
al backoffice se controla vía middleware transversal:

```python
# config/middleware.py
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

Registrado en `settings.py` como
`"config.middleware.BackofficeLoginRequiredMiddleware"`.

**Consecuencia en services:** `actor=request.user` es siempre un `User` válido
dentro del backoffice — el middleware garantiza autenticación antes de llegar
a cualquier view. No es necesario chequear `request.user.is_authenticated` en
ninguna view del backoffice.

**Justificación:** un único punto de control. Si cambia la lógica de acceso
(ej: agregar 2FA para rutas específicas), se modifica el middleware, no
múltiples decoradores distribuidos.

---

### Containers globales en `base.html`

**Decisión:** `base.html` declara dos containers globales con posicionamiento
y propósitos distintos:

**`#slide-over-container`** — al final del content area (dentro del div
`.flex.flex-col.flex-1`), antes del cierre de ese div:

```html
<main id="main-content" class="...">
    {% block content %}{% endblock %}
</main>
<div id="slide-over-container"></div>
```

El slide-over usa `absolute inset-0` — se posiciona sobre el content area
solamente. El sidebar desktop permanece visible.

**`#modal-container`** — al final del `<body>`, antes de los scripts:

```html
<div id="modal-container"></div>

{# ── Scripts ── #}
<script src="..." defer></script>
```

El modal usa `fixed inset-0` — cubre la pantalla completa incluyendo el
sidebar. La posición antes de los scripts es coherente con el principio de que
el DOM está listo antes de que los scripts (todos `defer`) lo evalúen.

**CSRF global:** el `<body>` incluye `hx-headers` con el CSRF token:

```html
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
```

Todos los requests HTMX desde cualquier template heredado incluyen el token
automáticamente — no es necesario agregarlo en cada `hx-post`.

---

### `modal_error.html` — partial compartido

**Decisión:** `partials/modal_error.html` vive en `templates/partials/` (no
dentro de ninguna app). Es el canal único de error de negocio vía HTMX:

```html
<div class="p-4 rounded-md bg-danger-bg border border-danger-text/20">
    <p class="text-sm font-medium text-danger-text">{{ error }}</p>
</div>
```

Cualquier view que devuelva un error de negocio vía HTMX usa este partial. El
target varía por contexto: el interior del modal, un `#archive-error` inline, etc.

**Consecuencia para las excepciones:** el mensaje de error (`str(e)`) debe
ser legible para el usuario final. Las excepciones de negocio deben tener
mensajes en español, no mensajes técnicos.

---

## Deudas técnicas conocidas

### Auto-fill de propietario en `contract_create`

**Estado:** deuda de comportamiento activa — V1.1.

El auto-fill de propietario al seleccionar una propiedad en
`contracts/contract_create.html` no funciona correctamente. El mecanismo de
`window.dispatchEvent` está implementado pero `selectProperty()` no completa
el fill del owner field.

---

### `COMMISSION_RECEIPT` excluido de `_COBROS_TYPES`

**Estado:** SALDADA en S5.

`COMMISSION_RECEIPT` integra `_COBROS_TYPES` sin condición de `deal_type`:
toda comisión es un cobro. La deuda no esperó al punto de emisión en `deals/`
porque el negocio la volvió cara antes (administración activa de alquileres
con comisiones invisibles). Rationale completo en `s5-billing-operativo.md`.

---

### Compartir / descargar comprobante

**Estado:** descargar SALDADA en S5; compartir pendiente — V1.1+.

Descarga operativa: `GET /backoffice/billing/<uuid>/pdf/` (WeasyPrint,
on-demand, sin persistencia), desde el detail modal y por fila en la tabla
desktop de cobros/pagos (mobile deliberadamente excluido: la card completa es
target de `hx-get`, el camino es card → modal → descarga).

Compartir, forma futura definida en S5: persistencia del PDF en R2 (bucket
privado, key en un campo `pdf_r2_key` nuevo — `pdf_url` se eliminó por estar
mal tipado para este futuro) + URL pública con token firmado fuera de
`/backoffice/` + envío por mail/WhatsApp como task en background. Cae en la
ola que estrena Celery; no hay infra de email en el repo.

---

### `contact_detail_panel.html` — stub pendiente

**Estado:** pendiente de implementación cuando exista un caso de uso activo.

El partial existe como stub (solo `{% comment %}`). Su propósito es cargar el
detalle de un contacto en `#main-content` desde otras vistas vía HTMX. El
flujo actual siempre navega a la full page `contact_detail.html`.

---

### Contact restore — sin UI

**Estado:** diferido hasta que exista una vista de contactos archivados.

No hay UI para restaurar contactos archivados. El backend soporta la
restauración a nivel de servicio, pero no hay endpoint ni template para el
flujo.

---

### Thumbnail mobile — shadow pendiente de verificación

**Estado:** pendiente de verificación en dispositivo real.

La columna de thumbnail en `property_list` usa
`shadow-[inset_-4px_0_6px_rgba(0,11,32,0.06)]`. El comportamiento de este
shadow puede no ser idéntico en todos los browsers mobile.
