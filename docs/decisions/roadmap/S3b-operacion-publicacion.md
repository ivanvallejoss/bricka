# S3b — Sección Operación, publicación, location y externas

Implementa "lo que publica + completitud" sobre la superficie de S3a: ofrecer
(listing), publicar con el gate como guía, ubicar en mapa, corregir la fuente
externa. NO toca el gate, sus constantes, ni el orquestador de operations.

## Qué se implementó (contra S2)

- **§10.5 `update_external_source`** — service en `properties/services.py`,
  contrato UNSET espejo de `update_property`, `agency_name` no blanqueable.
- **§1 checklist navegable** — resolver en `properties/checklist.py` (módulo
  nuevo) + partial compartido `_publication_checklist.html`. Traduce los códigos
  `missing` a ítems con deep link; agnóstico al flujo (wizard vs edición).
- **§8-listing sección Operación** — dos verticales: **alta** (form +
  `listing_create` + partial `_operacion_section.html`) y **publicación**
  (`listing_publish` + `listing_price` + fila con controles). Publicar rechazado
  por el gate → checklist; unicidad → `modal_error`.
- **§1 fase 4 del wizard** — `new/operacion/`, paso 4 de `WIZARD_STEPS`, reusa
  la sección con `FLOW_WIZARD`; "Finalizar" → detail.
- **§6 bloque externas** — `_externas_section.html`, se renderiza solo si
  `is_external` (invariante por ausencia, sin toggle), en fase 2 y edición.
- **§4 bloque location** — proxy `geocode` (cliente `common/geocoding.py`,
  espejo de `storage.py`) + Leaflet 1.9.4. Flujo buscar/click/drag/confirmar,
  persiste el Point vía `update_property`. Nunca bloquea.
- **Capas UX durables contra drafts duplicados** — el select de alta no ofrece
  un tipo ya tomado (no-cerrado); `hx-disabled-elt` mata el doble-click. Es UX,
  NO la garantía (ver deuda #1).

## Enmiendas a S2 (registradas acá; el paquete S2 las refleja)

1. **`period` derivado** — `create_listing` exige `period`; el form del §8 no lo
   colecta. La view lo deriva de `operation_type` (`SALE→TOTAL`, `RENT→MONTHLY`),
   espejando lo que el seed ya asume. El form no lo transporta. `temporary_rent`
   no se expone en V1.
2. **URLs de listings anidadas** — §9 definía `listings/<id>/publish|price/`
   plano. Las tres views renderean partials de `properties`, así que viven en
   `properties` (Fork B: la superficie pertenece al consumidor; `listings` queda
   dominio puro, sin views/urls). URLs → `properties/<uuid>/listings/<uuid>/…`.
3. **Geocode bajo `/backoffice/`** — §9 pedía "bajo el middleware de backoffice"
   pero definía `/geo/geocode/`, que cae fuera del prefijo `/backoffice/` que
   protege el middleware de S8 → proxy de geocoding abierto a internet, quemable
   (cuota de Nominatim + ban de IP). Corregido a `/backoffice/geo/geocode/`.

## Degradación transicional de S3a: saldada por construcción

El prompt asumía rechazos del gate saliendo hoy por `modal_error`. Verificado
contra `main`: ninguna view posteaba un publish → esa vía no existía. El
checklist **nace greenfield** como única superficie de rechazo de publicación;
no había degradación que migrar. El ítem queda satisfecho: ningún rechazo del
gate sale por la vía genérica, porque el checklist es la única que hay.

## Registros y patrones nuevos

- **`frontend.md` — Leaflet 1.9.4** (hecho): carga por página (solo edición y
  fase 2), tiles OSM con atribución, init inline `DOMContentLoaded`, `relative
  z-0`, config por data-attributes. Sin Leaflet, el init corta y la página anda.
- **`frontend.md` — `HX-Retarget`** (patrón nuevo, con ADR): acción con éxito
  inline + error/rechazo al modal, vía shell genérico `_modal_shell.html` con
  `HX-Retarget: #modal-container`. Primer caso del codebase con doble destino.
- **Módulo `properties/checklist.py`** (nuevo): dataclass + resolver + tabla
  código→ítem. La casa del contrato código→mensaje del gate.
- **Convención de helpers de sección** (lección de un bug saldado): todo helper
  que alimente un partial renderizable standalone (vía HTMX) debe devolver TODO
  lo que el partial referencia (`property` incluido), sin apoyarse en el
  contexto de la página.

## Deuda nueva (con ventana sugerida)

1. **Unicidad como invariante de dominio** — hoy solo la UI evita drafts
   duplicados del mismo tipo (capa débil). El cierre real: extender la constraint
   parcial a no-cerrados (`draft/pending/published/paused`), chequeo ampliado en
   `create_listing`, y catch de `IntegrityError` (espejo de `billing`). Efecto:
   la unicidad-en-publish se vuelve inalcanzable → su `except` pasa a defensivo
   con **log crítico** (si se dispara, un invariante imposible se rompió).
   → **Ventana propia, ANTES de S4.** Cierra el leak de doble-click/concurrencia/
   POST directo/callers no-UI que la UI no puede tapar.
2. **Dirección estructurada + auto-geocode** — `address_line` es texto libre que
   mezcla calle+número+piso; Nominatim se atraganta con el piso (mitigado con un
   strip por coma en `_location_section_context`, frágil: asume el formato). El
   fix real es campos estructurados (calle/número/piso separados) → cambio de
   modelo. El auto-geocode-al-cargar (que el mapa aterrice en la dirección sin
   apretar "Buscar") depende de esa base y quedó sin implementar.
   → **Ventana propia** (modelo + UX de ingreso de dirección).
3. **`price_min_acceptable ≤ price`** — invariante de negocio (un mínimo mayor al
   precio es un sinsentido). Su casa es **`create_listing`** (puerta única de
   dominio), NO el form: validar en el form deja la puerta abierta a cualquier
   caller futuro. → **V1.1.**
4. **Rango de `agreed_commission_percent`** (0–100) — si se quiere, invariante en
   `create_listing`, mismo criterio que #3. → V1.1.
5. **Cache de geocoding** — el "futuro" que nombra §4; dedup de queries
   repetidas. Se agrava si aterriza el auto-geocode-al-cargar (#2). → futuro.

## Estado final

- **Hecho:** update_external_source, checklist, sección Operación (alta +
  publicación), fase 4, externas, location (proxy + mapa), capas UX de unicidad,
  enmiendas registradas, `frontend.md` actualizado.
- **Roto a propósito / diferido:** remoción de listings (retirar/reactivar/
  cerrar) es S4. Consecuencia conocida: un DRAFT creado por error queda pegado
  hasta S4 y, con la capa UX de unicidad, bloquea recrear ese tipo. Fricción
  corta (S4 viene tras la ventana de unicidad).
- **Condición de cierre:** suite + seed + recorrido E2E en verde. Los tests por
  módulo quedaron verdes en cada paso; el pase completo es el gate final.

## Insumo para S4: "sacar de publicaciones" ≠ "cerrar por venta"

Son operaciones de capas distintas, no dos opciones de un mismo botón:

- **Sacar de publicaciones** — acción de *listing* (`PUBLISHED→PAUSED`);
  reactivar (`PAUSED→PUBLISHED`) re-corre el gate → **reusa el checklist**.
  Liviana, sin orquestador. **Es S4**, en la sección de operación.
- **Cerrar por venta** — *resultado de negocio*: la propiedad se vende, se
  registra el trato, y el **orquestador** (`operations`) cierra los activos como
  consecuencia. Vive en el flujo comercial (**S6**), no en un botón de la fila.

Un modal "¿sacar o vender?" co-locaría un evento pesado (orquestador + billing +
contrato) junto a un flip liviano — distinto radio de explosión, no comparten
botón.
