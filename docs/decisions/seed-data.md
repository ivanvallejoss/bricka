# Hallazgos de la sesión de seeding (seed_test_data)

Gaps de comportamiento que el sembrado de cobertura destapó. El sembrado
ejercitó las cuatro verticales vía services reales; cada fila salió de ver el
sistema correr con data variada, no de leer el código en frío.

## Pendientes — por severidad

### Coherencia de dominio (un flujo deja estado inconsistente)

| # | Gap | Dónde | Dirección |
| --- | ----- | ------- | ----------- |
| 7 | `close_deal` WON+listing marca la propiedad SOLD/RENTED pero deja el **listing PUBLISHED**. El seed lo cierra a mano; un flujo real por UI dejaría una unidad vendida aún publicada. | `deals/services.py::close_deal` | Decidir si `close_deal` cierra el listing como parte de la transacción, o si es acción separada del agente (y entonces bloquear/avisar) |
| 6 | `PropertyStatus.UNAVAILABLE` no tiene camino de service: ningún flujo la setea, solo `update_property_status` directo. Estado alcanzable pero sin transición de negocio. | `properties/services.py` | Definir el evento que lleva a UNAVAILABLE (retiro temporal, refacción) y darle un service, o documentar que es set manual de admin. |

### Superficie incompleta (la data existe pero no se puede ver/operar)

| # | Gap | Dónde | Dirección |
| --- | ----- | ------- | ----------- |
| ~~1~~ | ~~Comisión de alquiler sin superficie de listado~~ — **RESUELTO en S5**: la condición `deal_type=SALE` se eliminó de `get_cobros`; todas las comisiones se listan en cobros, con propiedad por fila (contrato → listing → notas de externa). Ver `s5-billing-operativo.md`. | | |
| 8 | Propiedades `is_external` sin tratamiento visual diferenciado en backoffice (card/listado). Se distinguen solo si el usuario lo escribe en el título. | templates/selectors de `properties/` | Diferenciar por `is_external` (badge/estilo). Ya estaba anticipado en el docstring de `Property`. |

### Display / UX (no rompe, confunde)

| # | Gap | Dónde | Dirección |
| --- | ----- | ------- | ----------- |
| ~~2~~ | ~~`$` hardcodeado sin distinguir moneda~~ — **RESUELTO en S5**: partial compartido `partials/_money.html` ($ + código ISO), aplicado a los 9 puntos del sistema que renderizan `total_amount` (cobros, pagos, detail modal, contacts, properties, contracts). Ver `s5-billing-operativo.md`. | | |
| 3 | Comprobantes sin `period` (comisión) desaparecen del listado de cobros al filtrar por mes. Visibles solo sin filtro. | `billing/selectors.py::get_cobros` | Aceptado como "menos sorprendente". Si se quiere bajo un mes, mapear por `date` en vez de `period`. Fijado como comportamiento intencional en `test_get_cobros_period_filter_excludes_documents_without_period` (S5): si ese test rompe, alguien relitigó esto. |

### Deuda de API interna (funciona, pero el contrato del service miente)

| # | Gap | Dónde | Dirección |
| --- | ----- | ------- | ----------- |
| 4 | `create_property` no expone `title`, `description`, `location` en su firma; se parchean con un `save()` post-create. | `properties/services.py::create_property` | Incorporarlos al service cuando sean campos de formulario reales. |
| 5 | Lógica de portada/orden de media (`is_cover`, `set_cover_media`) sin ejercitar: R2 no conectado, seed sin media. | `properties/services.py`, R2 | Pasada de media sobre la data sembrada cuando R2 esté conectado. |

## Resueltos en esta sesión

- **Reset roto** de `seed_demo_data` (no atómico + scope por `created_by` +
  `_raw_delete` sin cascada → estado parcial ante data de otro usuario).
  Reescrito a `TRUNCATE … CASCADE` en `seed_test_data`. *Pendiente operativo:*
  eliminar `seed_demo_data.py` ahora que `seed_test_data` corre completo.
- **Mora del seed** sembrada como interés simple; corregida a compuesta para
  reconciliar con `calculate_mora`.
- **Comisión de venta** ahora listada en cobros (`get_cobros`, condicionada a
  `deal_type=SALE`). *Superado en S5:* la condición se eliminó — todas las
  comisiones se listan.

## Pre-existentes confirmados (ya en docstrings)

- Numeración de billing con gaps por `nextval()` no transaccional; incompatible
  con AFIP. El nuevo reset reinicia las sequences.
- Pipeline (`DealStageHistory` / `PipelineStage`) diferido a V2.
  