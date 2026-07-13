# Convenciones de Testing — Bricka CRM

---

## Stack

- pytest + pytest-django
- factory-boy para creación de instancias de modelos
- Base de datos real en todos los tests — sin mocks de ORM

---

## Estructura

Tests dentro de cada app:
apps/contacts/
└── tests/
    ├── init.py
    ├── test_services.py
    ├── test_selectors.py
    └── test_views.py
    └── factories.py

---

## Qué se testea

### Obligatorio

- **Services** — toda la lógica de negocio, incluyendo:
  - Camino feliz
  - Excepciones de negocio (`ContactHasOpenDeals`, etc.)
  - Comportamiento con `actor=None` (acciones de sistema)
- **Selectors** — queries con filtros, comportamiento de soft delete,
  `DoesNotExist` en entidades archivadas
- **Signals de audit** — que `before`/`after` se capturen correctamente
  en CREATE, UPDATE, soft delete y restore

### Cuando hay lógica real

- **Forms** — solo métodos `clean()` con validación cruzada.
  Campos simples con `required=True` no se testean.
- **Views** — solo flujos con branching no trivial (HTMX vs full page,
  manejo de excepciones de negocio).

### No se testea

- Models sin métodos propios
- URLs
- Templates

### Constante compartida vs literal en asserts

- Cuando dos artefactos no deben divergir jamás (copy de UI y su test),
  el test referencia la fuente única (ej. `EmailAuthenticationForm.error_messages`); cuando el trabajo del test es fijar un contrato con algo externo (formato de URL/header que
  consume HTMX o el browser), el esperado se escribe literal — derivarlo
  del mismo código que lo produce volvería el test tautológico.

---

## Factories vs fixtures

- **factory-boy** para instancias de modelos — nunca fixtures de pytest
  para esto.
- **Fixtures de pytest** para contexto compartido:
  - `client` autenticado
  - Usuario con rol específico

```python
# conftest.py
@pytest.fixture
def agent_user(db):
    return UserFactory(is_active=True)

@pytest.fixture
def auth_client(client, agent_user):
    client.force_login(agent_user)
    return client
```

---

## Mocks — cuándo y qué

La única excepción a "sin mocks": servicios externos.

- R2 — siempre mockeado en tests
- httpx — siempre mockeado en tests
- Celery tasks — `CELERY_TASK_ALWAYS_EAGER = True` en settings de test,
  no mocks individuales

El ORM nunca se mockea. Un test que mockea `.filter()` no detecta
queries incorrectas, índices faltantes, ni comportamiento real
del manager de soft delete.

---

## Convención de nomenclatura

```python
def test_create_contact_assigns_actor():            # camino feliz
def test_archive_contact_raises_with_open_deals():  # excepción de negocio
def test_get_contact_detail_raises_if_archived():   # comportamiento de selector
```

Formato: `test_<acción>_<condición_o_resultado_esperado>`

---

## Cobertura pendiente

Áreas documentadas como pendientes — registrar aquí cuando se
identifica que la lógica no está implementada todavía.

| Área | Archivo | Contexto |
| ------ | --------- | ---------- |
| `ContactForm.clean()` | `tests/contacts/test_forms.py` | Pendiente confirmación de Bricka sobre restricción `document_type`/`document_number` en V1 |
| Signals de audit `before`/`after` | `tests/audit/test_signals.py` | Verificar captura correcta con la primera vertical completa |
| Views HTMX vs full page | `tests/contacts/test_views.py` | Branching `request.htmx` — implementar cuando templates estén definidos |

Cada pendiente tiene además un `TODO(tests)` en el archivo
correspondiente con referencia a esta tabla.

---

## Settings de test

```python
# config/settings/test.py
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# R2 — storage mockeado
DEFAULT_FILE_STORAGE = "django.core.files.storage.InMemoryStorage"
```
