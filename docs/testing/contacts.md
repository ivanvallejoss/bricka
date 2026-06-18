# Convención de Tests — Contactos

## services — `test_services.py`

### `TestCreateContact`

| Test | Contrato verificado |
| ------ | ------------------- |
| `test_creates_contact_with_required_fields` | `create_contact` con solo `full_name` y `actor` genera una instancia persistida con `deleted_at=None` |
| `test_assigns_actor_as_created_by` | `created_by` y `updated_by` se asignan al actor en creación |
| `test_creates_contact_with_optional_fields` | campos opcionales como `email`, `phone`, `assigned_agent` se persisten correctamente |

**Qué no se testea aquí:** validación de campos — eso es responsabilidad del form, no del service.

---

### `TestUpdateContact`

| Test | Contrato verificado |
| ------ | ------------------- |
| `test_updates_fields` | los campos modificados se persisten y `updated_by` refleja el actor |
| `test_updated_at_changes` | `update_fields` incluye `updated_at` — verificado empíricamente contra comportamiento de Django con `auto_now=True` |

**Decisión documentada:** `updated_at` debe estar explícitamente en `update_fields` o no se actualiza. Verificado en shell antes de escribir el test.

---

### `TestArchiveContact`

| Test | Contrato verificado |
| ------ | ------------------- |
| `test_archives_contact_without_open_deals` | `soft_delete` se aplica cuando no hay deals activos |
| `test_raises_with_open_deals` | `ContactHasOpenDeals` se lanza cuando `outcome=""` en algún deal del contacto |
| `test_allows_archive_with_closed_deal` | deals con `outcome` en `WON/LOST/CANCELLED` no bloquean el archivado |

**Decisión documentada:** "deal abierto" = `outcome=""`. Los tres valores de `DealOutcome` son estados de cierre — ninguno bloquea el archive.

---

### `TestRestoreContact`

| Test | Contrato verificado |
| ------ | ------------------- |
| `test_restores_archived_contact` | `deleted_at` vuelve a `None` tras restore |
| `test_restored_contact_visible_in_default_manager` | el manager default (que filtra `deleted_at__isnull=True`) incluye el contacto restaurado |

**Por qué el segundo test:** `deleted_at=None` en el objeto no garantiza que el manager lo devuelva — podría haber un bug en el queryset. El test valida el contrato completo.

---

## selectors — `test_selectors.py`

### `TestGetContactList`

| Test | Contrato verificado |
| ------ | ------------------- |
| `test_returns_active_contacts` | el manager default excluye soft-deleted |
| `test_excludes_archived_contacts` | un contacto archivado no aparece en el listado |
| `test_no_filters_returns_all_active` | `filters=None` no aplica ningún filtro |
| `test_filter_by_role` | filtra correctamente por `role` |
| `test_filter_by_source` | filtra correctamente por `source` |
| `test_filter_by_assigned_agent` | filtra correctamente por `assigned_agent_id` |
| `test_combined_filters` | múltiples filtros se aplican con AND — no OR |
| `test_select_related_assigned_agent_no_extra_queries` | acceder a `assigned_agent` en el loop no genera queries adicionales — N+1 imposible por construcción |

**Decisión documentada:** `ContactFilters` como dataclass — filtros crecen sin modificar la firma del selector.

---

### `TestGetContactDetail`

| Test | Contrato verificado |
| ------ | ------------------- |
| `test_returns_existing_contact` | devuelve la instancia correcta por PK |
| `test_raises_if_not_found` | `Contact.DoesNotExist` para UUID inexistente |
| `test_raises_if_archived` | `Contact.DoesNotExist` para contacto soft-deleted — mismo comportamiento que no encontrado, intencional |
| `test_select_related_assigned_agent` | una sola query para detalle + agente |

**Decisión documentada:** el selector lanza `DoesNotExist` — el caller decide si convierte a 404 o propaga. No usar `get_object_or_404` en selectors.

---

### `TestGetContactHistory`

| Test | Contrato verificado |
| ------ | ------------------- |
| `test_returns_audit_logs_for_contact` | creación genera exactamente un log |
| `test_history_ordered_most_recent_first` | el log más reciente aparece primero |
| `test_does_not_return_logs_of_other_contacts` | el historial está aislado por entidad |
| `test_returns_empty_queryset_for_unknown_contact` | UUID inexistente devuelve queryset vacío — no `DoesNotExist` |
| `test_history_includes_all_action_types` | DELETE y RESTORE aparecen en el historial |
