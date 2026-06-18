# Setup de Desarrollo — Bricka CRM

Guía para levantar el entorno de desarrollo local desde cero.

---

## Prerequisitos

- Python 3.12
- Docker y Docker Compose
- GDAL instalado en el sistema host

**Arch Linux / Omarchy:**

```bash
sudo pacman -S gdal python312
```

---

## Setup inicial

**1. Clonar el repositorio y crear el entorno virtual:**

```bash
git clone <repo>
cd bricka
python3.12 -m venv .venv
source .venv/bin/activate
```

**2. Instalar dependencias:**

```bash
pip install -r requirements/dev.txt
```

**3. Configurar variables de entorno:**

```bash
cp .env.example .env
```

Editá `.env` con los valores locales. Los valores default del
`.env.example` funcionan sin modificación para desarrollo local.

---

## Infraestructura — Docker híbrido

### Por qué híbrido

El setup completo (Django + Celery + DB + Redis en Docker) tiene un
problema de DNS en Arch Linux / Omarchy: los contenedores no pueden
resolver dominios externos durante el build, lo que impide instalar
dependencias dentro de la imagen.

**Solución adoptada:** solo la infraestructura corre en Docker.
Django y Celery corren directamente en el venv local.

El `Dockerfile` se mantiene en el repo — se usa en producción
(Hetzner), no en desarrollo local.

### Levantar infraestructura

```bash
docker compose up
```

Esto levanta únicamente `db` (PostgreSQL con PostGIS) y `redis`.

### Puerto de PostgreSQL — 5433

El contenedor de PostgreSQL expone el puerto `5433` en el host
(mapeado al `5432` interno). Motivo: conflicto con una instalación
local de PostgreSQL que ocupa el puerto `5432`.

`DATABASE_URL` en `.env` refleja esto:

``` bash
DATABASE_URL=postgis://bricka:bricka@localhost:5433/bricka
```

Si en otro entorno no existe ese conflicto, el puerto puede
volver a `5432` modificando `docker-compose.yml` y `.env`.

---

## Migraciones

Con la infraestructura levantada:

```bash
python manage.py migrate
```

El orden de dependencias entre apps está resuelto por Django
automáticamente. No es necesario migrar app por app.

**Nunca** correr `migrate <app>` directamente — Django no garantiza
que las dependencias de esa app estén aplicadas primero.

---

## Workflow de desarrollo

Cuatro terminales en paralelo:

```bash
# Terminal 1 — infraestructura
docker compose up

# Terminal 2 — Django
source .venv/bin/activate
python manage.py runserver

# Terminal 3 — Celery worker
source .venv/bin/activate
celery -A config worker -l info

# Terminal 4 — Celery beat (solo cuando haya tareas periódicas definidas)
source .venv/bin/activate
celery -A config beat -l info
```

Celery beat no muestra actividad hasta que existan tareas periódicas
definidas en `config/celery.py` o en los `tasks.py` de cada app.
El arranque silencioso es el comportamiento correcto.

---

## Verificación del stack

Para verificar que Django, Celery y Redis están operativos end-to-end:

```bash
python manage.py shell
```

```python
from apps.integrations.tasks import smoke_test
result = smoke_test.delay()
print(result.get(timeout=10))
# → "Celery + Redis OK"
```

⚠️ `smoke_test` es una tarea de verificación — no debe existir en
producción. Si aparece en `integrations/tasks.py`, eliminala.

---

## GDAL — consideraciones

GDAL requiere que la librería nativa del sistema esté instalada
antes de instalar el paquete Python. La versión del paquete Python
debe coincidir con la versión instalada en el sistema.

**Verificar versión instalada:**

```bash
gdal-config --version
```

El `Dockerfile` instala GDAL dinámicamente para evitar
desincronización:

```dockerfile
RUN pip install GDAL==$(gdal-config --version)
```

Por este motivo, `GDAL` no aparece en `requirements/base.txt` —
se instala en su propia capa del Dockerfile antes de las dependencias.

En el entorno local, GDAL se instala junto con las dependencias
del sistema (`sudo pacman -S gdal`) y el paquete Python se instala
como parte de `requirements/dev.txt` usando la versión reportada
por `gdal-config`.

---

## Variables de entorno — referencia

| Variable | Descripción | Default dev |
| --- | --- | --- |
| `SECRET_KEY` | Clave secreta Django | requerida |
| `DEBUG` | Modo debug | `True` |
| `ALLOWED_HOSTS` | Hosts permitidos | `localhost,127.0.0.1` |
| `DATABASE_URL` | URL de conexión PostgreSQL | `postgis://bricka:bricka@localhost:5433/bricka` |
| `POSTGRES_DB` | Nombre de la DB (Docker) | `bricka` |
| `POSTGRES_USER` | Usuario de la DB (Docker) | `bricka` |
| `POSTGRES_PASSWORD` | Password de la DB (Docker) | `bricka` |
| `REDIS_URL` | URL de conexión Redis | `redis://localhost:6379/0` |
| `SENTRY_DSN` | DSN de Sentry | vacío — desactiva Sentry |
| `R2_ACCESS_KEY_ID` | Cloudflare R2 key | vacío — usa filesystem local |
| `R2_SECRET_ACCESS_KEY` | Cloudflare R2 secret | vacío |
| `R2_BUCKET_NAME` | Nombre del bucket R2 | vacío |
| `R2_ENDPOINT_URL` | Endpoint R2 | vacío |
| `R2_CUSTOM_DOMAIN` | Dominio CDN de R2 | vacío |

**Storage en dev:** con las variables R2 vacías, Django usa
`FileSystemStorage` — los archivos se guardan en `/media/` local.
Este comportamiento está controlado por el bloque `if DEBUG` en
`config/settings.py`.

**Sentry en dev:** con `SENTRY_DSN` vacío, el SDK no se inicializa.
No hay tráfico hacia Sentry desde el entorno local.

---

## Problemas conocidos

**`relation "users_user" does not exist` al migrar:**
Ocurre cuando se intenta migrar una app antes de que sus dependencias
estén aplicadas. Solución: correr `python manage.py migrate` sin
especificar app.

**`role "bricka" does not exist` al conectar:**
El volumen de PostgreSQL fue creado sin las variables de entorno
correctas. Solución:

```bash
docker compose down -v
docker compose up
```

**`GDAL not found` al instalar dependencias:**
La librería nativa no está instalada en el sistema host.
Solución: `sudo pacman -S gdal` antes de `pip install`.

**`Temporary failure resolving` durante docker build:**
Problema de DNS en Docker sobre Arch Linux / Omarchy.
El Dockerfile no se usa en desarrollo local — este error
no afecta el workflow híbrido.
