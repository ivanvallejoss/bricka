# Convención de Tests — Audit

## audit signals — `test_signals.py`

### Contratos del sistema de trazabilidad

| Test | Contrato verificado |
| ------ | ------------------- |
| CREATE — log generado | cualquier `create_contact` genera exactamente un `AuditLog` |
| CREATE — `before` es null | objeto nuevo no tiene estado previo |
| CREATE — `after` tiene los datos | el snapshot post-creación es correcto |
| CREATE — `actor_id` correcto | el UUID del actor se persiste sin FK |
| UPDATE — log generado | cualquier `update_contact` genera log |
| UPDATE — `before`/`after` capturados | el sistema registra el estado anterior y el nuevo |
| UPDATE — `actor_id` correcto | el actor del update queda registrado |
| SOFT DELETE — acción `DELETE` | `archive_contact` genera log con `action=DELETE` |
| SOFT DELETE — `before.deleted_at` null | estado previo al archivado muestra `deleted_at=None` |
| SOFT DELETE — `after.deleted_at` presente | estado post-archivado muestra timestamp |
| RESTORE — acción `RESTORE` | `restore_contact` genera log con `action=RESTORE` |
| RESTORE — `before.deleted_at` presente | estaba archivado antes del restore |
| RESTORE — `after.deleted_at` null | volvió a estado activo |
| Infraestructura no auditada | `SearchPreference` (hereda `TimestampModel`) no genera logs |

**Decisión documentada:** signals solo disparan si `AppConfig.ready()` importa `signals.py`. Sin ese import, los `@receiver` nunca se registran — sin error, sin advertencia.

**Cobertura pendiente:** tests de signals para `BillingDocument` (`BaseModel + AuditableMixin` sin soft delete) — cuando se implemente esa vertical.
