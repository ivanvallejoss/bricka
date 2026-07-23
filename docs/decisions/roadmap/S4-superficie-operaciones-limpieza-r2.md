# S4 — Superficie de operaciones de propiedad y listing + limpieza de huérfanos R2

Sesión de implementación. Ejecutó el §8 de S2 (mitad-propiedad), el insumo
para S4 de S3b, y la tajada acotada de la observación #7 de la ventana de
unicidad (limpieza solo en el camino del seed/reset, bucket de media dev).

## Decisiones tomadas

### Superficie de propiedad (§8)

- **Transporte**: form nativo POST + redirect (convención de destructivas;
  el sidebar renderiza dos veces). **Enmienda al prompt**: "errores del
  orquestador → modal_error" es incompatible con transporte nativo (sin
  HTMX no hay HX-Retarget). Resolución: `InvalidPropertyTransition`
  (solo alcanzable por página vieja/carrera — el botón no existe en estados
  inválidos) → `messages.error` + redirect; el base template ya renderiza
  messages (bloque existente, tokens `danger-*` vía el remapeo
  `MESSAGE_TAGS` de settings). Rechazo del gate en Reactivar → render
  directo de `property_detail.html` con `checklist_items` (checklist
  compartido, `flow=edit`), releyendo estado post-rollback desde DB.
  Habilitado por la extracción de `_property_detail_context(pk)`,
  compartido por `property_detail` y `property_restore`.
- **Copy** (corregido contra el ADR de operations — el prompt decía
  "retirar no toca listings"; el código pausa los PUBLISHED):
  Retirar del mercado / "Se pausan sus publicaciones y la propiedad sale
  de la landing. ¿Confirmar?" — Volver al mercado / "Sus publicaciones
  pausadas vuelven a publicarse. ¿Confirmar?".
- **Visibilidad**: el botón que no aplica NO existe (AVAILABLE ↔
  UNAVAILABLE únicamente).
- **Badge "Pausada"**: resuelto en view (`_annotate_listing_badges`,
  patrón BadgeContext, anotación de instancia — sin template filters
  nuevos ni cambio de forma de `listings`). Condición: listing de alquiler
  PAUSED + propiedad SOLD. PAUSED por retiro NO lleva badge (el header ya
  dice "No disponible"; el badge marca solo el estado que sorprende).
  Nota contextual como `title` (sin joins → entra gratis, cláusula §8).
  Tres call sites anotan: `_property_detail_context`, `detail_publication`
  (ahora trae el objeto property), `slide_over_publications`. Outlined
  con tokens `warning-*`.

### Superficie de listing (insumo S3b)

- **Hallazgo**: la reactivación de listing YA existía — el botón Publicar
  en PAUSED re-corre el gate y manda el rechazo al checklist. Lo nuevo:
  copy por estado (DRAFT → "Publicar", PAUSED → "Reactivar", mismo
  endpoint), pausar y descartar.
- **Pausar** (`listing_pause`, PUBLISHED→PAUSED): flip liviano de listing,
  SIN orquestador. Guard de estado en la view (`update_listing_status` no
  valida transiciones hacia PAUSED); fila vieja/carrera → modal_error.
- **Descartar DRAFT** (`listing_discard` → `archive_listing`):
  **semántica verificada**: soft-delete, no transición de estado; la
  constraint de unicidad filtra `deleted_at__isnull=True`, así que
  descartar LIBERA el slot y recrear el tipo queda permitido — vía de
  salida del DRAFT pegado de S3b. Destructiva → form nativo + redirect
  por flujo (wizard → new_operacion; edit → edit#operacion-section).
  No-DRAFT → 404 (la acción no existe para ese estado, mismo criterio
  que el botón). Two-step inline (patrón probado; se testeó el wiring).
- **Cerrar-por-venta NO existe acá** — flujo comercial de S6, según la
  distinción del insumo.

### Limpieza de huérfanos R2 (tajada #7)

- **Definición de huérfano**: objeto en el bucket público de media sin
  fila PropertyMedia con esa key, más viejo que la ventana de gracia.
  Atemporal — idéntica corriendo suelto o desde el reset.
- **Vehículo**: management command propio (`cleanup_r2_orphans`) que el
  reset invoca. Motivos: primera operación destructiva sobre bucket →
  corrible/testeable suelta; costo API irrelevante (ListObjectsV2 Clase A
  ~USD 4.50/M con 1M gratis/mes, 1000 keys/página; DeleteObject en R2 es
  GRATIS).
- **Orden del diff**: la limpieza corre AL FINAL del reset, contra la DB
  recién sembrada. La captura de keys pre-truncado del prompt original se
  ELIMINÓ del diseño: no aporta — toda fila que muere en el TRUNCATE deja
  su objeto huérfano por definición. Ventajas: una sola definición de
  huérfano; si la siembra falla no se borra nada; cero estado entre fases.
- **Ventana de gracia asimétrica** (decisión emergida de la verificación
  real): default 10 min en modo suelto (un presigned PUT pre-confirm es
  huérfano *aparente*); **gracia 0 invocada desde el reset** — post-
  TRUNCATE ningún upload en vuelo puede confirmarse (su propiedad no
  existe), todo objeto sin fila es huérfano definitivo. Sin esto, el
  ciclo doble era no-determinista (verificado empíricamente: corridas
  espalda contra espalda retenían los huérfanos frescos "por gracia").
  Test pinnea la asimetría.
- **Guards innegociables** (ver ADR): `settings.DEBUG` activo Y
  `R2_PUBLIC_MEDIA_BUCKET` con sufijo `-dev`. Cualquiera falla →
  CommandError, no corre, dice cuál. Desde el reset: best-effort — la
  siembra ya commiteó; CommandError (guard) y Exception (I/O: credenciales,
  red — verificado con ClientError 403 real) se reportan como warning sin
  abortar. Corriendo suelto: frena en seco.
- **Flag `--with-r2-uploads`** (enmienda a S3a §4, que lo había diferido):
  sube un JPEG placeholder (1x1, ~630 bytes, hardcodeado en base64 a nivel
  módulo) por cada PropertyMedia sembrada vía `upload_public_media`. Las
  `<img>` del seed dejan de renderizar rotas en dev, y el ciclo doble de
  verificación es reproducible sin depender de basura manual. Best-effort:
  sin credenciales reporta y sigue (las keys sintéticas sin objeto son el
  estado pre-flag, no un error).
- **`list_public_media_objects`** en `storage.py`: listado paginado por
  prefijo con `last_modified` (habilita la gracia). Solo lectura.
- **Salida contada**: listados / retenidos (con fila en DB / por gracia) /
  eliminados.

## Fricciones saldadas

- **DRAFT pegado (S3b)**: con vía de salida — Descartar libera el slot;
  test recrea el tipo tras descartar sin chocar la constraint.
- **Huérfanos del bucket dev (obs. #7, mitad-bucket)**: limpieza integrada
  al reset. La primera corrida real eliminó 13 huérfanos históricos de
  pruebas manuales; el ciclo de verificación quedó determinista.

## Verificación (condición de cierre)

- Suite completa en verde: **571 passed** (24 tests nuevos de S4:
  11 propiedad, 7 listing, 8 limpieza — incluye guards: DEBUG off y
  bucket no-dev → no corre y cero deletes).
- Ciclo real contra bucket dev (`--reset --noinput --with-r2-uploads`):
  corrida N: `30 listados / 30 retenidos (30 DB) / 0 eliminados`;
  corrida N+1 (post-fix de gracia): `90 listados / 30 retenidos (30 DB,
  0 gracia) / 60 eliminados`. Los recién sembrados intactos, todo lo
  anterior eliminado. Determinista.
- Recorrido manual de superficies: retirar→estado/pausa→reactivar;
  reactivar con gate en rojo→checklist; descartar DRAFT→recrear tipo.

## Diff documental

- **S3b-a-unicidad-invariante.md, Estado final**: reemplazar el
  placeholder por: "**Abierto → cerrado en S4**: gate del seed verificado
  — `--reset` corrido contra DB dev real con la limpieza R2 integrada
  (S4); ciclo doble determinista, salida contada en el cierre de S4."
- **roadmap.md, fila S4**: agregar a su descripción "+ flag
  --with-r2-uploads (revierte el diferimiento de S3a §4) + comando
  cleanup_r2_orphans con guards" si la descripción actual no lo cubre.

## Observación para planificación (no deuda)

**Ubicación de las views de listing.** Las views de acciones de listing
(`listing_create/publish/price/pause/discard`) viven en
`properties/views.py` porque su superficie es la sección Operación
(decisión S2). Respetan las puertas de dominio (services de `listings`;
el orquestador no aplica: no tocan `Property.status`). Patrón
preexistente desde S3b; S4 lo extendió sin alterarlo. Insumo para
planificación: evaluar si migran a `listings/views.py` con URLs propias
cuando alguna sesión toque esa zona por otro motivo — no amerita ventana
propia.

## Qué le queda a la obs. #7 general tras esta tajada

- Cascadas de dominio fuera del seed: borrados desde UI y sus huérfanos
  (la deuda de S3a "subida sin confirm" sigue viva — la gracia del
  comando la tolera, no la resuelve).
- Interacción con soft-delete de Property (obs. #4): qué pasa con la
  media de una propiedad archivada.
- Producción: política de limpieza (¿lifecycle rules de R2? ¿comando con
  otros guards? — hoy el comando se NIEGA a correr fuera de dev, a
  propósito).
- Bucket de documents: intacto, fuera de alcance.

## Deuda nueva

- **Two-step de contacts con hx-post** (preexistente, detectado en S4):
  el patrón de referencia del ADR de two-step es anterior a la convención
  de destructivas (form nativo). Migración oportunista cuando una sesión
  toque contacts — no amerita ventana propia.

## Estado final

- **Hecho**: E1 (superficie propiedad + badge), E2 (pausar / descartar /
  copy reactivar), E3 (listado + comando + guards + flag + invocación),
  suite y ciclo doble en verde.
- **Abierto**: nada de esta sesión.
- **Roto a propósito**: nada.

## Para el roadmap

S4 cerrada, b12 saldado; la ola 1 restante queda S6 → S7 → S9 → S10.
