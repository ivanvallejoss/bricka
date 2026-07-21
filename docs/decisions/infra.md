# Decisiones de infraestructura

Registro de decisiones de infraestructura de Bricka: dominio, DNS,
Cloudflare (zona, seguridad, R2) y su frontera con el código. Las
decisiones de *diseño* de storage (buckets, keys, URLs, boto3) viven en
`design/design.md` y `design/adr-design.md` — acá se registra su
**ejecución en consolas** y las decisiones que solo existen a nivel de
infraestructura: registrador, naming de subdominios, credenciales,
CORS y seguridad de zona.

Convención: cada decisión lleva su rationale corto. Los pendientes
tienen ventana dueña explícita. Ninguna sesión de infraestructura
cierra sin actualizar este documento.

**Última actualización:** 2026-07-14 — cierre de la ventana de
preparativos + confirmaciones de coordinación con los socios.

---

## Dominio y registro

### Dominio: `inmobiliariabricka.com` (existente, Namecheap) — se descarta compra

**Decisión final:** el CRM opera sobre subdominios de
`inmobiliariabricka.com`, dominio preexistente de la inmobiliaria,
registrado en Namecheap bajo cuenta de los socios. No se compra dominio.

**Historia de la decisión (dos etapas en la misma sesión):**

1. Se había aprobado registrar `bricka.com.ar` (titularidad del cliente,
   canal DonWeb, DNS delegado a Cloudflare). `bricka.com` está tomado
   por terceros activos — descartado permanentemente como dependencia.
2. Enmienda: los socios ya poseían `inmobiliariabricka.com`, en uso por
   la landing de Tokko. Activo existente + titularidad resuelta + costo
   cero > registro nuevo. Se descarta `bricka.com.ar`.

**Fundamento técnico:** registrador ≠ DNS autoritativo ≠ proxy. Namecheap
solo controla la delegación de nameservers; con la zona delegada a
Cloudflare, proxy/TLS/WAF/custom domain de R2 operan completos sin
importar el registrador.

**Riesgo operativo:** renovación anual en Namecheap. Titularidad y
cuenta de los socios **confirmadas (2026-07-14)**. Flag de auto-renew:
verificar en la próxima visita al panel (registrado también en roadmap
§4b).

### Migración de zona entre cuentas de Cloudflare

**Contexto:** la zona ya vivía en Cloudflare, en cuenta ajena (armada por
Tokko o quien montó la landing). El custom domain de R2 exige zona y
buckets en la misma cuenta.

**Ejecutado:** inventario DNS externo (2 registros: `A @ → 23.21.123.17`
AWS/Tokko, `CNAME www → @`, ambos DNS-only, sin MX/TXT), réplica exacta
en la cuenta Bricka, switch de nameservers en Namecheap. Zona **Active**,
landing verificada sin cambio de comportamiento.

**Regla aplicada:** migrar sin cambiar comportamiento — registros
existentes entran DNS-only; el proxy se evalúa después, nunca durante.

**Aviso de cortesía a Tokko** (su zona vieja quedó muerta): descartado
por decisión de los socios (2026-07-14, "no necesario").

## Cuenta de Cloudflare y gobernanza

- Cuenta creada con email de un socio (dueño del tenant). Tarjeta de la
  inmobiliaria cargada para R2. Handover final = gestión de miembros,
  nunca contraseñas compartidas.
- **Confirmado (2026-07-14):** 2FA activo en el perfil del socio ✔;
  desarrollador invitado como miembro **Administrator** ✔ (Super
  Administrator queda solo en el socio).

## Plan de subdominios (naming cerrado; creación por ventana dueña)

| Nombre | Uso | Proxy | Estado |
| --- | --- | --- | --- |
| `@`, `www` | Landing (hoy Tokko; futuro: la sirve el CRM) | Gris | Existentes — no tocar |
| `media.` | Custom domain R2 prod (`bricka-media`) | Gestionado por R2 | **Creado, Active** |
| `app.` | Backoffice Django (destino: Hetzner) | Naranja | No se crea hasta deploy (S10) |
| `staging.` | Entorno de staging | Naranja | Solo si algún día existe |
| MX | No hay email en el dominio | — | Nombrado; decisión comercial de los socios |

Criterio: DNS nunca se adelanta al destino — no se crean registros hacia
infraestructura inexistente (anti dangling-DNS).

### Dependencia outbound - GeoCoding

/backoffice/geo/geocode/ hace una llamada saliente a nominatim.openstreetmap.org (server-side, no el browser). En Hetzner el egress es libre; si se agrega allowlist de egress, sumar ese host. Rate limit 1 req/s por política, enforzado con gate Redis en common/geocoding.py. Cache de resultados = futuro.

## R2 — ejecución

- Cuatro buckets creados: `bricka-media`, `bricka-documents`,
  `bricka-media-dev`, `bricka-documents-dev`. Location: Automatic.
  Todos nacen privados; apertura pública deliberada y por bucket.
- `bricka-media` ← custom domain `media.inmobiliariabricka.com` (Active).
- `bricka-media-dev` ← Public Development URL `r2.dev` habilitada.
  **Decisión:** r2.dev para dev, sin custom domain propio — la paridad
  que protege el ADR de diseño es de código (la da el `.env`), no de URL.
  El rate limit de r2.dev es irrelevante para un dev solo.
- `bricka-documents` y `bricka-documents-dev`: **sin acceso público, por
  ningún mecanismo, nunca.** Única puerta: presigned URLs.
- Con esto queda **resuelto el "⚠️ Pendiente operativo antes de
  producción"** del ADR "R2 — dos buckets por modelo de seguridad
  opuesto" (`design/adr-design.md`) — enmienda entregada a esa doc con
  referencia a este archivo.

### Credenciales

Dos tokens de cuenta, permiso **Object Read & Write** (nunca Admin),
scope por buckets:

- `bricka-app-prod` → solo `bricka-media` + `bricka-documents`
- `bricka-app-dev` → solo `bricka-media-dev` + `bricka-documents-dev`

TTL Forever; la mitigación es rotación deliberada (ante sospecha de
filtración o cambio de manos), no expiración sorpresa. Secrets guardados
en gestor de contraseñas, fuera del repo y del chat. Filtrado por IP del
token prod: pendiente, requiere IP de Hetzner (→ S10).

### CORS

`bricka-media-dev` (habilita presigned uploads desde el browser en dev):

    [{"AllowedOrigins": ["http://localhost:8000", "http://127.0.0.1:8000"],
      "AllowedMethods": ["PUT"],
      "AllowedHeaders": ["Content-Type"],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3600}]

- Buckets de documents: sin CORS — la descarga presigned es navegación
  directa, sin preflight. Si algún día hay upload de documentos desde
  browser, se replica el patrón (ventana de código).
- CORS de `bricka-media` prod: pendiente de deploy — mismo JSON con
  origin `https://app.inmobiliariabricka.com` (→ S10).

## Seguridad base de zona

- SSL/TLS: **Full (Strict)** — se nace en el modo correcto; el origen
  futuro (Hetzner) se adapta con cert de origen de Cloudflare o Let's
  Encrypt (decisión de esa ventana).
- **Always Use HTTPS: On** (hoy solo alcanza a `media.`).
- Nada más con cero tráfico: sin WAF custom, rate limiting ni Bot Fight
  Mode — reglas sin hipótesis de amenaza son configuración muerta.

## Inventario de variables de entorno (frontera con ventana de código)

| Variable | Dev | Prod | Secreto | Origen |
| --- | --- | --- | --- | --- |
| `R2_ACCOUNT_ID` | = | = | No | Dashboard Cloudflare (sidebar de R2) |
| `R2_ENDPOINT_URL` | = | = | No | `https://<account_id>.r2.cloudflarestorage.com` |
| `R2_ACCESS_KEY_ID` | token dev | token prod | Sí | Emisión del token (gestor de contraseñas) |
| `R2_SECRET_ACCESS_KEY` | token dev | token prod | Sí | Ídem — irrecuperable, solo regenerable |
| `R2_PUBLIC_MEDIA_BUCKET` | `bricka-media-dev` | `bricka-media` | No | Este doc |
| `R2_PRIVATE_DOCS_BUCKET` | `bricka-documents-dev` | `bricka-documents` | No | Este doc |
| `R2_PUBLIC_MEDIA_BASE_URL` | `https://pub-<hash>.r2.dev` | `https://media.inmobiliariabricka.com` | No | Consola R2 / este doc |

Nombres definitivos — la ventana de código (S1, 2026-07-14) ejerció el
veto sobre los nombres de bucket: `R2_PUBLIC_MEDIA_BUCKET` /
`R2_PRIVATE_DOCS_BUCKET`, porque el nombre debe cargar el modelo de
seguridad (público/privado), misma convención que las funciones de
`common/storage.py`. Los valores secretos jamás entran al repo ni a
conversaciones.

Nota de estado del código (verificado por planificación, 2026-07-14):
`common/storage.py` y el wiring de services ya están en `main`; **no
existe código sin pushear**. La frontera pendiente con la ventana de
código es solo: poblar `.env` con este inventario + el alcance propio
de S1 (duplicados de `storage.py`, seed de `PropertyMedia`, tests).

## Pendientes con ventana dueña

| Pendiente | Ventana dueña | Estado |
| --- | --- | --- |
| ~~Verificar 2FA del socio + invitar al dev como Administrator~~ | Coordinación con socios | **RESUELTO 2026-07-14** |
| ~~Titularidad y cuenta Namecheap de los socios~~ | Coordinación con socios | **RESUELTO 2026-07-14** — flag de auto-renew por confirmar |
| ~~Aviso de cortesía a Tokko~~ | Socios | **DESCARTADO 2026-07-14** ("no necesario") |
| Registro `app.` + proxy naranja | Deploy Hetzner (S10) | Abierto |
| Recambio del `A` raíz: sale Tokko, landing la sirve el CRM | Deploy Hetzner (S10) | Abierto |
| CORS prod en `bricka-media` | Deploy Hetzner (S10) | Abierto |
| IP filtering en token `bricka-app-prod` | Deploy Hetzner (S10) | Abierto |
| Poblar `.env` dev + alcance S1 | Ventana implementación R2 (S1) | Abierto — gate destrabado |
| Marcar resuelto el ⚠️ del ADR de dos buckets en `design/adr-design.md` | Planificación (diff entregado) | Entregado 2026-07-14, pendiente de commit |
| `staging.` | Solo si el entorno nace | Condicional |
