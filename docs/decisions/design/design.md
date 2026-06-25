# Decisiones de Diseño — Bricka CRM

Convenciones técnicas y registro de decisiones del backend.

Este documento tiene dos partes con ciclos de vida distintos:

- **Parte 1 — Convenciones activas.** Las reglas que se siguen al escribir
  código, agrupadas por dominio. Enunciado terso + enlace al registro
  completo. Es la sección de consulta diaria.
- **Parte 2 — Registro de decisiones.** El contexto, la justificación y el
  trade-off de cada decisión. Formato ADR, append-only. Se lee una vez para
  entender el *por qué*; rara vez después.

Cuando una convención y su decisión coexisten, el enunciado vive en la
Parte 1 y el rationale completo en la Parte 2. No se duplica.

---

## Modelos base y herencia

- **`BaseModel`** es la raíz de todos los modelos del sistema (directo o vía
  `SoftDeleteModel`). Aporta UUID PK, timestamps y `created_by`/`updated_by`.
  → [ADR](#basemodel--raíz-de-modelos-de-dominio)
- **`SoftDeleteModel`** extiende `BaseModel` con `deleted_at`, doble manager
  (`objects` filtrado / `all_objects` sin filtro) y enforcement de audit.
  → [ADR](#softdeletemodel--soft-delete--enforcement-de-audit)
- **`TimestampModel`** es la base mínima (UUID + timestamps, sin trazabilidad
  de usuario) para tablas append-only o de reemplazo: `PropertyMedia`,
  `ListingPriceHistory`, `DealStageHistory`, `RentAdjustment`.
  → [ADR](#timestampmodel--base-para-tablas-auxiliares)
- **`AuditableMixin`** aporta enforcement de audit a modelos que NO heredan
  `SoftDeleteModel` (ej: `BillingDocument`). → [ADR](#auditablemixin--enforcement-para-modelos-sin-soft-delete)
- **`User` no hereda `BaseModel`** — hereda `AbstractUser` y declara UUID PK
  y `deleted_at` manualmente. → [ADR](#user--no-hereda-basemodel)

## Identidad y trazabilidad

- **PKs: UUIDv4** (`UUIDField(primary_key=True, default=uuid.uuid4)`) en todos
  los modelos. No se usa ULID. → [ADR](#pks--uuid-sobre-ulid)
- **No existe `tenant_id`** en ninguna tabla. → [ADR](#tenant_id--eliminado)
- **`created_by` / `updated_by`: FK nullable, `SET_NULL`, `related_name="+"`.**
  `null` significa "acción ejecutada por el sistema" (tareas Celery sin
  request). No hay un "system user". → [ADR](#created_by--updated_by--null--sistema)
- **`AuditLog.actor_id` es `UUIDField` sin FK** — snapshot histórico, no
  referencia viva. → [ADR](#auditlogactor_id--uuid-sin-fk)
- **Excepción a `SET_NULL`: `RentAdjustment.applied_by`** es no nullable con
  `PROTECT` — certifica quién aprobó el ajuste. → [ADR](#rentadjustmentapplied_by--excepción-a-la-convención)

## Modelado de dominio

- **`ContactRole`: campo único (`CharField`) en V1.** Un contacto tiene un
  solo rol simultáneo. → [ADR](#contactrole--campo-único-en-v1)
- **`assigned_agent` en `Contact`: semántica flexible.** Editable
  post-creación; la inmobiliaria define su uso. → [ADR](#assigned_agent--semántica-flexible)
- **`PipelineStage` y `DealStageHistory`: tablas presentes, inactivas en V1.**
  `Deal.stage` es nullable; el pipeline visual se difiere a V2.
  → [ADR](#pipelinestage-y-dealstagehistory--inactivos-en-v1)
- **`Deal.listing` nullable + `external_property_notes`.** Check constraint
  garantiza presencia de uno u otro. → [ADR](#deallisting--nullable-con-external_property_notes)
- **Mora: cálculo derivado, sin persistencia.** Se computa en
  `contracts/selectors.py`; se materializa solo en `billing_documents.concept`
  al emitir. → [ADR](#mora--cálculo-derivado-sin-persistencia)
- **`Listing.property`** — el campo FK se llama `property`, no `property_id`
  (Django agrega `_id` solo). → [ADR](#listingproperty--nombre-de-campo)

## Choices compartidos

- **Todo choice usado por más de una app vive en `common/choices.py`.**
  `Currency` es el caso canónico (usado por listings, contracts, billing,
  contacts). → [ADR](#currency--y-choices-compartidos--en-commonchoicespy)

## Capa de services y selectors

- **Cross-app via selectors.** Un service de la app A que necesita datos de B
  importa del `selectors.py` de B, nunca del `models.py`.
  → [ADR](#cross-app--selectors-como-punto-de-entrada)
- **Imports de type hints cross-app van bajo `TYPE_CHECKING`** (con
  `from __future__ import annotations`). `User` es la excepción: se importa
  vía `get_user_model()` en runtime. → [ADR](#imports-cross-app-de-type-hints--type_checking)
- **Selectors lanzan `Model.DoesNotExist`**, nunca `get_object_or_404`. El
  caller decide cómo manejar la ausencia. → [ADR](#selectors--manejo-de-no-encontrado)
- **Selectors con más de dos filtros opcionales usan un `dataclass`**, no
  kwargs individuales. → [ADR](#filtros-de-selectors--dataclass-sobre-kwargs)
- **Services usan kwargs explícitos con `*`**, no `data: dict`.
  → [ADR](#firmas-de-services--kwargs-explícitos-con-)
- **Todo `save(update_fields=[...])` incluye `"updated_at"`.** Sin excepción.
  → [ADR](#update_fields--updated_at-siempre-explícito)
- **Funciones puras de presentación viven en `_build_*_context` en views**,
  no en templates ni selectors. → [ADR](#funciones-de-contexto-en-views--_build__context)

## Excepciones

- **Excepciones de negocio en `<app>/exceptions.py`**; transversales en
  `common/exceptions.py`. → [ADR](#excepciones--organización-por-módulo)
- **Excepciones enriquecidas: adjuntar la instancia conflictiva en
  `__init__`** para evitar queries extra en la view.
  → [ADR](#excepciones-enriquecidas--adjuntar-instancia-conflictiva)

## Auditoría

- **`entity_type` nunca se hardcodea** — siempre `Model.audit_entity_type()`.
  → [ADR](#audit_entity_type--classmethod-en-auditablemixin)
- **Ninguna app importa `AuditLog` directamente** — todo pasa por
  `audit/selectors.py`. → [ADR](#cross-app--selectors-como-punto-de-entrada)
- **`.update()` y `.delete()` en queryset de modelos auditados lanzan
  `AuditViolationError`.** Usar `instance.soft_delete()` o el service.
  → [ADR](#softdeletemodel--soft-delete--enforcement-de-audit)
- **Apps con `signals.py` deben importarlo en `AppConfig.ready()`.** Hoy
  aplica a `audit`. → [ADR](#appconfigready--registro-de-signals)

## Billing

- **`BillingDocument.number`: PostgreSQL sequences por `document_type`.**
  Número asignado en el service, lo más tarde posible.
  → [billingdocumentnumber--postgresql-sequences](adr=design.md)
- **Moneda de `OWNER_STATEMENT` deriva a ARS por defecto** — deuda conocida
  para multi-moneda. → [moneda-de-owner_statement--deriva-a-ars-deuda-conocida](adr-design.md)

## Documentos

- **`documents/` es app propia** — `Document` tiene FK a contacts, properties,
  deals y contracts; no puede vivir en ninguna de ellas.
  → [documents--app-propia](adr-design.md)
- **Invariante de `Document`: al menos una FK padre presente.** Garantizado
  por el service, no por constraint. → [document--soft-delete--invariante-de-múltiples-padres](adr-design.md)
- **Hard delete de `Document`: R2 primero, DB después.**
  → [hard-delete-en-document--r2-primero-db-después](adr-design.md)
- **Batch upload: `.save()` individual dentro de `atomic()`**, sin
  `bulk_create` (bloqueado por el queryset auditado).
  → [batch-upload--save-individual-en-atomic](adr-design.md)
- **`categorize_document` vive solo en `documents/utils.py`.** Fuente única.
  → [categorize_document--fuente-de-verdad-en-documentsutilspy](adr-design.md)

## Formularios

- **Formularios con FK de alto volumen usan `forms.UUIDField`**, no
  `ModelChoiceField`. El combobox llena un hidden con el UUID.
  → [formularios-con-fk--uuidfield-en-lugar-de-modelchoicefield](adr-design.md)

## Infraestructura y URLs

- **HTMX vía `django-htmx`** (`request.htmx`), no chequeo manual de headers.
  → [htmx--django-htmx-como-librería-de-integración](adr-design.md)
- **URLs del backoffice centralizadas en `apps/backoffice_urls.py`.**
  → [estructura-de-urls--backoffice_urlspy-centralizado](adr-design.md)
- **Setup local híbrido:** solo `db` y `redis` en Docker; Django/Celery en
  venv local. PostgreSQL en puerto 5433. → [setup-híbrido-docker](adr-design.md)
  
## Storage — Cloudflare R2

- **Dos buckets:** `bricka-media` (público, custom domain, URL estable) para
  fotos de propiedades y assets de agencia; `bricka-documents` (privado, solo
  presigned URLs de corta vida) para documentos legales. No pueden convivir
  en un bucket. → [ADR](#r2--dos-buckets-por-modelo-de-seguridad-opuesto)
- **boto3 directo, sin `django-storages` ni `FileField` en modelos de dominio.**
  Los modelos gestionan `r2_key` como `CharField`. `STORAGES["default"]` queda
  como `FileSystemStorage`, usado solo por staticfiles.
  → [ADR](#boto3-directo--sin-django-storages-ni-filefield)
- **El bucket se deriva del modelo, no se almacena por fila.** `PropertyMedia`
  → siempre bucket público; `Document` → siempre bucket privado.
  → [ADR](#bucket-derivado-del-modelo-no-almacenado-por-fila)
- **Paridad dev/prod:** R2 corre con el mismo código en dev y prod. El
  aislamiento de datos lo da el `.env`: dev apunta a buckets `*-dev`.
  → [ADR](#paridad-devprod-en-la-ruta-de-código-de-r2)
- **Keys:** `properties/{property_id}/{uuid4}.{ext}` para media pública;
  `documents/{document_id}/{uuid4}.{ext}` para documentos privados.
  → [ADR](#keys-con-prefijo-legible--uuid-no-enumerable)
- **Funciones `delete_*` de storage lanzan, nunca tragan el error.** Habilita
  el orden "R2 primero, DB después" en los services de borrado.
  → [ADR](#funciones-delete-en-storage--lanzan-no-tragan)
- **URLs:** `get_public_media_url` → concatenación de string (costo cero);
  `generate_document_download_url` → presigned URL (default 300s, solo cuando
  un usuario abre un documento en el backoffice).
  → [ADR](#asimetría-de-costo--url-pública-vs-presigned)
- **Token de API de portales (Navent):** `access_token` cacheado en Redis con
  TTL = expiración del token menos margen. No necesita tabla.
  → [ADR](#token-de-api-de-portales--redis-no-db)

## Pendientes de diseño

Decisiones de modelado cerradas cuya capa de presentación o flujo aún no está
definida. No son convenciones activas — son recordatorios de qué acordar antes
de implementar.

- **`is_external` — tratamiento visual.** Las propiedades de otras
  inmobiliarias necesitan presentación, filtros y claridad diferenciados.
  Definir convención antes de las vistas de properties.

  → [propiedades-externas-is_external--presentación-pendiente](adr-design.md)

- **Logo de agencia: `r2_key` sin modelo de configuración.** La key existe
  en el bucket público pero el modelo de configuración de agencia que la
  referencia no existe aún. No bloquea storage.
  → [ADR](#logo-de-agencia--pendiente-de-modelo-de-configuración)

---
