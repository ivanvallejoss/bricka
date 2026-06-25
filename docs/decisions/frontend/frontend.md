# Decisiones de Frontend — Bricka CRM

Convenciones técnicas y registro de decisiones de la capa de templates.
Complementa `design.md` (decisiones de backend) y `audit.md`.

Este documento tiene dos partes con ciclos de vida distintos:

- **Parte 1 — Convenciones activas.** Las reglas que se siguen al escribir
  templates, views y código frontend, agrupadas por dominio. Enunciado terso
  + enlace al registro completo. Es la sección de consulta diaria.
- **Parte 2 — Registro de decisiones.** El contexto, la justificación y el
  trade-off de cada decisión. Formato ADR, append-only. Se lee una vez para
  entender el *por qué*; rara vez después.


---

# Parte 1 — Convenciones activas

## Stack y tooling

- **Django Templates** — capa de renderizado.
- **HTMX 2.0.4** — interactividad sin SPA; integración vía `django-htmx`
  (`request.htmx`). → [ADR](#stack-de-frontend--librerías-y-versiones)
- **Alpine.js 3.14.9** — estado local en componentes; carga `defer`
  obligatorio. → [ADR](#stack-de-frontend--librerías-y-versiones)
- **Tailwind v4** — utility-first CSS; compilado con `bun run dev` (dev) y
  `bun run build` (prod). → [ADR](#stack-de-frontend--librerías-y-versiones)
- **Flowbite v3** — componentes UI sobre Tailwind v4 (CDN v3.1.2).
  → [ADR](#stack-de-frontend--librerías-y-versiones)
- **Fuente de verdad CSS:** `static/src/input.css`. Nunca asumir valores de
  tokens sin verificarla.

## Tokens y color

- **Tokens semánticos:** usar siempre el nombre semántico, nunca un valor hex
  directo. → [ADR](#tokens-semánticos-de-color)
- **Tabla de asignación fija:**

  | Estado | Token | Uso |
  |--------|-------|-----|
  | Disponible | `success-bg / success-text` | Propiedad disponible |
  | Alquilada | `alquiler-bg / alquiler-text` | Propiedad con contrato activo |
  | Vendida | `venta-bg / venta-text` | Propiedad vendida |
  | No disponible | `surface-container / on-surface-variant` | Sin actividad |
  | Pago (billing) | `success-bg / success-text` | Comprobante emitido |
  | Pendiente (billing) | `warning-bg / warning-text` | Sin comprobante, en plazo |
  | En mora (billing) | `danger-bg / danger-text` | Sin comprobante, fuera de plazo |

- **`warning-bg/text` está reservado para PENDING de billing.** "Alquilada"
  usa `alquiler-bg/text` (azul). No intercambiar.
  → [ADR](#tokens-semánticos-de-color)
- **`PropertyStatus` en templates: siempre comparar en minúsculas.**
  `{% if property.status == 'rented' %}` — nunca `'RENTED'`.
  → [ADR](#propertystatus--comparaciones-en-minúsculas)

## Patrones HTMX

- **Full page vs partial:** cada view soporta los dos modos según
  `request.htmx`. → [ADR](#full-page-vs-partial--patrón-base)
- **Acción exitosa (POST que redirige):** `HttpResponse(status=204)` +
  `HX-Redirect`. → [ADR](#respuesta-de-acción-exitosa--http-204--hx-redirect)
- **Error de negocio:** `render(request, "partials/modal_error.html", {"error": str(e)})`.
  El partial reemplaza el contenido del modal sin cerrarlo.
  → [ADR](#respuesta-de-error-de-negocio)
- **`hx-trigger="load"`** en `property_detail.html` y cualquier página donde
  el scroll ocurre dentro de `<main class="overflow-y-auto">`.
  → [ADR](#hx-trigger--load-vs-revealed)
- **`hx-trigger="revealed"`** en el slide-over y contenedores con scroll
  propio donde los elementos realmente quedan fuera del viewport visible.
  → [ADR](#hx-trigger--load-vs-revealed)
- **OOB elements al final del partial** cuando el target del swap es un
  elemento de tabla (`<tbody>`, `<tr>`). Nunca al principio.
  → [ADR](#oob-elements--posición-en-partials-de-tabla)
- **Lista multi-sección:** cuando una vertical tiene estados cualitativamente
  distintos, dividir en secciones con `hx-get` y `hx-trigger` propios en
  lugar de un único listado con pills de filtro.
  → [ADR](#lista-multi-sección-con-scroll-independiente)

## Layout y spacing

- **Dos columnas desktop (`lg+`) / single-column mobile.** El sidebar se
  renderiza dos veces en el HTML (`lg:hidden` + `hidden lg:block`).
  → [ADR](#dos-columnas-desktop--sidebar-renderizado-dos-veces)
- **Consecuencia del doble render:** no poner en el sidebar contenido que
  deba aparecer después de la columna principal en mobile — el sidebar
  siempre llega primero en el DOM.
  → [ADR](#dos-columnas-desktop--sidebar-renderizado-dos-veces)
- **Separación entre cards y elementos apilados principales:** usar
  `flex flex-col gap-*`. `space-y-*` es aceptable en sub-componentes
  internos acotados. → [ADR](#separación-entre-elementos--flex-gap-sobre-space-y)
- **Tablas con swap HTMX:** usar siempre `table-fixed` con `<colgroup>`
  explícito. → [ADR](#tablas-htmx--table-fixed--colgroup-obligatorio)
- **Columnas ocultas en mobile:** `hidden md:table-cell` en `<th>` y `<td>`;
  `w-0 md:w-XX` en la `<col>` correspondiente.
  → [ADR](#tablas-htmx--table-fixed--colgroup-obligatorio)
- **Dual layout en tablas anchas:** cards (`md:hidden`) + tabla
  (`hidden md:table`). Aplicar cuando la tabla tiene más de 3 columnas y
  alguna debe ocultarse en mobile.
  → [ADR](#dual-layout--cards-mobile--tabla-desktop)

## Componentes

- **Slide-over:** vive en `#slide-over-container` (al final del content area
  en `base.html`). Se carga vía HTMX con `hx-swap="innerHTML"`. Shell Alpine
  controla animación y limpia el container al cerrar (delay 200ms).
  → [ADR](#slide-over--arquitectura-y-posicionamiento)
- **Slide-over en mobile:** el click en una row navega directamente a
  `property_detail` — sin slide-over. El slide-over es desktop-only.
  → [ADR](#slide-over--arquitectura-y-posicionamiento)
- **Secciones lazy del slide-over:** usan `hx-trigger="revealed"` — el panel
  es más pequeño que el viewport, por lo que el observer funciona
  correctamente. → [ADR](#slide-over--arquitectura-y-posicionamiento)
- **Modal simple:** vive en `#modal-container` (antes de scripts en
  `base.html`). Shell Alpine con backdrop, animación y auto-limpieza del
  container al cerrar (delay 200ms).
  → [ADR](#modal-simple--shell-alpine--limpieza-automática)
- **Two-step modal:** el shell Alpine (backdrop, animación, close) se carga
  una vez y no se recarga entre pasos. Solo el contenido interno hace swap
  vía HTMX contra un `id` interno (`#emit-modal-content`).
  → [ADR](#two-step-modal--target-interno)
- **Archivado two-step (sin modal separado):** `x-data="{ confirming: false }"` +
  `x-show` inline en el mismo componente.
  → [ADR](#archivado-two-step--alpine-inline)
- **Badge contextual:** resolver el badge en la view vía `BadgeContext(text,
  style)`. El template solo elige el color según `badge.style`.
  → [ADR](#badge-contextual--patrón-badgecontext)
- **Filled vs outlined:** badges de disponibilidad usan `bg-*` (filled);
  badges de billing usan solo `border` + `text-*` (outlined). Permite
  distinguir visualmente las dos capas de información en la misma row.
  → [ADR](#badge-contextual--patrón-badgecontext)
- **Combobox Alpine + HTMX:** input de texto visible + input hidden con el
  UUID; el input se bloquea (`:readonly`) al seleccionar; botón X para
  limpiar. Endpoint `/search/` dedicado, no reutilizar endpoints de lista.
  → [ADR](#combobox-alpine--htmx)
- **Auto-fill entre campos del combobox:** cuando seleccionar un registro
  puede pre-rellenar otro, usar `onclick` nativo + `window.dispatchEvent` en
  el partial y `@evento.window` en el componente Alpine estático.
  → [ADR](#combobox-alpine--htmx)
- **Builder de renglones Alpine:** los signos de cada renglón los define la
  view según `document_type`. El template no conoce la lógica de signos. Los
  renglones activos se serializan a JSON en un `<input type="hidden">` antes
  del submit. → [ADR](#builder-de-renglones-alpine)

## Mobile

- **Bottom nav:** `md:hidden`, `fixed bottom-0`, `z-30`, `h-16`,
  `grid-cols-5`, máximo 5 items (icono 17px + label `text-[10px]`).
  → [ADR](#bottom-nav--convenciones)
- **`pb-safe`** es una custom utility en `input.css` que aplica
  `env(safe-area-inset-bottom, 0px)`.
  → [ADR](#bottom-nav--convenciones)
- **`<meta viewport>`** debe incluir `viewport-fit=cover` para que `pb-safe`
  funcione en iOS. → [ADR](#bottom-nav--convenciones)
- **`<main>`** usa `pb-28 md:pb-6` para compensar la altura del nav (64px)
  más la safe area de iOS. → [ADR](#bottom-nav--convenciones)
- **Active state del bottom nav:** `request.resolver_match.app_name`.
  Requiere que la app tenga `app_name` declarado.
  → [ADR](#bottom-nav--convenciones)
- **Precio inline en mobile:** cuando la columna de precio se oculta en
  mobile (`hidden md:table-cell`), el precio aparece bajo el título de la
  celda de nombre con `md:hidden`. El precio nunca desaparece del todo.
  → [ADR](#precio-inline-en-mobile)

## Patrones de view/template

- **`BadgeContext`** (`text`, `style`) y **`PropertyListContext`**
  (`property`, `cover_url`, `display_price`, `contextual_badge`): dataclasses
  de presentación resueltos en la view, nunca en el template.
  → [ADR](#badgecontext-y-propertylistcontext--dataclasses-de-presentación)
- **Prefetch building blocks:** los prefetch reutilizables se exportan como
  funciones desde sus selectors (`active_listings_prefetch()`,
  `active_contracts_prefetch()`). El caller los inyecta sin conocer los
  detalles internos. → [ADR](#prefetch-building-blocks)
- **Precio — fuente de verdad:** `rented` → `active_contract.current_price`;
  cualquier otro estado → `listing.price`.
  → [ADR](#precio--fuente-de-verdad-por-estado-de-propiedad)
- **Cross-app en views:** las views no importan modelos de otras apps
  directamente. Todo acceso cross-app pasa por el selector correspondiente.
  → [ADR](#cross-app-en-views--selectors-como-única-puerta)
- **Imports a nivel de módulo:** los imports y las constantes que no cambian
  entre requests van al bloque de módulo, nunca dentro de funciones.
  → [ADR](#imports-a-nivel-de-módulo)
- **Billing — capacidad transversal:** `billing/` no tiene dashboard de
  estado propio. Sus puntos de entrada son contextuales por vertical
  (`contract_detail`, `deal_detail`, `contact_detail`). La vista global
  `/backoffice/billing/` es historial de consulta, organizada por dirección
  del dinero (Cobros / Pagos).
  → [ADR](#billing--capacidad-transversal-sin-dashboard-propio)

## Convenciones de código

- **`app_name` obligatorio** para toda app con templates que aparezca en la
  navegación (sidebar o bottom nav). Sin esto, `request.resolver_match.app_name`
  devuelve `''` y el active state nunca funciona.
  → [ADR](#app_name--obligatorio-para-navegación)
- **`reverse()` con namespace** cuando la app tiene `app_name` declarado:
  `reverse("contacts:contact-list")`, nunca `reverse("contact-list")`.
  → [ADR](#app_name--obligatorio-para-navegación)
- **Orden de `except`:** la excepción más específica (hija) siempre primero.
  → [ADR](#orden-de-except--específica-primero)
- **`name=` en `urls.py`:** verificar al agregar cualquier URL nueva,
  especialmente en copypaste de una línea adyacente. Un `name=` incorrecto
  falla silenciosamente en runtime.
  → [ADR](#name-en-urlspy--error-silencioso-de-alto-impacto)
- **Alpine sobre contenido cargado por HTMX:** usar `onclick` nativo +
  `window.dispatchEvent` en el partial; `@evento.window` en el componente
  Alpine estático. No depender de `x-on:click` en elementos insertados por
  HTMX. → [ADR](#alpine-sobre-contenido-htmx--windowdispatchevent)
- **Acciones destructivas:** `<form method="post">` nativo + `redirect()`
  estándar en la view. No usar `hx-post` para acciones que deben rescindir
  o archivar. → [ADR](#acciones-destructivas--form-nativo-sobre-htmx)

## Infraestructura de templates

- **`BackofficeLoginRequiredMiddleware`** controla el acceso a todo
  `/backoffice/` sin decorar cada view. Consecuencia: `actor=request.user`
  es siempre un `User` válido dentro del backoffice.
  → [ADR](#middleware-de-backoffice--backofficeloginrequiredmiddleware)
- **`#slide-over-container`:** al final del content area (dentro del div
  `.flex-1` del layout), antes del cierre de ese div. El slide-over usa
  `absolute inset-0` — se posiciona sobre el área de contenido, no sobre
  el sidebar. → [ADR](#containers-globales-en-basehtml)
- **`#modal-container`:** al final del `<body>`, antes de los scripts. El
  modal usa `fixed inset-0` — cubre la pantalla completa.
  → [ADR](#containers-globales-en-basehtml)
- **CSRF global:** `<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>`.
  Todos los requests HTMX lo incluyen automáticamente.
  → [ADR](#containers-globales-en-basehtml)
- **`partials/modal_error.html`** vive en `templates/partials/` (no dentro
  de ninguna app). Es el único canal de error de negocio vía HTMX.
  → [ADR](#modal_errorhtml--partial-compartido)

---
