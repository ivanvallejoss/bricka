# S2 — Diseño UI de creación/edición de properties (paquete de decisiones)

**Producido en ventana de planificación: 2026-07-15. S2 NO está
cerrada — este documento la pone en marcha.** Contiene las decisiones
tomadas y acordadas en planificación; la ventana S2 que lo ejecute:
(1) re-verifica los hallazgos de §0 contra `main`, (2) valida cada
decisión contra el código real y frena ante cualquier contradicción,
(3) cierra los detalles finos que la ejecución destape, y (4)
commitea la versión final en `docs/decisions/roadmap/` — recién ese
commit salda b8 y convierte este documento en la fuente de verdad de
S3. Sin código de producción en ningún punto de S2. Referencias vivas: `frontend.md`
(convenciones de UI), `last-adr.md` (contratos de properties),
`S1-r2-media.md` (storage y deuda de portada), `S8-auth.md` (sesión
expirada / rama HTMX).

---

## 0. Verificación de arranque — hallazgos contra `main`

- **`storage.py` no tiene generador de presigned PUT** (solo uploads
  server-side y presigned GET de documents). El CORS PUT dev sí está
  (`infra.md`). "Infra lista" era cierto a nivel bucket, no a nivel
  código → función nueva especificada en §10.
- **`create_listing` no tiene ningún consumidor de UI** (solo seed y
  operations). Sin superficie de creación/publicación de listings, en
  producción no hay precios ni filtros venta/alquiler. Agujero sin
  nombre en el roadmap — **entra al alcance de esta espec** (fase 4
  del wizard + sección de la edición).
- **`Property.location` no tiene consumidor** (solo el seed lo
  puebla). Habilita el mínimo de la Decisión 4 sin presión.
- **`roadmap.md` en `main` no tiene la enmienda de cierre de S1**
  (`S1-r2-media.md` sí la marca). Lag documental — commitear la
  enmienda junto con este doc.
- **Enmienda de alcance decidida en sesión**: los valores nuevos del
  gate de publicación (≥5 fotos, descripción ≥150 caracteres) se
  deciden acá y se **especifican como cambio de services para S3**.
  Motivo: la UI necesita exactamente esos números (contadores,
  checklist del gate); decidirlos en otra ventana garantiza
  divergencia UI/gate. El resto del gate y el orquestador siguen
  intocados.

---

## 1. Decisión 1 — Flujo de creación: wizard de 4 fases

**DECIDIDA.** Creación como wizard de página propia, dividido por
coherencia de campos. **Cada "Siguiente" persiste** (fase 1 =
`create_property`; fases siguientes = `update_property` / acciones
directas). Navegar hacia atrás re-renderiza desde la DB — no existe
estado en memoria que perder. Fases 2–4 skippeables con "Guardar y
salir" → aterriza en el detail (la propiedad ya es operable por
diseño del backend).

Descartadas: modal (las fotos no caben en el patrón modal existente
— una línea de forms cortos) · form único con submit final (bloquea
las fotos: `build_media_key` exige `property_id`) · creación mínima

- completar desde el detail (salto de contexto en la operación
diaria del socio).

### Fases

| Fase | Campos | Mecánica |
| --- | --- | --- |
| **1 — Identificación** | `property_type`, `address_line`, `city`, `province`, `neighborhood`, **toggle `is_external` + `agency_name`** | Al confirmar corre `create_property` → nace el UUID. `is_external` es acá o nunca: el toggle está prohibido en `update_property` |
| **2 — Detalle** | `title` (helper de título, §5), `description` (contador /150), `area_m2`, `bedrooms`, `bathrooms`, `parking_spaces`, `year_built`, `youtube_video_url`, `owner_contact` (combobox — patrón existente), features (§5), bloque externas si `is_external` (§6), bloque location (§4) | `update_property` mandando la fase completa; el resto de campos viaja UNSET |
| **3 — Fotos** | Upload, orden, portada, contador de gate | §3 completo |
| **4 — Operación** *(opcional)* | Venta / alquiler / ambas + precio + moneda + `price_min_acceptable` → `create_listing` (DRAFT) + acción "Publicar" | §8 de edición comparte la sección. `price_min_acceptable` entra: superficie operativa (regla de §6) |

### URLs

- `properties/new/` → fase 1 (full page).
- Post-creación: `properties/<uuid>/new/detalle/`, `.../new/fotos/`,
  `.../new/operacion/` — URL por fase permite retomar un wizard
  abandonado desde donde quedó.
- Patrón full-page vs partial estándar de `frontend.md` en cada fase.

### El gate como checklist navegable

`ListingPublicationRequirementsError.missing` trae códigos
estructurados. La UI los traduce a ítems con deep link a su
fase/sección:

    No se puede publicar todavía:
    ✗ Fotos: 3 de 5 mínimas          → Ir a Fotos
    ✗ Descripción: 87/150 caracteres → Ir a Detalle

**Esta presentación es única para todo rechazo del gate** — publicar
(fase 4 / edición), reactivar (§8), y re-mandatar el día que tenga
UI. S3 la implementa una vez como partial compartido.

---

## 2. Decisión 2 — Edición: página única con secciones apiladas

**DECIDIDA.** `properties/<uuid>/edit/`, página propia. Estructura
mixta:

- **Form escalar** (identificación + detalle, incluida la sección de
  features): un solo "Guardar" → `update_property` mandando todo
  (caso "el form manda todo — reemplazo total desde su perspectiva"
  que `last-adr.md` ya contempla; UNSET casi no aparece desde esta
  puerta y sigue siendo vital para el wizard y los callers
  programáticos).
- **Secciones de acción inmediata** (no esperan submit): fotos (§3),
  operación (§8-listing), fuente externa (§6, form propio →
  `update_external_source`), location (§4).

**Regla de implementación para S3 (restricción, no sugerencia):**
*cada sección es un partial autocontenido* — recibe `property` + su
contexto propio, postea a su endpoint propio, no asume nada del
shell (layout padre, orden, vecinos). La página de edición es un
arreglo de secciones, no un form monolítico con secciones adentro.
Esto habilita la evolución nombrada de abajo a costo de template.

**Evolución nombrada, condicionada a S6:** re-componer estas mismas
secciones sobre el layout comercial del detail cuando S6 lo defina
(re-layout = barato por la regla de partials). La pregunta "¿el
detail comercial convive con la página de edición operativa o la
absorbe?" queda como **insumo de S6**, no se decide acá. Inline
editing verdadero (campo por campo sobre la vista) NO queda
habilitado gratis: exige ADR de interacción nuevo.

Descartadas: edición inline sobre el detail (acoplada a S6 que va a
redefinir ese layout; patrón inexistente en `frontend.md`; contrato
UNSET borroso con guardado por campo) · wizard para edición (crear y
editar comparten datos pero no ritmo: guiado/secuencial vs
directo/puntual — se comparten componentes, no estructura).

---

## 3. Decisión 3 — Upload de fotos

**DECIDIDA.**

### Transporte: presigned PUT desde el browser

Descartada la vía servidor: doble tránsito (browser→Django→R2) y
workers bloqueados durante subidas multi-foto en un deploy chico de
Hetzner. Con presigned, Django solo firma y registra metadata.

### Flujo por archivo (cada foto es una transacción independiente)

1. **Validación local** (browser): MIME por type, dimensiones
   ≥500×500 leyendo el archivo, resize si aplica (§7).
2. **Pedir firma** a Django: el server **re-valida MIME y tamaño
   declarado** (nunca confiar solo en el cliente), genera la key con
   `build_media_key`, valida el techo de cantidad, devuelve key +
   URL firmada con `ContentType` fijado en la firma (el MIME validado
   es el único que R2 acepta).
3. **PUT directo a R2.**
4. **Confirmación** a Django: el endpoint hace **`head_object`
   contra R2** (`public_media_exists`, §10) antes de llamar
   `upload_property_media` — la precondición del service ("r2_key ya
   subido") se honra verificando, no confiando. Si el objeto no
   está, la confirmación se rechaza y la foto se marca fallida.

La foto que no confirmó no existe para el sistema. El objeto huérfano
en R2 es barato — limpieza en §11 (deuda nueva).

### Validaciones — valores cerrados

| Regla | Valor | Dónde se aplica |
| --- | --- | --- |
| MIME | `image/jpeg`, `image/png`, `image/webp` | Local + firma (server) |
| Dimensión mínima | 500×500 px | Local, **sobre el original** |
| Peso máximo | 10 MB | Local + firma, **post-resize** (una foto de 15 MB que el resize deja en 2 MB, pasa) |
| Cantidad máxima | **35 por propiedad** | Firma + confirmación (server) |

Restricción heredada anotada: 35 debe mantenerse ≤ al límite del
portal más restrictivo — **S12 lo verifica contra ZonaProp**.

### Orden

Default: orden de subida. Reorden: **drag & drop en desktop, botones
subir/bajar en mobile** (drag táctil frágil para el socio). Persiste
vía endpoint de reorden → `reorder_property_media` (§10).

### Portada

- La cover es `is_cover=True`, independiente del orden. Default:
  primera subida (comportamiento actual del service, intacto).
- **Selección manual**: control "hacer portada" sobre cualquier foto
  → `set_cover_media` (service existente, atómico — no se crea nada).
- **Borrar la cover promueve a la primera por `order`** — cambio en
  `delete_property_media` (§10). Cierra la deuda de S1; **el test-pin
  del comportamiento actual se reemplaza deliberadamente**. Descartado
  el estado "con fotos y sin cover": inconsistencia sin valor
  operativo (lista sin imagen, detail con fallback) que obligaba a
  tocar dos templates para representar un estado que nadie quiere.
- Borrado de cualquier foto: **R2 primero, DB después** (orden ya
  documentado como responsabilidad de la view).

### Errores y estados

- **Subida parcial (3 de 5)**: las confirmadas existen; las fallidas
  quedan marcadas con **reintento individual**. Sin todo-o-nada.
- **Dos capas visuales en la sección, no fundir**: el contador de
  gate (**"N/5 mínimo publicable · máx 35"**) es permanente; el
  estado por archivo (spinner → tick/cruz + reintentar) es efímero,
  vive en la lista durante la subida.
- **Sesión expirada a mitad de carga**: rama HTMX de S8 (200 +
  `HX-Redirect` al login). Las fotos confirmadas antes del
  vencimiento persisten. Comportamiento ya definido — solo se
  referencia.

---

## 4. Decisión 4 — Location: pin sobre mapa, mínimo real

**DECIDIDA.** Vive como **bloque dentro de la fase 2 / sección de la
edición** — no es fase propia (necesita la dirección persistida y es
opcional; `PointField` sigue nullable).

- **Mecanismo**: Leaflet + tiles OpenStreetMap + geocoding Nominatim.
  Gratis, sin API key. **Leaflet es librería nueva del stack** — S3
  deja el registro en `frontend.md` al implementar.
- **Operación**: botón "Ubicar en mapa" (no geocoding automático por
  tecleo) → geocodifica `address_line + city + province` **una vez**,
  centra el mapa, cae un pin arrastrable → "Confirmar ubicación"
  persiste el Point vía el `update_property` de la sección.
- **Proxy propio obligatorio**: el geocode pasa por
  `/geo/geocode/` (endpoint nuestro), nunca fetch directo del
  browser a Nominatim — su política exige User-Agent identificable;
  el proxy centraliza rate limit (1 req/s sobra para single-tenant)
  y un cache simple futuro.
- **Bordes**: Nominatim sin resultado o caído → mapa centrado en un
  default por ciudad (configurable) y pin manual, o saltear. **Nunca
  bloquea** el guardado del resto. Sin confirmación → `location`
  null, cero consecuencias (verificado: nada lo consume).
- **Restricción heredada**: si S12 descubre que ZonaProp exige
  coordenadas, el gate podría sumar `location` — decisión de S12.

Descartadas: lat/lng manual (socio no técnico, descartado de
entrada) · Google Geocoding (costo + API key sin necesidad
demostrada) · diferir del todo (el mecanismo es barato y la
dirección ya cargada lo alimenta gratis).

---

## 5. Decisión 5 — Features en el form

**DECIDIDA.** Checkboxes agrupados por las 4 categorías existentes
(`Feature.category` — el consumidor para el que nació), **siempre
visibles, sin colapso**. Rationale: en un form de carga el estado de
los checkboxes es información — el socio audita su carga y detecta
missed-clicks mirando; colapsar esconde exactamente eso. El costo de
mostrar todo es scroll (barato); el de colapsar, un error de datos
silencioso.

- Orden de categorías: Características generales → Características →
  Servicios → Ambientes. Dentro: alfabético (`Meta.ordering` — la UI
  no ordena nada).
- **Grid responsive: 3 columnas desktop / 2 mobile.**
- **Contador por categoría en el header** ("Servicios · 2
  seleccionadas").
- Sin búsqueda, sin tocar el modelo. Vocabulario por tipo sigue V2
  (b7).
- Mapeo al service: la sección manda **la lista completa de slugs
  marcados** (reemplazo total; `[]` vacía; nunca UNSET desde esta
  puerta).

**Consejo de título** (misma fase): helper text bajo el campo con
ejemplo concreto — *"Buscá que sea googleable por sus
características: «Depto 3 amb con balcón en Villa del Parque», no
«Propiedad Rivadavia»"*. Es consejo, no constraint.

---

## 6. Decisión 6 — Edición de externas

**DECIDIDA.** Hoy una externa se crea completa y no se puede
corregir nunca (los campos están fuera de `update_property` a
propósito). Esta decisión lo salda:

- **Creación**: fase 1 captura toggle + `agency_name` (mínimo del
  service). `source_url` y `agreed_commission_percent` van al bloque
  de externas de fase 2 — son completitud, no identificación.
- **Edición**: sección "Fuente externa" renderizada **solo si
  `is_external`**. Sin toggle visible ni deshabilitado: la
  invariante se protege por ausencia, igual que en la firma.
- **`agreed_commission_percent` entra al form**: la página de
  edición es superficie operativa, nadie la comparte. **Regla para
  S6 y sucesoras: la comisión vive en superficies operativas, nunca
  en superficies mostrables** (el motivo de `last-adr.md` para
  excluirla del detail sigue vigente allá).

Service nuevo (especificado en §10): `update_external_source`.
Descartado ensanchar `update_property`: otra entidad, otro ciclo de
vida; mezclarla en una firma de 15 campos esconde la invariante.

---

## 7. Decisión 7 — Peso de imágenes (sin Celery)

**DECIDIDA.** Resize client-side con canvas, **solo si el lado mayor
supera 2000 px**, re-codificación JPEG calidad 0.85.

- Números: foto de celular típica (4000×3000, 3–8 MB) → ~2000×1500,
  300–700 KB. Foto ya comprimida/achicada bajo el umbral → **no se
  toca** (cero re-compresión en cadena; se procesa una sola vez, al
  subir). 2000 px preserva calidad suficiente para el portal en
  ola 2 — achicar más ahorra bytes hoy y cuesta re-pedir fotos
  mañana.
- PNG/WebP que superan el umbral salen como JPEG — **la extensión de
  la key y el `mime_type` registrado reflejan el archivo final**, no
  el original.
- **Se sirve el original post-resize en todas las superficies.** Sin
  variantes en ola 1 (restricción sin-Celery). Mitigación
  obligatoria para S3: **`loading="lazy"` + `decoding="async"`** en
  las imágenes de la lista (con paginado de 20, cargan solo las
  visibles) + cache edge de Cloudflare.
- **Forma futura nombrada**: variantes server-side como task de
  Celery post-upload (el "consumidor futuro potencial" que el
  roadmap reservó), con alternativa registrada de Cloudflare Image
  Resizing si algún día se paga. **Disparador**: lentitud percibida
  en uso real o métrica que lo muestre.

---

## 8. Decisión 8 — b12: superficie de operaciones (diseño adelantado)

**DECIDIDA (solo diseño — implementación en S4, que queda reducida a
ejecutar esto).**

- **Retirar / Reactivar**: bloque "Acciones" en el sidebar del
  detail. En mobile el doble render lo trae arriba — correcto: son
  acciones de la propiedad, no contenido secundario.
- **Visibilidad por estado**: "Retirar" solo en AVAILABLE,
  "Reactivar" solo en UNAVAILABLE. El botón que no aplica **no
  existe** (no se deshabilita).
- **Transporte**: form nativo POST + redirect (convención de acciones
  destructivas de `frontend.md` — no `hx-post`), confirmación
  **two-step Alpine inline** (patrón del archivado, con ADR).
- **Reactivar vs gate**: `restore_property` → `_unpause_listings`
  valida publicación; el rechazo (A1: revierte todo) **reusa el
  checklist navegable de §1** — misma presentación para todos los
  rechazos del gate.
- **Señal del alquiler PAUSED post-venta**: badge outlined "Pausada"
  vía `BadgeContext` resuelto en view, en `_detail_publication` y en
  el slide-over de publicaciones. Nota contextual ("pausada al
  concretarse la venta") solo si no exige joins nuevos; si los
  exige, se degrada a badge solo.

### La sección "Operación" (listing) — creación y edición

Comparte partial entre fase 4 del wizard y la página de edición:

- Lista los listings existentes de la propiedad (estado, tipo,
  precio) + alta de listing nuevo: tipo de operación (venta /
  alquiler), precio, moneda, `price_min_acceptable` (opcional) →
  `create_listing` (nace DRAFT).
- Acción **"Publicar"** por listing DRAFT/PAUSED → `update_listing_status(PUBLISHED)`;
  rechazo del gate → checklist navegable. La unicidad
  (un PUBLISHED/PAUSED por tipo) ya la valida el service — el error
  va por `modal_error` estándar.
- Cambio de precio: `update_listing_price` (service existente, con
  historial). Sin edición de tipo de operación (se crea otro
  listing).

---

## 9. Espec operativa — pantallas y endpoints

### Pantallas nuevas

| Ruta | Contenido |
| --- | --- |
| `properties/new/` | Fase 1. Submit → `create_property` → redirect a `…/new/detalle/` |
| `properties/<uuid>/new/detalle/` | Fase 2 (form escalar + features + externas + location). "Siguiente" persiste y va a fotos; "Guardar y salir" → detail |
| `properties/<uuid>/new/fotos/` | Fase 3 (sección de fotos). Ídem navegación |
| `properties/<uuid>/new/operacion/` | Fase 4 (sección operación). "Finalizar" → detail |
| `properties/<uuid>/edit/` | §2: form escalar + secciones de acción (fotos, operación, externas, location) — los mismos partials del wizard |

Errores de validación de form: inline, patrón `contact_create`
(re-render con errores). Errores de negocio de services vía HTMX:
`partials/modal_error.html`. POST exitosos con navegación: 204 +
`HX-Redirect`.

### Endpoints nuevos (views, todos bajo el middleware de backoffice)

| Endpoint | Hace |
| --- | --- |
| `POST properties/<uuid>/media/sign/` | Re-valida MIME/tamaño/techo, `build_media_key`, devuelve key + presigned PUT |
| `POST properties/<uuid>/media/confirm/` | `public_media_exists` → `upload_property_media`; devuelve el partial de la foto |
| `POST properties/<uuid>/media/reorder/` | `reorder_property_media` |
| `POST media/<id>/set-cover/` | `set_cover_media` |
| `POST media/<id>/delete/` | R2 primero (`delete_public_media`), DB después (`delete_property_media` con promoción) |
| `GET /geo/geocode/` | Proxy Nominatim (User-Agent propio, rate limit) |
| `POST properties/<uuid>/listings/` · `POST listings/<id>/publish/` · `POST listings/<id>/price/` | Sección operación |
| (S4) `POST properties/<uuid>/withdraw/` · `…/restore/` | Form nativo + redirect |

---

## 10. Cambios de services y gate — especificados, NO implementados

1. **`storage.generate_media_upload_url(*, key, content_type, expires_in=300)`**
   — presigned PUT con `ContentType` fijado en la firma.
2. **`storage.public_media_exists(key) -> bool`** — `head_object`
   contra el bucket público.
3. **`properties.reorder_property_media(*, property, ordered_media_ids, actor)`**
   — reemplazo total del `order` en una transacción; rechaza si el
   set de ids no coincide exactamente con las fotos de la propiedad.
4. **`properties.delete_property_media`** — suma promoción de
   portada: si la borrada era cover y quedan fotos, la primera por
   `order` hereda `is_cover`, misma transacción. **Reemplaza el
   test-pin de S1 deliberadamente.**
5. **`properties.update_external_source(*, property, agency_name=UNSET, source_url=UNSET, agreed_commission_percent=UNSET, actor)`**
   — precondición `property.is_external` (excepción de validación si
   no; nunca crea la 1:1 por el costado); contrato UNSET idéntico a
   `update_property`; **`agency_name` no admite blanquear** (`""` se
   rechaza, espejo de `create_property`); `source_url` y comisión se
   blanquean libre.
6. **Gate (`listings._publication_requirements_missing`)** — valores
   nuevos: descripción **≥150 caracteres** (post-strip), **≥5
   fotos**. Códigos `description`/`photos` se mantienen. Las
   constantes se exportan (`MIN_PHOTOS_TO_PUBLISH = 5`,
   `MIN_DESCRIPTION_LENGTH = 150` en `listings/services.py`) y **la
   UI importa esas mismas constantes** para contadores y checklist —
   una sola fuente de números.

---

## 11. Diferidos con forma futura nombrada

| Qué | Forma futura | Disparador / ventana |
| --- | --- | --- |
| Variantes de imágenes | Task Celery post-upload (o CF Image Resizing pago) | Lentitud real / métrica; Celery disponible desde ola 2 |
| Location como requisito del gate | Decisión de S12 si ZonaProp exige coordenadas | S12 |
| Re-composición de la edición sobre el layout comercial + convivencia edición/detail | Re-layout de los partials autocontenidos | S6, con feedback del socio |
| Inline editing campo a campo | ADR de interacción nuevo | Sin disparador — solo si el uso lo pide |
| b12 implementación | Esta espec, §8 | S4 (contenido reducido a ejecutar) |

## 12. Deuda nueva descubierta

| Deuda | Ventana sugerida |
| --- | --- |
| Objetos huérfanos en R2 (PUT exitoso sin confirmación) — command de reconciliación (listar keys sin fila en DB, borrar con umbral de antigüedad) | V1.1 (o task Celery en ola 2) |
| Techo de 35 fotos vs límite real del portal | Verificar en S12 |
| Leaflet entra al stack — registrar decisión y versión en `frontend.md` | S3, al implementar |
| Enmienda de cierre de S1 ausente en `roadmap.md` de `main` | Commitear junto con este doc |

## 13. Para la ventana S2 y el roadmap

- **Estado de S2: decisiones tomadas en planificación, ejecución
  pendiente.** S2 se cierra cuando su ventana verifique este paquete
  contra `main` y commitee la espec — **b8 se salda con ese commit**,
  no antes. Si la verificación contradice una decisión, la ventana
  frena y lo plantea; no se desvía en silencio.
- **b12: el diseño se adelantó a la planificación** (§8). **S4 cambia
  de contenido**: pasa de "mini diseño + implementación" a
  implementación pura de §8 — a confirmar en el cierre real de S2.
- **Alcance sumado por decisión de planificación**: (a) UI de
  creación/publicación de listings — cerraba un agujero sin nombre
  (`create_listing` sin consumidor de UI, crítico para S10); (b)
  valores nuevos del gate (5 fotos / 150 caracteres) decididos acá,
  implementación en S3. Ambos sujetos a la verificación de la
  ventana S2.
- **S3 quedará sin bloqueos de diseño ni de backend** recién con el
  commit de S2, pero su alcance creció: secciones + wizard + upload
  presigned + 5 services/cambios + gate + Leaflet + sección de
  listings. Sugerencia para la ventana de planificación: evaluar
  partir S3 en dos ventanas (S3a: wizard + form escalar + fotos;
  S3b: operación + location + externas) — el corte natural es "lo
  que publica" vs "lo que carga".
