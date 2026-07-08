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

---

## Dominio y registro

bricka.com.ar vía NIC Argentina, titularidad del cliente.
Se registra bricka.com.ar a nombre del CUIT de la inmobiliaria (trámite TAD del titular). DNS delegado a Cloudflare: el registrador solo controla la delegación de nameservers; proxy, TLS, WAF y custom domain de R2 operan íntegramente en la zona de Cloudflare sin diferencia funcional con un dominio comprado en Cloudflare Registrar. Se descarta Cloudflare Registrar porque no soporta .ar y porque la titularidad debe quedar en el cliente (el sistema es un desarrollo a medida de su propiedad). Costo: renovación anual en nic.ar sin auto-renovación — requiere recordatorio operativo explícito (responsable: cliente, con respaldo del desarrollador).
