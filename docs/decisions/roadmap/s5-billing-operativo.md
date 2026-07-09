# S5 — Billing operativo: moneda por fila, comisiones de alquiler, comprobante PDF

Sesión de mini-diseño + implementación en ventana única. Entregas: b6, b5, c4.

## Decisiones

**Moneda (b6).** Patrón único: `$` + monto + código ISO como sufijo chico
(`partials/_money.html`), el mismo vocabulario visual que contracts. Aplicado
a los 9 puntos del sistema que renderizan `total_amount` (billing ×5,
contacts, properties ×2, contracts). El partial emite solo el contenido; el
`<p>` contenedor queda en cada caller (tres tamaños distintos conviven).
Renglones de desglose sin sufijo: la moneda del documento la declara el total.
Criterio: se extrae partial cuando se repite la *regla* ("cómo se escribe
dinero de un comprobante"), no cuando se parece el markup — por eso los
precios de contracts/listings no migraron.

**Comisiones de alquiler (b5).** La condición `deal_type=SALE` se eliminó de
`get_cobros`: toda `COMMISSION_RECEIPT` es un cobro — el selector quedó
alineado a la definición de la vista global (historial por dirección del
dinero) y la query se simplificó (cayó el join a deals del filtro, y el
import cross-app de `DealType`). Retroactividad gratis: filtro de lectura,
sin migración. Columna propiedad enriquecida para comisiones: contrato →
listing del deal → `external_property_notes`. `get_cobros` estrenó cobertura:
6 tests, incluido el que fija el gap #3 como intencional.

**Comprobante PDF (c4).**
- *Tipos:* los cuatro `document_type`, template compartido — el layout es el
  mismo y el costo marginal de restringir era mayor que el de incluir.
- *Librería:* WeasyPrint 69.0. HTML→PDF desde templates de Django (el idioma
  que el proyecto ya habla); CSS propio embebido — Tailwind no participa del
  pipeline. Deps de sistema: pango/harfbuzz (Dockerfile, CI, `pacman -S pango`
  en dev). Descartadas: fpdf2 (layout como código, ciclo de iteración más
  caro), xhtml2pdf (CSS viejo, mantenimiento irregular).
- *Generación:* on-demand síncrona en request-time, streaming con
  `Content-Disposition: attachment`, sin persistencia. Rationale: la
  inmutabilidad de `BillingDocument` hace la regeneración determinista —
  persistir compraba un caché no pedido con ciclo de vida de regalo.
  Compatible con la restricción de ola 1 (sin Celery). Consecuencia:
  `pdf_url` ELIMINADO del modelo (RemoveField) — campo dormido y mal tipado
  para su propio futuro (persistencia iría a bucket privado → key, no URL).
- *Layout:* comprobante interno no fiscal — leyenda enmarcada "Comprobante
  interno — sin validez fiscal", sin vocabulario AFIP (letra/CAE/QR).
  Anatomía formal: membrete, tipo+número prominentes, desglose tabulado con
  signos, total con moneda (patrón b6). Cancelados SÍ tienen PDF, con banda
  diagonal "CANCELADO": un comprobante anulado sigue siendo evidencia
  operativa.
- *Membrete:* `AGENCY_*` en settings vía env (repo público — datos reales en
  `.env`, patrón `R2_*`). Sin vertical propia: single-tenant, dato que cambia
  ~nunca. b9 puede absorber estos campos con el modelo de configuración.
- *Entrega:* detail modal (botón que existía deshabilitado) + ícono por fila
  en la tabla desktop de cobros y pagos, con `stopPropagation` nativo (la
  fila entera es target `hx-get`; `@click.stop` de Alpine exige scope
  `x-data` no garantizado en billing — desviación consciente del patrón de
  contacts). Mobile excluido a propósito: mis-taps sobre cards compactas.

**Estructura.** Nuevo `apps/billing/display.py`: presentación pura compartida
(`enrich_lines_for_display`, `month_label`, `property_label`, sets
subtractive) — extraída de views para que `pdf.py` no genere ciclo de
imports. `apps/billing/pdf.py` separa `build_pdf_context` de
`render_document_pdf`: los tests aseveran sobre contexto, no sobre bytes.

**CI (de pasada, aprobado en sesión).** El workflow instalaba
`requirements.txt` (inexistente) y corría ruff sin instalarlo — roto tal como
estaba escrito. Reparado: `requirements/dev.txt`, `ruff==0.15.20` pinneado en
dev, paso apt con libs de WeasyPrint.

## Enmiendas documentales aplicadas

- `seed-data.md`: gaps #1 y #2 → RESUELTOS con referencia; gap #3 referencia
  al test que lo fija; bullet de comisión de venta marcado como superado.
- `adr-frontend.md`: deuda `COMMISSION_RECEIPT` → SALDADA; "Compartir /
  descargar" → descargar saldada, compartir con forma futura completa.

## Deuda nueva

| Deuda | Ventana sugerida |
| --- | --- |
| Refinamiento de layout del comprobante con el socio (separador de miles, jerarquías, membrete definitivo). El formato actual es correcto pero no validado con quien lo va a entregar. | Sesión propia, V1.1 |
| Search de cobros no matchea la propiedad de comisiones (filtra `recipient_name` + `contract__property`; el camino deal→listing/notas queda afuera). | V1.1 |
| `property_label` duplicado en dos idiomas (elif de template en `_section_cobros`, Python en `display.py`). Unificar anotando en la view si aparece un tercer consumidor. | Registro, sin ventana |
| Ícono de descarga en cards mobile, si el socio lo pide con uso real en la mano. | Registro, sin ventana |

## Estado final

- **Hecho:** b6 (9 puntos + partial), b5 (selector + columna propiedad +
  6 tests), c4 (display.py, pdf.py, template, endpoint, dos puntos de
  descarga, 12 tests), `pdf_url` eliminado, CI reparado, enmiendas aplicadas.
  18 tests nuevos en total.
- **Abierto:** validación de formato con el socio (deuda arriba).
- **Roto a propósito:** nada.

## Para el roadmap

S5 CERRADA: b6 ✔, b5 ✔, c4 ✔ (PDF on-demand con WeasyPrint, sin Celery, sin
persistencia — coherente con partición de ola 1). Reubicaciones sugeridas:
(a) nueva sesión "refinamiento de comprobante con el socio" en V1.1, natural
de encadenar con la validación de S6; (b) "Compartir comprobante" ya tiene
forma técnica definida — ubicarla explícitamente en la ola que estrena Celery;
(c) b9 anotado como futuro dueño de los campos `AGENCY_*`.