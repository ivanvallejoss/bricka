# Ventana pre-S4 — Unicidad de listing no-cerrado como invariante de dominio

Ejecuta la deuda #1 del cierre de S3b. La regla "un listing no-cerrado
por (property, operation_type)" deja de ser cortesía de la UI y pasa a
garantía de DB, con las tres capas del patrón chequeo + constraint +
catch (precedente: billing, recibos periódicos).

## Decisiones y enmiendas

- **Condición de la constraint**: `~Q(status="closed") &
  Q(deleted_at__isnull=True)` — exclusión, no lista. Criterio: ante un
  estado futuro, sobre-bloqueo visible > leak silencioso. Migración
  0004 (RemoveConstraint + AddConstraint, mismo nombre).
- **Helper `violates_constraint` → `apps/common/utils.py`**: segunda
  aparición idéntica (billing) y conocimiento de infraestructura
  (introspección del diag de Postgres), no de dominio — regla, no
  coincidencia. Billing importa desde common; su copia local se borró.
- **`create_listing`**: guard ampliado al conjunto no-cerrado con
  `.first()` (el mensaje nombra el estado bloqueante — "Borrador" pide
  otra acción que "Publicado") + catch de IntegrityError con mensaje
  propio de carrera ("actualizá la página" — el conflicto lo creó otro,
  el usuario no lo ve).
- **Unicidad-en-publish → defensiva**: inalcanzable por construcción
  tras la constraint. Filtro ampliado a no-cerrados (alarma parcial es
  peor que ninguna), log CRITICAL con args estructurados (siembra para
  Sentry F1, sin adelantar F2), error genérico al usuario. El comentario
  en el código explica el porqué de la inalcanzabilidad.
- **Enmienda de comentario en el orquestador**: `_ACTIVE_LISTING_STATUSES`
  ya no describe el slot del constraint sino el subconjunto *visible*.
  Solo comentario, cero lógica.
- **ADR de listings enmendado** (ver adr-design.md).

## Hallazgo empírico

La verificación pre-migración encontró en dev el estado inválido exacto
que la deuda predice: dos drafts SALE duplicados (prueba manual pre-S3b,
sin vía de descarte hasta S4). Saneado vía `archive_listing` por shell —
por la puerta de dominio, no por SQL. Evidencia de problema real.

## Tests

- Duplicado rechazado, parametrizado por los 4 estados no-cerrados;
  permitido con closed (test preexistente).
- Contrato del mensaje: nombra el estado bloqueante (fragmento literal,
  criterio testing.md: contrato con humano externo).
- Carrera, espejo de billing: constraint directa en DB bypaseando el
  service + guard cegado con mock → traducción a error de negocio.
  Criterio registrado: "sin mocks de ORM" prohíbe mockear para EVITAR
  la DB; acá el mock ciega el guard para OBLIGAR a la DB real a hablar.
  Se mockea el SELECT del guard, nunca el write path.
- Defensivo: guard cegado al revés + caplog → CRITICAL + error genérico.
- Reemplazados: los dos tests active/paused de create (subsumidos por la
  parametrización) y el de publish-con-activo (escenario imposible).
- Test de views de publish reescrito: el escenario de unicidad real es
  inalcanzable → el test inyecta ListingValidationError en la frontera
  view↔service (patch donde se usa) y verifica SOLO el ruteo
  (modal_error + HX-Retarget + no-efecto sobre el listing). Criterio:
  el contrato de la view es "muestra str(e)", se assertea con centinela,
  no con redacción real del service.

## Observaciones capturadas — destino: ventana de planificación

Sin versión asignada; la partición V1/V1.1/V2 la decide planificación.

1. **Edición de propiedad + affordance de forms** — reestructurar la
   superficie de edición (se suma a lo propuesto para property_detail/
   hover) + los inputs no se leen como inputs (problema de affordance
   visual, probablemente sistémico → clases compartidas, no template
   por template).
2. **Índices de aumento de alquiler + recomendación** — contracts ya
   guarda adjustment_index/frecuencia; falta la fuente del dato (BCRA/
   INDEC/manual) y el motor de recomendación. Dos ventanas: ingesta
   (candidata a Celery beat) y recomendación.
3. **Datos para el dashboard home/** — trabajo de definición primero:
   qué pregunta responde para el socio. Sesión de diseño antes de código.
4. **Soft-delete de propiedad** — Property ya hereda SoftDeleteModel;
   falta la puerta de dominio y la decisión de cascada (listings
   no-cerrados, contratos, deals). Insumo de esta ventana: un listing
   no-cerrado de una propiedad soft-borrada RETIENE el slot de la
   constraint — esa ventana decide si borrar propiedad cierra/archiva
   sus listings.
5. **Filtros en Facturación** — selectors + UI (período, tipo,
   destinatario). Acotada.
6. **PDF de comprobantes** — presentación (billing/pdf.py). Insumo
   previo: qué buscan los socios en el papel.
7. **Ciclo de vida de media en R2 vs. borrado** — reset del seed /
   cascadas / futuro soft-delete de propiedad: ¿la fila borrada limpia
   el objeto en R2 o queda huérfano? Definir UNA política para todos
   los caminos de borrado. Toca la #4.
   Confirmado en esta ventana: el reset usa TRUNCATE CASCADE (SQL puro,
   sin pasar por el ORM) → ningún camino de borrado actual limpia R2;
   todo objeto subido queda huérfano al borrar su fila. La ventana que
   tome esto define UNA política (borrado explícito del objeto vs.
   limpieza de huérfanos batch) para: reset del seed, cascadas, y el
   futuro soft-delete de propiedad (#4). Insumo pendiente de esa
   ventana: revisar el upload_to de PropertyMedia — si el path tiene
   prefijo predecible, la limpieza de huérfanos es un list+diff barato.

## Deuda nueva

- Ninguna propia de esta ventana. Conocimiento anotado (no deuda): el
  reemplazo RemoveConstraint+AddConstraint deja un instante sin
  constraint — irrelevante en dev; cuando exista producción (post-S10),
  las migraciones de constraints usan el patrón crear-nueva-borrar-vieja.

## Estado final

- **Hecho**: constraint extendida + migración aplicada, guard + catch en
  create_listing, publish defensivo, helper en common, comentario del
  orquestador, tests nuevos, ADR enmendado. Suite listings + billing en
  verde.
- **Abierto**: gate del seed — [COMPLETAR: --reset corrido | verificado
  contra DB efímera por la observación #7].
- **Roto a propósito**: el DRAFT pegado sigue sin vía de descarte en UI
  hasta S4 — fricción conocida, ahora con red de DB debajo.

## Para el roadmap

Deuda #1 de S3b: SALDADA. S4 destrabada como implementación pura sobre
paths firmes. Siete observaciones capturadas esperando partición en la
ventana de planificación.
