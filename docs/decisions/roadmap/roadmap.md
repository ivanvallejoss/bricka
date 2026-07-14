# Roadmap hacia la entrega — Bricka CRM

Documento vivo de la ventana de planificación. Criterio rector: ENTREGA —
prioriza lo que el socio necesita pulido y estable para operar. Relegar un
ítem a V1.1/V2 es una decisión escrita, no un olvido.

**Última actualización:** 2026-07-14 (enmienda 5 — cierre de S1)
**Base verificada:** `main` como única fuente de verdad (todo commiteado
salvo `.env`).

---

## 1. Inventario reconciliado

Marcas: **(a)** en lista del desarrollador y en el repo · **(b)** solo en el
repo — gap no visto · **(c)** solo en la lista — sin registro en el repo.

### (a) — Coincidencias, con precisión contra el repo

| # | Ítem | Estado real verificado |
| --- | --- | --- |
| ~~a1~~ | ~~Upload de fotos / track R2~~ — **RESUELTO en S1 (2026-07-14)**: `storage.py` reconciliado a una sola generación (el bloque viejo nunca funcionó contra R2 — símbolos inexistentes en prod, URLs muertas en dev), 7 call sites migrados, settings sin fósiles, `.env` dev validado con round-trip real, seed EN VERDE con keys sintéticas (12 PropertyMedia, 6 covers, lógica de cover ejercida por el service), 12 tests de storage + 4 de services de media, `r2_smoke` como herramienta de ops. Ver `S1-r2-media.md`. Lo que queda del territorio es UI (S2/S3) | - |
| a2 | UI creación/edición de properties | Decisión 4 pendiente; espec original no commiteada (ver b8). Services listos: `create_property` expone title/description/location (umbral operable, no publicable); `update_property` con sentinela UNSET. Decisiones abiertas: flujo de upload, captura de location, edición de externas. |
| a3 | Celery | `config/celery.py` + settings existen; modelos `OutboundEvent`/`InboundEvent` diseñados para worker+beat+watchdog. Cero `tasks.py` en el repo. Alcance V1 decidido: solo lo que ZonaProp consume (ver §2, ola 2). |
| a4 | Usuarios | Base existente: `User` custom (UUID, soft delete, managers) + grupos `socio`/`agente` por data migration. Pendiente: perfil (nombre/foto), asociaciones agente↔entidades, uso de roles en vistas. → V1.1 |
| a5 | ZonaProp | `portal/models.py` vacío; `integrations` solo modelos de eventos. ADR de token Navent (Redis) cerrado. Todo el cableado por hacer. → V1 ola 2 (decisión de producto). |
| a6 | Vista de publicaciones | Parciales existentes: `slide_over_publications`, `detail_publication`. La vista consolidada depende de saber qué devuelve el portal → V1 ola 2, después de S13. |
| a7 | Hetzner / preparativos infra | **Ventana de preparativos CERRADA (2026-07-14)**: dominio `inmobiliariabricka.com` (existente en Namecheap de los socios — se descartó comprar `bricka.com.ar`), zona migrada a cuenta Cloudflare propia (Active, landing intacta), 4 buckets R2 creados con custom domain `media.` (prod) y r2.dev (dev), tokens scoped por entorno, CORS dev, SSL Full (Strict). 2FA del socio ✔, dev como Administrator ✔, titularidad Namecheap ✔. Ver `infra.md`. **Gate de S1 destrabado.** Resto (registro `app.`, `A` raíz, CORS prod, IP filtering) → S10. Gate de costo Hetzner: sin cambios (~90% funcional). |
| ~~a8~~ | ~~Auth (login/logout fuera del admin + protección global)~~ — **RESUELTO en S8**: `EmailBackend` + constraint CI + normalización; `BackofficeLoginRequiredMiddleware` con exención mínima y rama HTMX (200 + `HX-Redirect`); login/logout/password-change propios; sesión deslizante 2 semanas; validadores de password; `UserAdmin` con alta por email y archive/restore. 26 tests. Ver `S8-auth.md`. *(Nota: esta fila afirmaba "no existe middleware" y "`User` ya soporta login por email" — lo primero quedó viejo, lo segundo era aspiracional hasta S8; el archivo real es `apps/urls.py`, no `backoffice_urls.py`)* | — |

### (b) — Solo en el repo: gaps destapados

| # | Ítem | Versión |
| --- | --- | --- |
| ~~b1~~ | ~~`close_deal` WON deja el listing PUBLISHED (seed #7)~~ — **RESUELTO**: `close_deal` delega en `operations` (`settle_won_sale` para SALE, `transition_property_status(RENTED)` para RENT; el listing de alquiler se PAUSA, RENTED precede a SOLD). Ver ADR "Coordinación de estado cruzado". Lo vivo pasa a b12 | — |
| ~~b2~~ | ~~`create_property` sin title/description/location~~ — **RESUELTO** en la sesión de Decisión 3; `seed-data.md` quedó desactualizado (ver §5, diff) | — |
| b3 | Observabilidad: fase 1 NO está en `main` (sentry-sdk 1.40.0 EOL, init inline sin `before_send`). Fase 2 (logging estructurado) decidida sin implementar | F1 → V1 ola 1 (S9) · F2 → V1.1 |
| ~~b4~~ | ~~`PropertyStatus.UNAVAILABLE` sin camino de service (seed #6)~~ — **RESUELTO**: `withdraw_property` (AVAILABLE→UNAVAILABLE, docstring "Cierra el gap #6") + `restore_property`, con 28 tests en `operations/tests/`. Lo vivo pasa a b12 | — |
| ~~b5~~ | ~~Comisiones de alquiler sin superficie en cobros (seed #1)~~ — **RESUELTO en S5**: filtro `deal_type=SALE` eliminado de `get_cobros`; toda `COMMISSION_RECEIPT` es un cobro, con propiedad por fila (contrato → listing del deal → notas de externa). Retroactivo sin migración. 6 tests. Ver `s5-billing-operativo.md` | — |
| ~~b6~~ | ~~`$` hardcodeado en template de cobros, sin distinguir moneda (seed #2)~~ — **RESUELTO en S5**: partial `partials/_money.html` ($ + código ISO), aplicado a los 9 puntos que renderizan `total_amount`. Ver `s5-billing-operativo.md` | — |
| b7 | Deudas de `last-adr.md`: atributos con valor (8 enums/columnas), vocabulario por tipo de propiedad, A2 (restore parcial) | V2 (por diseño: se activan cuando el uso lo pida). Edición de externas: V1, dentro de S2/S3 |
| b8 | Documento de decisiones de properties (Decisiones 1–5) no existe en el repo; espec de Decisión 4 vive solo en una conversación vieja | V1 — S2 la re-deriva y commitea |
| b9 | Logo de agencia: `r2_key` sin modelo de configuración. Desde S5 es también el futuro dueño de los campos `AGENCY_*` del membrete (hoy en settings vía env, single-tenant) | V1.1 |
| b10 | Testing pendiente histórico (ContactForm.clean, signals audit before/after, views HTMX) + `storage.py` sin tests | Tests de cada track dentro del track; cola histórica → V1.1 |
| b11 | Numeración de billing incompatible AFIP (gaps por `nextval()`) | V2 — decisión explícita: V1 entrega comprobantes internos no fiscales |
| b12 | **Superficie de operaciones de propiedad** (sustituye a b1/b4): ninguna view llama `withdraw_property` / `restore_property` — retirar/reactivar no se puede hacer desde el backoffice; y el listing de alquiler que queda PAUSED tras una venta (`settle_won_sale`) no tiene señal visible para el agente. Alcance de UI, no de coherencia de dominio | V1 ola 1 (S4 redefinida) |

### (c) — Solo en la lista: a registrar

| # | Ítem | Versión |
| --- | --- | --- |
| c1 | Papelera (soft-deletes consolidados) — depende de a4 (separación por usuario) | V1.1 |
| c2 | Vista comercial del detail de properties — feedback directo del socio (mostrar propiedad a un cliente sin ruido operativo) | V1 ola 1 (S6) |
| c3 | Home — contratos por vencer + accesos (mínima, sin portales) en ola 1; sección portales en ola 2 | V1 (S7 + S14) |
| c4 | Exportar PDF — **comprobante de pago ✔ ENTREGADO en S5** (WeasyPrint 69.0, on-demand síncrono, sin persistencia — `pdf_url` eliminado del modelo; cuatro tipos, cancelados con banda; detail modal + ícono por fila desktop). Export genérico de imágenes/documentos sigue en V1.1 | ✔ S5 / V1.1 |
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

~~Auth (a8)~~ **✔ S8** · ~~Track R2/media (a1)~~ **✔ S1** · UI creación/edición (a2, b8, edición de
externas) · Superficie de operaciones de propiedad (b12) · ~~Billing operativo
(b6, b5, comprobante PDF de c4)~~ **✔ S5** · Vista comercial (c2) · Home
mínima (c3 reducida) · Observabilidad fase 1 (b3) · Puesta en producción.

### V1 — ola 2: portales → HITO "entrega completa"

Celery mínimo (a3) · Handler ZonaProp (a5) · Vista de publicaciones +
sección portales de Home (a6, resto de c3).

### V1.1

Users completo (a4) · Papelera (c1) · Logging estructurado (b3 f2) ·
Export genérico (c4 resto) · Logo de agencia (b9 + campos `AGENCY_*`) ·
Testing histórico (b10) · Notificaciones por mail (nuevo consumidor de
Celery) · **Refinamiento del comprobante con el socio** (deuda de S5:
separador de miles, jerarquías, membrete definitivo — natural encadenarla
con la validación de S6) · **Compartir comprobante** (forma técnica ya
definida en `adr-frontend.md`; requiere Celery, disponible desde ola 2) ·
**Search de cobros sobre propiedad de comisiones** (deuda de S5: el camino
deal→listing/notas queda fuera del filtro actual) · **Reset de password por
email** (deuda de S8; consumidor de la infra de mail/Celery) · **Links de
invitación** (deuda de S8: socio genera link con grupo embebido vía
`TimestampSigner`, entrega por WhatsApp sin mail; frontera V1.1/V2 —
primera superficie de registro semi-pública, ahí el rate limiting deja de
ser opcional; natural encadenarlo con a4) · b9 suma: **logout + cambio de
contraseña en mobile** (pantalla de Configuración; hoy inexistentes en
mobile a propósito).

### V2

Meta Catalog (c5) · Atributos con valor / vocabulario por tipo / A2 (b7) ·
Numeración AFIP (b11) · Pipeline visual (ya diferido por ADR) · **Rate
limiting de login / lockout** (de S8; se adelanta si entran los invite
links) · **2FA** (de S8; nombrado, sin diseño).

---

## 3. Secuencia de sesiones de V1

Camino crítico: R2 → UI de creación. Trámite de credenciales Navent: **iniciar
durante la ola 1** (única dependencia externa que puede mover la fecha final).

### Ola 1

| # | Sesión | Tipo | Depende de | Decisiones |
| --- | --- | --- | --- | --- |
| ~~S1~~ | **CERRADA (2026-07-14)** — Track R2/media completo (ver a1 y `S1-r2-media.md`). Hallazgo portable: R2 responde 400 (no 403) a GET sin firma — "S3-compatible" cubre la API firmada, no los bordes de error. Bonus: tercer fósil corregido en `docs/setup/development.md` | Cerrada | — | Todas cerradas y documentadas |
| S2 | Diseño UI creación/edición: re-derivar y commitear espec de Decisión 4 (salda b8); upload (orden/portada/validaciones), captura de location, edición de externas, ¿thumbnails? **+ de S1: decisión UX de portada al borrar el cover** (hoy no promueve otra foto y la presentación es inconsistente — list sin imagen, detail con fallback; comportamiento pineado por test, cambiarlo debe ser deliberado) | Diseño | ~~ADRs de S1~~ ✔ — sin bloqueo, próxima sesión natural | Las produce esta sesión |
| S3 | Implementación UI creación/edición. **+ de S1, opt-in solo si duele en dev:** flag `--with-r2-uploads` en el seed para placeholders visibles (hoy: keys sintéticas, `<img>` rotas en dev — trade-off asumido para que el seed corra en CI sin credenciales) | Implementación | ~~S1~~ ✔ + S2 | Las de S2 |
| S4 | Superficie de operaciones de propiedad (b12): acciones retirar/reactivar en el detail (llaman `withdraw_property`/`restore_property`) + señal visible del listing de alquiler PAUSED post-venta | Mini diseño + implementación (ventana única) | Post-S3 (hereda patrones del detail); las decisiones de superficie pueden adelantarse a S2 si conviene | Backend cerrado y testeado; falta solo la decisión de presentación |
| ~~S5~~ | **CERRADA (2026-07-09)** — Billing operativo: b6 ✔ (9 puntos + partial), b5 ✔ (selector + columna propiedad + 6 tests), c4 ✔ (display.py, pdf.py, endpoint, dos puntos de descarga, 12 tests). Bonus: CI reparado (requirements/dev.txt, ruff pinneado, libs WeasyPrint). 18 tests nuevos. Ver `s5-billing-operativo.md` | Cerrada | — | Todas cerradas y documentadas |
| S6 | Vista comercial del detail (c2) | Diseño (relevar con el socio) → implementación | Post-S3 (hereda patrones) | Faltan; insumo = feedback del socio |
| S7 | Home mínima: contratos por vencer (query request-time) + accesos. **+ de S8: repuntar `LOGIN_REDIRECT_URL` de `properties:list` (interim) a la home real** | Implementación con mini-diseño | Vistas previas (consistencia) | Casi cerradas por reducción de alcance |
| ~~S8~~ | **CERRADA (2026-07-13)** — Auth completo (ver a8 y `S8-auth.md`). Roto a propósito: logout/password-change inexistentes en mobile (bottom nav 5/5; destino b9). 26 tests, suite verde | Cerrada | — | Todas cerradas y documentadas |
| S9 | Observabilidad f1: upgrade SDK, init module, `before_send` | Implementación | — (justo antes de producción) | Diseño previo NO commiteado — la sesión deja el rationale en docs |
| S10 | Puesta en producción — **HITO: socios testeando** | Implementación | Todas + infra (dominio ✔, Cloudflare ✔, Hetzner pendiente) | Falta: checklist deploy, settings prod, migración de datos reales. **De S8, ya decididos, activar acá:** `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_*` según config final de dominio. **De infra, ejecutar acá:** registro `app.` + proxy naranja, recambio del `A` raíz (sale Tokko, entra el CRM), CORS prod en `bricka-media` (origin `https://app.inmobiliariabricka.com`), IP filtering del token `bricka-app-prod` con la IP de Hetzner, cert de origen (Cloudflare origin cert o Let's Encrypt). **De S1:** correr `r2_smoke` contra el `.env` prod (incluye el chequeo negativo de privacidad de documents) como parte del checklist |

### Ola 2

| # | Sesión | Tipo | Depende de | Decisiones |
| --- | --- | --- | --- | --- |
| S11 | Celery mínimo: worker + `OutboundEvent` + watchdog beat | Implementación con mini-diseño | Redis (existe) | Casi cerradas — docstrings de `integrations/models.py` son la espec |
| S12 | Diseño ZonaProp: contrato del handler, mapeo features→portal, errores/reintentos vía `OutboundEvent` | Diseño | Credenciales Navent (⚠️ tramitar en ola 1) | ADR token cerrado; el resto lo produce esta sesión |
| S13 | Implementación ZonaProp | Implementación | S11 + S12 + credenciales | Las de S12 |
| S14 | Vista de publicaciones + sección portales de Home | Diseño + implementación | S13 (recién ahí se sabe qué devuelve el portal) | Faltan; insumo lo genera S13 |
| — | **HITO: entrega completa** | | | |

### Transversales sin sesión propia

- Ventana de infra: ~~buckets dev antes de S1~~ ✔; Hetzner + tareas de
  deploy → absorbidas por S10. La ventana de preparativos cerró — deja de
  ser dependencia paralela. **Trámite Navent: sigue sin iniciar y sigue
  siendo la única dependencia externa que puede mover la entrega completa.**
- Fix documental de `seed-data.md` (§5) — commiteable hoy.
- Captura de c6 en la próxima charla con los socios.

---

## 4. Estado conocido de cosas rotas a propósito

- ~~`seed_test_data` queda rojo en su primer publish~~ — **RESUELTO en S1**:
  el seed siembra `PropertyMedia` (keys sintéticas) antes de los publish y
  corre EN VERDE.
- **`<img>` rotas en dev tras el seed** (S1): las keys son sintéticas, no
  hay objeto en R2. Trade-off deliberado para que el seed corra en CI y
  entornos sin credenciales. Remedio opt-in si duele: flag
  `--with-r2-uploads` (S3).
- Vars `R2_*` en settings son `env.str` sin default: sin `.env` poblado el
  proyecto no levanta. Deliberado (paridad dev/prod), pero es la primera
  pared de todo entorno nuevo.

---

## 4b. Deudas menores registradas (sin ventana asignada)

Registro para que no se pierdan; ninguna justifica sesión propia hoy. Se
promueven si aparece el disparador anotado.

- `property_label` duplicado en dos idiomas (elif de template en
  `_section_cobros`, Python en `display.py`). Disparador: un tercer
  consumidor → unificar anotando en la view. *(S5)*
- Ícono de descarga de comprobante en cards mobile. Disparador: pedido del
  socio con uso real en la mano. *(S5)*
- Renovación anual de `inmobiliariabricka.com` en Namecheap: titularidad y
  cuenta de los socios confirmadas (2026-07-14); **flag de auto-renew: no
  confirmado explícitamente** — verificar en la próxima visita al panel y
  borrar esta línea. *(infra.md)*
- Aviso de cortesía a Tokko (zona DNS vieja quedó muerta): **descartado por
  decisión (2026-07-14, "no necesario")** — registrado para que sea
  decisión y no olvido. *(infra.md)*
- Acoplamiento `BackofficeLoginRequiredMiddleware` → `HtmxMiddleware` (orden
  en `MIDDLEWARE`): hoy documentado solo en `S8-auth.md`. Disparador:
  cualquier sesión que toque `MIDDLEWARE` lo hace ruidoso primero (guard
  `hasattr(request, "htmx")` con error explícito o system check). *(S8)*
- Nota de escala: `SESSION_SAVE_EVERY_REQUEST` = un write de sesión por
  request HTMX (partials incluidos), no por página. Irrelevante hoy;
  revisitar solo si aparece en un profile. *(S8)*
- Migración `00002_create_groups` con cinco dígitos — typo inofensivo, **NO
  renombrar** (Django referencia por string exacto; `0003` depende del
  nombre literal). *(S8)*
- Deriva de nombre en docs: los ADRs y este roadmap nombraban
  `backoffice_urls.py`; el archivo real es `apps/urls.py`. Corregir al tocar
  cada doc, sin renombrar código. *(S8)*

---

## 5. Enmiendas documentales pendientes de commit

**`docs/decisions/seed-data.md`** — tres filas quedaron desactualizadas
respecto del código; marcarlas RESUELTO con referencia. **Verificado
2026-07-14: siguen sin aplicar en `main`** (S5 enmendó sus propias filas #1 y #2, estas tres siguen pendientes):

- **Gap #4**: la firma de `create_property` expone `title`, `description` y
  `location` desde la sesión de Decisión 3 (umbral operable vs. publicable).
  Ref: `last-adr.md`.
- **Gap #6**: `withdraw_property` / `restore_property` en
  `operations/services.py` dan camino de service a UNAVAILABLE.
  Ref: ADR de operations. Superficie de UI pendiente → roadmap b12/S4.
- **Gap #7**: `close_deal` coordina vía `settle_won_sale` /
  `transition_property_status`; el listing de venta se cierra siempre, el de
  alquiler se pausa. Ref: ADR "Coordinación de estado cruzado". Señal visible
  del PAUSED pendiente → roadmap b12/S4.

**Nota de método para futuras reconciliaciones:** las tablas de severidad de
`seed-data.md` son una foto de su sesión, no estado vivo. Todo gap listado
ahí se cruza contra services y ADRs antes de darlo por abierto.

**`docs/decisions/design/adr-design.md`** (línea ~865) — el "⚠️ Pendiente
operativo antes de producción" del ADR "R2 — dos buckets por modelo de
seguridad opuesto" quedó RESUELTO por la ventana de infra: buckets creados,
custom domain `media.inmobiliariabricka.com` Active, r2.dev para dev,
tokens scoped. Marcar con referencia a `infra.md`. **Verificado
2026-07-14 post-S1: sigue sin aplicar.**

~~**`docs/decisions/infra.md`**~~ — **COMMITEADO** (con la enmienda de S1:
ganaron los nombres del código, `R2_PUBLIC_MEDIA_BUCKET` /
`R2_PRIVATE_DOCS_BUCKET`).

~~**`docs/decisions/roadmap/roadmap.md`** — enmienda 3~~ — **COMMITEADO**
(enmienda 4 en `main`).

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
- **2026-07-08 (enmienda 1)** — b1 y b4 verificados como ya resueltos en
  `main` (corrección aportada por la ventana orquestadora, verificada acá
  contra el código). S4 se redefine de "coherencia de dominio" a "superficie
  de operaciones de propiedad" (b12) y pasa a depender de S3. `seed-data.md`
  suma dos filas al diff documental.
- **2026-07-09 (enmienda 2)** — S5 CERRADA (verificado contra `main`:
  `display.py`/`pdf.py`, migración 0009, WeasyPrint en base.txt y CI,
  `_money.html`, selector sin filtro SALE). b5, b6 y comprobante de c4
  resueltos. PDF on-demand síncrono sin persistencia — coherente con la
  partición de ola 1 (sin Celery); `pdf_url` eliminado del modelo. Tres
  ítems nuevos a V1.1 (refinamiento de comprobante con el socio, compartir
  comprobante, search de comisiones); b9 anotado como dueño futuro de
  `AGENCY_*`; sección 4b creada para deudas menores sin ventana. Ola 1
  restante: S1–S3, S4 (b12), S6, S7, S8, S9, S10.
- **2026-07-13 (enmienda 3)** — S8 CERRADA (verificado contra `main`:
  `EmailBackend` con timing constante, constraint CI en migración 0003,
  middleware con rama HTMX en `config/middleware.py`, settings de sesión y
  validadores, 26 tests). a8 resuelto; flags de producción decididos en S8
  quedan asignados a S10; repunte de `LOGIN_REDIRECT_URL` asignado a S7.
  Deudas de S8 distribuidas: reset por email e invite links a V1.1, rate
  limiting y 2FA a V2, logout mobile a b9. Cuatro registros nuevos en 4b
  (acoplamiento de middleware, nota de escala de sesión, migración 00002,
  deriva `backoffice_urls`/`apps/urls`). S8 era la sesión flotante: la
  ola 1 restante queda S1→S2→S3→S4, S6, S7, S9, S10 — el camino crítico
  R2→UI sigue siendo el frente abierto más largo.
- **2026-07-14 (enmienda 4)** — Ventana de preparativos de infra CERRADA.
  Cambio de dominio: `inmobiliariabricka.com` (existente, Namecheap de los
  socios) reemplaza a `bricka.com.ar`, que se descarta — activo existente +
  titularidad resuelta + costo cero. Zona migrada a cuenta Cloudflare
  propia; 4 buckets R2 operativos; tokens scoped por entorno; CORS dev.
  Confirmados por los socios: 2FA ✔, dev como Administrator ✔, titularidad
  Namecheap ✔; aviso a Tokko descartado por decisión. Confirmado: no queda
  código sin pushear. **Gate de S1 destrabado** — S1 es la próxima sesión
  natural y solo le falta poblar `.env` dev. Tareas de deploy de infra
  absorbidas por S10. Diffs entregados: `adr-design.md` (⚠️ resuelto),
  `infra.md` (reemplazo completo).
- **2026-07-14 (enmienda 5)** — S1 CERRADA (verificado contra `main`:
  `storage.py` en una sola generación, cero símbolos viejos, settings con
  nombres nuevos de buckets, `r2_smoke`, seed con `PropertyMedia` vía
  service, `test_storage.py`; `infra.md` y `development.md` reconciliados
  en la misma sesión). a1 resuelto; el rojo del seed sale de §4 y entra el
  trade-off de `<img>` rotas en dev. Herencias asignadas: decisión UX de
  portada al borrar cover → S2; flag `--with-r2-uploads` opt-in → S3;
  `r2_smoke` → checklist de S10. Hallazgo documentado: R2 devuelve 400 (no
  403) a GET sin firma. **El camino crítico queda sin ningún bloqueo: S2 es
  la próxima sesión y solo depende de sí misma.** Pendientes documentales
  persistentes: `seed-data.md` #4/#6/#7 y ⚠️ de `adr-design.md`.
