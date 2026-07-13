# Autenticación — Bricka CRM

Decisiones de la sesión S8 (a8 del roadmap). Cubre: quién entra al
sistema y por qué puerta. Autorización (qué puede hacer adentro) es
a4, V1.1 — fuera de este documento.

---

## Decisiones y rationale

### Identidad de login: email, vía backend propio

`EmailBackend` (`apps/users/backends.py`) busca por `email__iexact`
sobre el manager default y delega password/is_active en `ModelBackend`.
Se eligió backend propio (Opción B) sobre `USERNAME_FIELD = "email"`
(Opción A): mismo resultado funcional, radio de explosión mínimo —
el modelo no cambia su identidad, `username` queda como campo auxiliar.

Invariantes que sostienen el backend:

- **Unicidad case-insensitive de email** — constraint parcial
  `users_user_email_ci_unique` (`Lower("email")`, excluye `email=""`).
  Unicidad sobre campo opcional = unicidad parcial: un usuario sin
  email es válido pero no puede loguearse por email.
- **Normalización a lowercase en `User.save()`** — conveniencia; la
  invariante real vive en la DB (el constraint cubre `bulk_create`,
  `update()` y SQL directo, que no pasan por `save()`).
- **Archivados no autentican, doble candado** — `User.objects`
  (ActiveUserManager) los excluye del lookup, y `is_active=False`
  los frena en `user_can_authenticate()`.
- **Un archivado retiene su email**: el constraint lo incluye, así que
  no se puede re-dar de alta la misma casilla. Deliberado — el camino
  es restaurar, no duplicar.

`ModelBackend` queda de fallback en `AUTHENTICATION_BACKENDS`:
superuser por username en admin. Nota anti-enumeración: cuando el
email no existe, el backend corre el hasher igual (timing constante).

### Ubicación y mecánica del login

`/backoffice/login/` (lo que `LOGIN_URL` prometía desde el inicio),
sobre views de `django.contrib.auth` configuradas desde
`apps/users/urls.py` (namespace `users`) — sin `views.py`: no hay
lógica propia que lo justifique; nace cuando un flujo la necesite.
`EmailAuthenticationForm` re-tipa el campo `username` a `EmailField`
(el nombre del campo es el contrato con la cadena de backends).
Mensaje de credenciales inválidas deliberadamente ambiguo: no revela
si la casilla existe. `redirect_authenticated_user=True` y validación
de `?next=` contra open redirect vienen gratis del framework.
`LOGIN_URL`/`LOGIN_REDIRECT_URL`/`LOGOUT_REDIRECT_URL` por nombre con
namespace, no paths hardcodeados.

**Interim:** `LOGIN_REDIRECT_URL = "properties:list"` (home de facto).
S7 lo repunta a la home real cuando exista.

### Middleware: exención mínima y sesión expirada bajo HTMX

`BackofficeLoginRequiredMiddleware` protege `/backoffice/` por prefijo.
Exención por **igualdad exacta** solo para el login (logout y
password-change quedan protegidos: superficie de exención mínima).
Resolución del login URL por request con `resolve_url()` — nunca en
`__init__`, donde el URLconf puede no estar cargado.

Requests HTMX con sesión muerta NO reciben 302 (fetch lo sigue en
silencio y HTMX swapearía el login dentro del target del partial):
reciben 200 + `HX-Redirect` (`HttpResponseClientRedirect`) → navegación
de página completa. El `next` sale de `request.htmx.current_url_abs_path`
(la página real del usuario, no el path del fragmento; `None` si el
origen no coincide — anti open-redirect capa 1; `LoginView` re-valida,
capa 2). Encoding del `next` con `urlencode(..., safe="/")`, alineado
a la convención de `redirect_to_login` de Django.

Acoplamiento silencioso: este middleware depende de `HtmxMiddleware`
ANTES en `MIDDLEWARE` (`request.htmx`). Reordenar la lista lo rompe.

### Política de sesión

TTL 2 semanas (`SESSION_COOKIE_AGE = 1209600`, default explícito) con
ventana deslizante (`SESSION_SAVE_EVERY_REQUEST = True`): uso frecuente
no re-loguea nunca; inactividad de 2 semanas sí. Costo: un write de
sesión por request — irrelevante a esta escala, y perceptible solo
como lentitud marginal en tests de views con `auth_client`.

### Política del admin

Solo superuser (`is_staff` únicamente para el desarrollador). Habilitado
en producción: es la puerta de gestión de usuarios. `UserAdmin` propio
(`apps/users/admin.py`, antes vacío): alta con **email obligatorio**
(`AdminUserCreationForm` — sin email no hay login; el default de Django
lo dejaba pasar vacío), acciones archivar/restaurar que pasan por
`soft_delete()`/`restore()` (nunca `queryset.update()`: saltearía la
coordinación de los dos campos), y `all_objects` en el queryset — el
admin es la única superficie que ve archivados.

### Gestión de contraseñas V1

- Cambio propio: `PasswordChangeView` en `/backoffice/password/change/`.
  Cambiar la propia contraseña invalida todas las demás sesiones del
  usuario (verificación de `_auth_user_hash` por request) pero conserva
  la actual (`update_session_auth_hash`) — es el remedio correcto ante
  robo de sesión.
- Reset por el operador: `manage.py changepassword <username>` y el
  form de password del `UserAdmin`. Cero código.
- `AUTH_PASSWORD_VALIDATORS` estándar (antes ausente = lista vacía =
  cualquier string era válido). Aplica a cambios y altas, no re-valida
  passwords existentes.
- Reset self-service por email: V1.1 (requiere infraestructura de mail).

### Logout en la UI

Desktop: pie del sidebar (reemplaza el placeholder "Configuración"),
junto al link de cambiar contraseña. Form POST — `LogoutView` es
POST-only en Django 5, y coincide con la convención FRD de acciones
destructivas (form nativo, nunca `<a>` ni `hx-post`).

**Mobile: logout y cambio de contraseña NO existen en V1 — decisión
consciente, no un olvido.** El bottom nav está 5/5 (máximo por
convención) y el pie del sidebar no se renderiza en mobile. Con sesión
deslizante de 2 semanas, el caso de uso real es marginal. Destino: b9
(pantalla de Configuración), donde vive la cuenta completa en mobile.

### Login standalone

`templates/users/login.html` no hereda `base.html` (un anónimo no tiene
nav que ver) pero habla el sistema visual completo: misma fuente, mismo
CSS compilado, tokens y radios de `input.css`. Password change/done SÍ
extienden `base.html` (usuario autenticado, con su nav).

---

## Flags de settings decididos — destino S10 (checklist de producción)

Se decidieron en S8, se activan en S10:

- `SESSION_COOKIE_SECURE = True`
- `CSRF_COOKIE_SECURE = True`
- `SECURE_SSL_REDIRECT = True`
- `SECURE_HSTS_SECONDS` (+ `SECURE_HSTS_INCLUDE_SUBDOMAINS`,
  `SECURE_HSTS_PRELOAD` según config final de dominio)

Ya activos desde S8 (no son de producción): `SESSION_COOKIE_AGE`,
`SESSION_SAVE_EVERY_REQUEST`, `AUTH_PASSWORD_VALIDATORS`.

---

## Diff documental

- **roadmap a8**: el enunciado "No existe flujo ni middleware" quedó
  mitad viejo antes de S8 (el middleware existía) y entero viejo
  después: flujo completo implementado. También afirmaba "`User` ya
  soporta login por email" — era aspiracional (no había backend);
  ahora es verdadero. El docstring de `User` ("Login por email o
  username") pasó de aspiracional a exacto por la misma razón.
- **`backoffice_urls.py` vs `apps/urls.py`**: los ADRs y el roadmap
  nombran el primero; el archivo real es el segundo. Anotado, no se
  renombra nada en S8.
- **Migración `00002_create_groups`**: cinco dígitos (typo inofensivo).
  Django referencia por string exacto — NO renombrar: invalidaría el
  historial de migraciones aplicadas. `0003` depende del nombre literal.
- **`testing.md` — convención nueva a agregar**: *constante compartida
  vs literal en asserts.* Cuando dos artefactos no deben divergir jamás
  (copy de UI y su test), el test referencia la fuente única (ej.
  `EmailAuthenticationForm.error_messages`); cuando el trabajo del test
  es fijar un contrato con algo externo (formato de URL/header que
  consume HTMX o el browser), el esperado se escribe literal — derivarlo
  del mismo código que lo produce volvería el test tautológico.

---

## Deuda nombrada (no implementada)

| Ítem | Destino sugerido | Nota |
| --- | --- | --- |
| Reset de password por email | V1.1 | Consumidor de la infra de mail/Celery |
| Links de invitación (socio genera link con grupo embebido; agente crea su cuenta) | V1.1/V2 | `TimestampSigner` — no requiere mail (WhatsApp). Primera superficie de registro semi-pública: rate limiting deja de ser opcional ahí |
| Rate limiting de login / lockout | V2 (o junto con invite links) | Hoy: superficie interna, usuarios contados |
| 2FA | V2 | Nombrado, sin diseño |
| Logout + password change en mobile | b9 | Pantalla de Configuración |
| `LOGIN_REDIRECT_URL` → home real | S7 | Interim: `properties:list` |

---

## Estado final S8

- **Hecho:** EmailBackend + constraint + normalización; middleware con
  exención y rama HTMX; LoginView/LogoutView/PasswordChange* con form
  y templates propios; sesión deslizante; validadores de password;
  `UserAdmin` con alta y archive/restore; logout + cambio de contraseña
  en sidebar desktop; 26 tests (9 backend, 7 middleware, 10 flujo),
  suite completa verde.
- **Abierto:** nada bloqueante.
- **Roto a propósito:** logout/password-change inaccesibles en mobile
  (ver decisión, destino b9). El placeholder "Configuración" del
  sidebar fue reemplazado por el bloque de cuenta.
  