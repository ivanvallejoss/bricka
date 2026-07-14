# S1 — Track R2/media: reconciliación de storage, wiring dev, seed, tests

**Cerrada: 2026-07-14.** Sesión de implementación; decisiones de diseño
de storage preexistentes en `design/adr-design.md` — acá solo las de
reconciliación propias de S1.

## Decisiones tomadas

- **Reconciliación de `storage.py`: sobrevive el bloque ADR-compliant**
  (kwargs-only, presigned default 300s). El bloque viejo no era solo
  divergente de estilo: su rama prod referenciaba símbolos inexistentes
  (`_get_s3_client`, `AWS_STORAGE_BUCket_NAME` → NameError) y su rama
  dev devolvía URLs locales a archivos que no existen. Nunca funcionó
  contra R2. Migrados 7 call sites en 2 archivos
  (`build_media_url` → `get_public_media_url`,
  `generate_document_url` → `generate_document_download_url`).
- **Base URL única: `R2_PUBLIC_MEDIA_BASE_URL`** (requerida, sin
  default). `R2_PUBLIC_BASE_URL` eliminada. Cayeron también
  `MEDIA_URL`/`MEDIA_ROOT` (único consumidor: la función muerta).
- **Nombres de env vars: ganó el código** —
  `R2_PUBLIC_MEDIA_BUCKET` / `R2_PRIVATE_DOCS_BUCKET`. Criterio: el
  nombre carga el modelo de seguridad (público/privado), misma
  convención que las funciones de `storage.py`. Diff entregado y
  commiteado en `infra.md`.
- **Seed de `PropertyMedia`: keys sintéticas** (formato real vía
  `build_media_key`, sin objeto en R2), 2 por propiedad, sembradas vía
  `upload_property_media` para que la lógica primera-foto-cover la
  ejerza el service. Trade-off asumido: `<img>` rotas en dev hasta S3;
  a cambio el seed corre en CI y entornos sin credenciales. Se viola a
  propósito la precondición del service ("r2_key ya subido") —
  documentado en el docstring del helper `_media`.
- **Borde de mocking para tests de storage: `storage._client` completo**
  vía `monkeypatch.setattr` (el `lru_cache` no participa). Se fija el
  contrato hacia boto3 (bucket por función, params, default 300s,
  propagación del retorno y de excepciones); no se re-testea boto3 ni
  la firma presigned. Compatible con `testing.md`: la prohibición de
  mocks es de ORM, no de I/O externo.
- **Smoke `r2_smoke`: commiteado como herramienta de ops**, no
  descartable — el mismo round-trip se corre en S10 contra el `.env`
  prod. Incluye chequeo negativo: GET sin firma al bucket de documentos
  debe fallar.

## Hallazgos

- **Semántica R2 vs AWS S3:** ante un GET sin header `Authorization`,
  R2 responde **400** (request malformado), no 403 como AWS. "S3-
  compatible" cubre la API firmada, no los bordes de error. Documentado
  en el propio `r2_smoke` (acepta 400/401/403; 200 = incidente).
- **Tercer fósil de la generación vieja:** `docs/setup/development.md`
  documentaba `R2_BUCKET_NAME`/`R2_CUSTOM_DOMAIN` y un fallback a
  `FileSystemStorage` que ya era falso (vars sin default). Corregido y
  commiteado en sesión.
- **El estado del sistema del prompt estaba desactualizado en tests:**
  los services de media YA tenían cobertura
  (`TestUploadPropertyMedia/SetCoverMedia/DeletePropertyMedia`). La
  auditoría encontró 4 huecos reales, saldados: media-sin-cover vuelve
  cover al próximo upload, `actor=None` (obligatorio por `testing.md`,
  faltaba), idempotencia de `set_cover_media`, y pin del
  comportamiento de borrar el cover (ver deuda).
- La atomicidad de `set_cover_media` (crash entre `update` y `save`)
  no es testeable sin mockear ORM — se testea la invariante en estados
  finales; el `transaction.atomic` es materia de code review.

## Deuda nueva

| Deuda | Ventana sugerida |
| --- | --- |
| Borrar el cover no promueve otra foto; presentación inconsistente (list: sin imagen; detail: fallback a `media_list[0]`). Test-pin del comportamiento actual en `TestDeletePropertyMedia` — cambiarlo debe ser deliberado | S2 (decisión UX de portada) |
| Seed con upload real de placeholders (flag opt-in `--with-r2-uploads`) si dev necesita imágenes visibles | S3, solo si duele |
| `r2_smoke` en el checklist de deploy | S10 |

## Estado final

- **Hecho:** `storage.py` una sola generación; settings sin fósiles;
  7 call sites migrados; `.env` dev poblado y validado con round-trip
  real (credenciales, base URL r2.dev, presigned, privacidad de
  documents, deletes); seed EN VERDE (12 PropertyMedia, 6 covers);
  12 tests nuevos de storage + 4 de services de media; docs
  (`infra.md`, `development.md`) reconciliadas.
- **Abierto:** nada propio de S1.
- **Roto a propósito:** nada — el rojo del seed quedó resuelto.

## Para el roadmap

S1 CERRADA — destraba el camino crítico R2 → UI: S2/S3 quedan sin
bloqueo de backend. Roadmap §4 pierde su primera entrada (seed rojo).
