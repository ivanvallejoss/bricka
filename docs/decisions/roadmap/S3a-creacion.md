# S3a — UI de creación y edición · Cierre de implementación

**Estado:** implementado y verificado (suite + seed verdes). S3b sin bloqueos.
**Espec de referencia:** `S2-ui-creacion-edicion.md` (decisiones §1–§13).

---

## 1. Qué se implementó

### Capa de services (§10)

- `generate_media_upload_url` (presigned PUT, ContentType en la firma),
  `public_media_exists` (head_object), `reorder_property_media` (set exacto,
  bulk_update), promoción de portada en `delete_property_media` (el heredero
  por `order,created_at` hereda `is_cover` en la misma transacción).
- Gate de publicación: `MIN_PHOTOS_TO_PUBLISH=5`, `MIN_DESCRIPTION_LENGTH=150`;
  `_publication_requirements_missing` los consume (códigos 'photos'/'description').
- Constantes de media: `MAX_PHOTOS_PER_PROPERTY=35`, `MAX_MEDIA_SIZE_BYTES=10MB`,
  mapas MIME↔extensión. `PropertyMedia.Meta.ordering = ["order","created_at"]`.

### Superficie de media (§3)

- Galería server-owned (`#media-gallery` > `#media-grid` estable) + 5 endpoints:
  `sign` (JSON), `confirm` (HTML éxito / JSON error, idempotente por key),
  `set_cover` / `delete` (HTML, delete = R2 primero, DB después),
  `reorder` (204 mantiene / 200 re-sync).
- Cola de subida Alpine (`_media_uploader.html`): dropzone, resize canvas
  (>2000px lado mayor → JPEG 0.85, EXIF `imageOrientation:"from-image"`),
  máquina de estados por archivo (spinner→tick/cruz+reintento), reorden por
  delegación (drag desktop / botones ↑↓ mobile).
- **Regla de forma de respuesta (Fork B):** JSON cuando son datos para que el
  cliente actúe; HTML cuando es presentación de estado persistido; 204 cuando
  no hay ninguno. El camino de error re-materializa la verdad (reorder falla →
  swap de galería). *ADR completo → `frontend.md` (pendiente, ver §5).*

### Form escalar de edición (§2/§5)

- `PropertyForm` (ModelForm; piso required `address_line`/`city`/`province`
  heredado del modelo `blank=False`; `owner_contact_id` UUIDField; `clean()`
  solo no-negativos; `.save()` nunca — `update_property` es la puerta).
- `property_edit` (GET+POST; kwargs EXPLÍCITOS vía `_save_property_scalar`;
  `features` reemplazo total por `getlist`; owner por combobox; **`location` y
  externas quedan UNSET** — un guardado escalar no borra el pin ni la fuente).
- `_property_fields.html` (campos, compartido con el wizard), `_feature_selector.html`
  (agrupado por las 4 `FeatureCategory`, contador por categoría live).

### Wizard de creación (§1, fases 1–3)

- Fase 1 (`properties/new/`): `PropertyCreateForm` + `create_property`; toggle
  `is_external` + `agency_name` (acá o nunca); regla externa→agencia validada
  por el service, mostrada como non-field error; guard anti-doble-submit.
- Fase 2 (`.../new/detalle/`): reusa `_property_fields.html`; doble submit
  (`name="action"`: "Guardar y salir" → detail / "Siguiente" → fotos).
- Fase 3 (`.../new/fotos/`): reusa `_media_section.html`; "Atrás"/"Finalizar"
  son navegación (las fotos persisten al subirse, sin submit).
- Shell `_wizard_steps.html` (pasos pasados completados NO clickeables).

### Entry points y performance

- "Editar" (header del detail), "Nueva propiedad" (page_actions de la lista).
- `loading="lazy"` + `decoding="async"` en listados, galería del detail y
  cards de edición.

---

## 2. Enmiendas contra la espec

1. **`modal_error` fuera de S3a.** Verificado: ninguna view postea un publish
   todavía. El gate 5/150 está armado en el service pero sin trigger de UI
   hasta S3b (fase 4). `reorder` no usa `modal_error` (es un drag, no hay modal
   en el DOM — su re-render de galería ES la recuperación).
2. **Seed acotado.** Solo las 6 descripciones de propiedades *publicables* se
   subieron a ≥150 chars (no las 13). El trait `publishable` (descripción ≥150
   - 5 fotos) cubre los tests que el gate rompió.

---

## 3. Roto a propósito

- El test-pin de S1 `test_deleting_cover_leaves_property_without_cover` se
  reemplazó por tests de promoción de portada. Decisión §3: se eliminó el
  estado "con fotos y sin cover" (inconsistencia sin valor operativo).

---

## 4. No implementado, con motivo

- **`--with-r2-uploads` (punto 9):** las subidas reales de la cola producen
  objetos R2 reales y pueblan la galería sin dolor. El flag solo servía para
  pre-poblar las fotos *sintéticas* del seed (keys sin objeto → `<img>` rotas
  en dev), nunca hizo falta para operar ni verificar la cola. Queda disponible
  si el desarrollo futuro quiere una galería pre-poblada de arranque.

---

## 5. Deuda nueva

- **Huérfanos R2:** una subida que no llega a `confirm` deja el objeto en R2
  sin fila en DB. Limpieza diferida (§11).
- **Combobox compartido:** `contracts/partials/_combobox_contact.html` ahora lo
  consume `properties/` también → mudar a un dir compartido (`common/`/`shared/`).
- **`x-data` del combobox de owner duplicado** entre `_property_form.html` y
  `property_new_detalle.html` (unas líneas; extraíble a variable).
- **Queryset del owner:** todos los contactos no borrados, sin filtro por rol
  (abierto como el FK).
- **ADR de forma de respuesta** (§1, Fork B) pendiente de escribir en `frontend.md`.

---

## 6. Fuera de alcance (S3b / S4)

- Fase 4 / sección Operación (`create_listing` + publicar).
- Checklist navegable del gate (`ListingPublicationRequirementsError.missing`
  → ítems con deep link). Presentación única para todo rechazo del gate.
- Bloque location (§4): Leaflet + Nominatim, proxy propio `/geo/geocode/`.
- Bloque externas (§6) + `update_external_source` (§10.5).
- b12/§8: retirar / reactivar.

Cada uno tiene **hueco nombrado** en la página de edición y/o el wizard fase 2.

---

## 7. Para el roadmap

**S3a cerrado.** Creación y edición operables de punta a punta. S3b arranca sin
bloqueos: sus piezas (operación, location, externas, gate checklist) aterrizan
sobre huecos ya nombrados, y la superficie de media + el form escalar quedan
como componentes reusables.
