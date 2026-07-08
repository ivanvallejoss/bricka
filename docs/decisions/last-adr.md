# Cierre de la vertical Properties — registro de implementación

Sesión de implementación sobre el documento de decisiones de la
auditoría de `properties`. Este registro documenta las enmiendas,
hallazgos y decisiones tomadas DURANTE la implementación. El documento
original sigue siendo la fuente de verdad del diseño; lo de acá lo
enmienda donde se indica.

Alcance ejecutado: capa de datos (Decisiones 1 y 2), contrato de
services (Decisión 3), gate de publicación (contrato de Decisión 3,
implementación en listings), selectors, mínimo visual de externas
(Decisión 5). Pendiente para ventana aparte: UI de creación/edición
(Decisión 4). Fuera de alcance intacto: R2, scheduler, API, portal,
máquina de estados.

---

## Enmienda a Decisión 1 — mecanismo de migración de features

El plan de tres movimientos (tabla → data migration desde JSON → drop
de JSONFields) asumía datos existentes que preservar. Al implementar,
el sistema no tiene entorno productivo: los únicos JSON poblados
provenían del seed, que se reescribió al vocabulario canónico.

Se colapsó a dos piezas:

1. Migración de schema en un movimiento (drop de ambos JSONField +
   tabla Feature + M2M + parking_spaces + description blank).
2. Data migration que siembra el vocabulario v1 — dato de dominio, no
   de test: toda DB nueva (incluida producción futura) lo obtiene por
   el solo hecho de migrar.

La Decisión 1 queda intacta en diseño (forma del modelo, contratos,
muerte de los JSONField); cambió solo el mecanismo de transición, que
era contingente a la existencia de datos.

Derivada para tests: el vocabulario sembrado por migración es parte
del baseline de toda suite. Los tests positivos pueden apoyarse en él;
los tests negativos deben usar identificadores fuera del namespace del
vocabulario real (un slug de fantasía sigue siendo seguro cuando el
vocabulario crezca; un slug real nunca lo fue).

## Enmienda a Decisión 1 — category en Feature

La decisión negativa "sin category hasta que exista consumidor" se
revirtió por activación de su propia cláusula: el consumidor llegó
dentro de la misma sesión (el form de creación necesita ~50 checkboxes
agrupados; una lista plana es hostil para el usuario no técnico).
category es TextChoices de 4 valores (general / caracteristicas /
servicios / ambientes), taxonomía provista por el dueño del producto.
icon y order manual siguen fuera: sin consumidor. El orden de display
es alfabético por label (Meta.ordering), no una columna manual.

Vocabulario v1: 54 features. Lista del dueño del producto (relevada
sobre departamentos) + slugs del seed que pasaron el test de la
Decisión 2 (vidriera, deposito, recepcion, kitchenette, lote_propio,
a_estrenar, en_pozo). porteria consolidó en encargado;
cocina_integrada/cocina_americana consolidaron en cocina;
cochera/cochera_doble/garaje salieron del vocabulario (son
parking_spaces); luminoso salió (es escala, no presencia — ver deuda).

## Deuda nueva — atributos con valor relevados junto al vocabulario

Del relevamiento surgieron atributos que NO son features (fallan el
test presencia/valor de la Decisión 2). Quedan nombrados con su forma
futura para agregarse sin rediseño:

| Atributo | Forma | Nota |
| --- | --- | --- |
| Cobertura de cochera | enum | atributo de parking_spaces; solo aplica si > 0 |
| Cantidad de plantas | columna numérica | |
| Disposición | enum frente/contrafrente/interno/lateral | |
| Luminosidad | enum muy/normal/poco | reemplaza al ex-slug "luminoso" |
| Orientación | enum 8 puntos | |
| Pisos del edificio | columna numérica | |
| Departamentos por piso | columna numérica | |
| Superficie cubierta | columna numérica | obliga a definir si area_m2 es total o cubierta |

## Deuda nueva — vocabulario por tipo de propiedad

La lista v1 fue relevada pensando en departamentos. Cuando el afinado
con los clientes lo pida, la forma es metadata property_types en
Feature (qué tipos ofrecen cada feature en formularios). El form v1
muestra el vocabulario completo: el costo de un checkbox irrelevante
es bajo y no justifica la metadata todavía.

## Paso 2 — contrato de update_property: sentinela UNSET

El contrato de edición del doc (blanquear = setear vacío/null) choca
con el sentinela None = no tocar: None no puede ser marcador de
ausencia y valor legítimo a la vez. Se adoptó UNSET
(apps/common/sentinels.py): UNSET = no enviado / no tocar; None y ""
pasan a ser valores (blanquear). El form manda todo (reemplazo total
desde su perspectiva); los callers programáticos (remandate_property)
siguen enviando solo lo que les importa, sin cambios. Se descartó el
reemplazo total obligatorio: forzaba a operations a leer-y-reenviar
cada campo, frágil ante campos nuevos y fuera del alcance de la sesión.

Enmienda menor a Decisión 1: features harmonizó al mismo sentinela —
UNSET = no tocar, [] = vaciar, lista = reemplazo. Los tres estados del
contrato congelado se preservan; cambió solo la ortografía de "no
tocar" para no convivir dos sentinelas en una firma.

Blanquear en campos string no-nullables = "" (convención de forms);
None en campo NOT NULL es error del caller y lo rechaza la DB — el
service no duplica la constraint.

Cambio de comportamiento: owner_contact_id=None ahora desasocia el
dueño (antes no-op). Semántica correcta del contrato nuevo; único
caller programático (remandate) pasa UUID real.

Pendiente para la ventana de UI: edición de datos de externas
(agency_name, source_url, comisión) — fuera de las firmas hasta ver
qué necesita el form de edición. El toggle de is_external sigue
prohibido.

## Gate de publicación — implementación y alcance (vertical listings)

Contrato definido en Decisión 3 de properties; implementación en
update_listing_status, bloque PUBLISHED, después de la unicidad.
v1: descripción no vacía (strip) + al menos una foto. Excepción
estructurada ListingPublicationRequirementsError(missing: list[str]),
códigos v1: "description", "photos". Hereda de ListingValidationError.

Decisión de alcance: el gate aplica a TODA transición a PUBLISHED,
incluido el PAUSED→PUBLISHED del orquestador (_unpause_listings, usado
por restore_property y remandate_property). Fundamento: la invariante
"nada incompleto llega a estado público" no distingue caminos, y el
contrato de edición del paso 2 hace real el escenario (blanquear
descripción con la propiedad retirada). Se descartó eximir la
republicación (agujero explotable) y un parámetro de bypass (puerta
lateral, prohibida por la restricción de la máquina de estados).

Comportamiento ante rechazo en el orquestador (A1): la excepción
propaga y la transacción revierte entera — restaurar/re-mandar una
propiedad incompleta exige completarla primero. La atomicidad del
orquestador quedó verificada por test (propiedad y listing revierten
juntos). Refinamiento futuro nombrado, no implementado (A2): saltear
el listing incompleto, restaurar igual e informar, espejo del éxito
parcial de la Decisión 4. Se adopta si el uso real lo pide.

Estado conocido: seed_test_data queda rojo en su primer publish (las
propiedades del seed no tienen fotos). Se resuelve en el track R2:
las filas de PropertyMedia del seed deben crearse ANTES de los
update_listing_status(→PUBLISHED).

## Selectors

prefetch de features en get_property_detail y get_property_preview
(la lista no paga el join — congelado en Decisión 1). external_source
entra al select_related del detail (consumidor: sidebar de externas).
Garantía fijada por test: recorrer features después del selector
cuesta cero queries. El filtro por features de PropertyFilters queda
SIN cablear: sigue sin consumidor en el repo (el form de creación no
filtra propiedades). Se cablea cuando el portal o la lista lo pidan.

## Mínimo visual de externas (Decisión 5)

Badge "Externa" en filas de la lista (mobile y desktop) y en el header
del detail; agency_name + link a source_url en el sidebar del detail.
Estilo: borde neutro — metadata de origen, no estado; no disputa
gramática visual a los badges de estado. La comisión acordada queda
deliberadamente fuera del render (dato comercial sensible en pantalla
potencialmente compartida con clientes); mostrarla requeriría decisión
explícita. is_external viaja como columna en la lista: cero joins.

## Notas de implementación (no ADR, contexto útil)

- Trait `publishable` en PropertyFactory: la factory pelada produce el
  umbral operable; completitud de publicación se pide explícita. Los
  tests que publican lo usan.
- skip_postgeneration_save=True en PropertyFactory (deprecación de
  factory_boy; el RelatedFactory del trait no modifica la instancia).
- La invariante 1:1 de externas permite al template acceder a
  external_source bajo guard de is_external sin manejo de ausencia.
