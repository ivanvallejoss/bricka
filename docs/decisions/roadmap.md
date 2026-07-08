# Roadmap hacia la entrega — Bricka CRM

Documento vivo de la ventana de planificación. Criterio rector: ENTREGA —
prioriza lo que el socio necesita pulido y estable para operar. Relegar un
ítem a V1.1/V2 es una decisión escrita, no un olvido.

**Última actualización:** 2026-07-08
**Base verificada:** `main` como única fuente de verdad (todo commiteado
salvo `.env`).

---

## 1. Inventario reconciliado

Marcas: **(a)** en lista del desarrollador y en el repo · **(b)** solo en el
repo — gap no visto · **(c)** solo en la lista — sin registro en el repo.

### (a) — Coincidencias, con precisión contra el repo

| # | Ítem | Estado real verificado |
| --- | --- | --- |
| a1 | Upload de fotos / track R2 | Backend YA en `main`: `common/storage.py` completo (dos buckets, keys, presigned), `upload_property_media` / `set_cover_media` / `delete_property_media`, vars `R2_*` en settings. Falta: flujo UI→backend, reconciliar funciones duplicadas en `storage.py` (`get_public_media_url` vs `build_media_url`; `generate_document_download_url` vs `generate_document_url`), seed de `PropertyMedia`, tests. |
| a2 | UI creación/edición de properties | Decisión 4 pendiente; espec original no commiteada (ver b8). Services listos: `create_property` expone title/description/location (umbral operable, no publicable); `update_property` con sentinela UNSET. Decisiones abiertas: flujo de upload, captura de location, edición de externas. |
| a3 | Celery | `config/celery.py` + settings existen; modelos `OutboundEvent`/`InboundEvent` diseñados para worker+beat+watchdog. Cero `tasks.py` en el repo. Alcance V1 decidido: solo lo que ZonaProp consume (ver §2, ola 2). |
| a4 | Usuarios | Base existente: `User` custom (UUID, soft delete, managers) + grupos `socio`/`agente` por data migration. Pendiente: perfil (nombre/foto), asociaciones agente↔entidades, uso de roles en vistas. → V1.1 |
| a5 | ZonaProp | `portal/models.py` vacío; `integrations` solo modelos de eventos. ADR de token Navent (Redis) cerrado. Todo el cableado por hacer. → V1 ola 2 (decisión de producto). |
| a6 | Vista de publicaciones | Parciales existentes: `slide_over_publications`, `detail_publication`. La vista consolidada depende de saber qué devuelve el portal → V1 ola 2, después de S13. |
| a7 | Hetzner / preparativos infra | Ventana paralela (dominio, Cloudflare, consolas R2). Dependencia externa del roadmap, no sesión propia. Gate de costo: Hetzner al ~90% funcional. |
| a8 | Auth (login/logout fuera del admin + protección global) | NUEVO — surgió en planificación. No existe flujo ni middleware. `User` ya soporta login por email; `backoffice_urls.py` centralizado habilita protección por namespace. → V1 ola 1. |

### (b) — Solo en el repo: gaps destapados

| # | Ítem | Versión |
| --- | --- | --- |
| b1 | `close_deal` WON deja el listing PUBLISHED (seed #7) — coherencia de dominio, el gap operativo más caro | V1 ola 1 (S4) |
| ~~b2~~ | ~~`create_property` sin title/description/location~~ — **RESUELTO** en la sesión de Decisión 3; `seed-data.md` quedó desactualizado (ver §5, diff) | — |
| b3 | Observabilidad: fase 1 NO está en `main` (sentry-sdk 1.40.0 EOL, init inline sin `before_send`). Fase 2 (logging estructurado) decidida sin implementar | F1 → V1 ola 1 (S9) · F2 → V1.1 |
| b4 | `PropertyStatus.UNAVAILABLE` sin camino de service (seed #6) | V1 ola 1 (S4) |
| b5 | Comisiones de alquiler sin superficie en cobros (seed #1) — negocio venta-céntrico pero con alquileres en administración | V1 ola 1 (S5) |
| b6 | `$` hardcodeado en template de cobros, sin distinguir moneda (seed #2) | V1 ola 1 (S5) |
| b7 | Deudas de `last-adr.md`: atributos con valor (8 enums/columnas), vocabulario por tipo de propiedad, A2 (restore parcial) | V2 (por diseño: se activan cuando el uso lo pida). Edición de externas: V1, dentro de S2/S3 |
| b8 | Documento de decisiones de properties (Decisiones 1–5) no existe en el repo; espec de Decisión 4 vive solo en una conversación vieja | V1 — S2 la re-deriva y commitea |
| b9 | Logo de agencia: `r2_key` sin modelo de configuración | V1.1 |
| b10 | Testing pendiente histórico (ContactForm.clean, signals audit before/after, views HTMX) + `storage.py` sin tests | Tests de cada track dentro del track; cola histórica → V1.1 |
| b11 | Numeración de billing incompatible AFIP (gaps por `nextval()`) | V2 — decisión explícita: V1 entrega comprobantes internos no fiscales |

### (c) — Solo en la lista: a registrar

| # | Ítem | Versión |
| --- | --- | --- |
| c1 | Papelera (soft-deletes consolidados) — depende de a4 (separación por usuario) | V1.1 |
| c2 | Vista comercial del detail de properties — feedback directo del socio (mostrar propiedad a un cliente sin ruido operativo) | V1 ola 1 (S6) |
| c3 | Home — contratos por vencer + accesos (mínima, sin portales) en ola 1; sección portales en ola 2 | V1 (S7 + S14) |
| c4 | Exportar PDF — comprobante de pago en V1 (operación diaria); export genérico de imágenes/documentos en V1.1 | V1 (S5) / V1.1 |
| c5 | Meta Catalog — investigación hecha fuera del repo (Business Verification como bloqueante conocido). Registrar el resumen en `docs/` aunque el track sea V2 | V2 |
| c6 | Idea de los socios mencionada junto a la administración de alquileres — **PENDIENTE DE ESPECIFICACIÓN**, sin versión asignada. Capturarla en la próxima charla antes de que se pierda | — |

---

## 2. Partición V1 / V1.1 / V2 — razonamiento de cada corte

### Criterios aplicados

1. **V1 = el socio opera el negocio completo**, incluida la publicación a
   portales (decisión de producto: es parte de la promesa de entrega).
2. **V1 se parte en dos olas con hito intermedio**: la ola 1 entrega el
   sistema interno operable y habilita a los socios a testear en producción
   mientras la ola 2 (portales) se desarrolla. Reduce riesgo de descubrir
   problemas de UX interno al final y adelanta el gate de Hetzner.
3. **Coherencia antes que superficie**: gaps que dejan estado inconsistente
   (b1) pesan más que vistas nuevas.
4. **Celery entra con su primer consumidor real** (ZonaProp), con alcance
   mínimo: worker + procesamiento de `OutboundEvent` + watchdog beat. El
   flujo interno no lo necesita: mora es cálculo derivado en selectors,
   contratos por vencer es query request-time. PDF en background y
   thumbnails: descartado el primero, el segundo queda como consumidor
   futuro potencial si S2 lo decide (se anota, no se implementa).

### V1 — ola 1: interno operable → HITO "socios testeando"

Auth (a8) · Track R2/media (a1) · UI creación/edición (a2, b8, edición de
externas) · Coherencia de dominio (b1, b4) · Billing operativo (b6, b5,
comprobante PDF de c4) · Vista comercial (c2) · Home mínima (c3 reducida) ·
Observabilidad fase 1 (b3) · Puesta en producción.

### V1 — ola 2: portales → HITO "entrega completa"

Celery mínimo (a3) · Handler ZonaProp (a5) · Vista de publicaciones +
sección portales de Home (a6, resto de c3).

### V1.1

Users completo (a4) · Papelera (c1) · Logging estructurado (b3 f2) ·
Export genérico (c4 resto) · Logo de agencia (b9) · Testing histórico (b10) ·
Notificaciones por mail (nuevo consumidor de Celery).

### V2

Meta Catalog (c5) · Atributos con valor / vocabulario por tipo / A2 (b7) ·
Numeración AFIP (b11) · Pipeline visual (ya diferido por ADR).

---

## 3. Secuencia de sesiones de V1

Camino crítico: R2 → UI de creación. Trámite de credenciales Navent: **iniciar
durante la ola 1** (única dependencia externa que puede mover la fecha final).

### Ola 1

| # | Sesión | Tipo | Depende de | Decisiones |
| --- | --- | --- | --- | --- |
| S1 | Track R2/media: reconciliar duplicados de `storage.py`, verificar wiring, sembrar `PropertyMedia` en seed (resuelve el rojo deliberado), tests | Implementación | Buckets dev creados (infra) | Cerradas (ADRs en `adr-design.md`). Nueva: qué función de cada par duplicado sobrevive |
| S2 | Diseño UI creación/edición: re-derivar y commitear espec de Decisión 4 (salda b8); upload (orden/portada/validaciones), captura de location, edición de externas, ¿thumbnails? | Diseño | ADRs de S1 (puede solaparse con S1) | Las produce esta sesión |
| S3 | Implementación UI creación/edición | Implementación | S1 + S2 | Las de S2 |
| S4 | Coherencia de dominio: b1 (`close_deal`↔listing) + b4 (`UNAVAILABLE`) | Diseño + implementación (ventana única, alcance chico) | — | Faltan; direcciones planteadas en `seed-data.md` |
| S5 | Billing operativo: b6 (moneda por fila), comprobante PDF, b5 (comisiones de alquiler en cobros) | Diseño corto + implementación | — | Falta: librería/layout PDF, dónde viven comisiones de alquiler |
| S6 | Vista comercial del detail (c2) | Diseño (relevar con el socio) → implementación | Post-S3 (hereda patrones) | Faltan; insumo = feedback del socio |
| S7 | Home mínima: contratos por vencer (query request-time) + accesos | Implementación con mini-diseño | Vistas previas (consistencia) | Casi cerradas por reducción de alcance |
| S8 | Auth (a8): login/logout propios, protección global vía `backoffice_urls.py`, política del admin | Diseño + implementación (ventana única) | — (flotante; obligatoria antes de S10) | Faltan las tres, todas chicas |
| S9 | Observabilidad f1: upgrade SDK, init module, `before_send` | Implementación | — (justo antes de producción) | Diseño previo NO commiteado — la sesión deja el rationale en docs |
| S10 | Puesta en producción — **HITO: socios testeando** | Implementación | Todas + infra (dominio, Cloudflare, Hetzner) | Falta: checklist deploy, settings prod, migración de datos reales |

### Ola 2

| # | Sesión | Tipo | Depende de | Decisiones |
| --- | --- | --- | --- | --- |
| S11 | Celery mínimo: worker + `OutboundEvent` + watchdog beat | Implementación con mini-diseño | Redis (existe) | Casi cerradas — docstrings de `integrations/models.py` son la espec |
| S12 | Diseño ZonaProp: contrato del handler, mapeo features→portal, errores/reintentos vía `OutboundEvent` | Diseño | Credenciales Navent (⚠️ tramitar en ola 1) | ADR token cerrado; el resto lo produce esta sesión |
| S13 | Implementación ZonaProp | Implementación | S11 + S12 + credenciales | Las de S12 |
| S14 | Vista de publicaciones + sección portales de Home | Diseño + implementación | S13 (recién ahí se sabe qué devuelve el portal) | Faltan; insumo lo genera S13 |
| — | **HITO: entrega completa** | | | |

### Transversales sin sesión propia

- Ventana de infra: buckets dev antes de S1; dominio + Hetzner antes de S10;
  trámite Navent cuanto antes.
- Fix documental de `seed-data.md` (§5) — commiteable hoy.
- Captura de c6 en la próxima charla con los socios.

---

## 4. Estado conocido de cosas rotas a propósito

- `seed_test_data` queda rojo en su primer publish (propiedades sin fotos).
  Se resuelve en S1: sembrar `PropertyMedia` antes de los
  `update_listing_status(→PUBLISHED)`.
- Vars `R2_*` en settings son `env.str` sin default: sin `.env` poblado el
  proyecto no levanta. Deliberado (paridad dev/prod), pero es la primera
  pared de todo entorno nuevo.

---

## 5. Enmiendas documentales pendientes de commit

**`docs/decisions/seed-data.md`** — gap #4: marcar como RESUELTO. La firma
de `create_property` expone `title`, `description` y `location` desde la
sesión de Decisión 3 (umbral operable vs. publicable; el gate de publicación
concentra la completitud). Referencia: `last-adr.md`.

---

## Registro de decisiones de planificación

- **2026-07-08** — `main` como fuente de verdad (vs. estado declarado en el
  prompt de sesión): R2 backend ya pusheado; observabilidad f1 recategorizada
  a pendiente.
- **2026-07-08** — ZonaProp dentro de V1 (decisión de producto del dueño);
  V1 estructurada en dos olas con hito intermedio de socios testeando.
- **2026-07-08** — Alcance de Celery en V1: exclusivamente lo que ZonaProp
  consume. Sin tasks internas hasta tener consumidor.
- **2026-07-08** — b5 (comisiones de alquiler) sube a V1 ola 1 por dato de
  negocio: venta-céntrico pero con alquileres en administración activa.
- **2026-07-08** — V1 entrega comprobantes internos no fiscales; AFIP (b11)
  explícitamente diferido a V2.
  