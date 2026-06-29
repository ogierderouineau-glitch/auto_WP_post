# V2 File Inventory

## Created

- `main.py`
- `app/v2/errors.py`
- `app/v2/observability.py`
- `app/v2/api/step_01_models.py`
- `app/v2/api/step_02_routes.py`
- `app/v2/api/step_03_container.py`
- `app/v2/api/v2_ui.html`
- `app/v2/content_generation/step_01_schema_factory.py`
- `app/v2/content_generation/step_02_prompts.py`
- `app/v2/context/step_01_builder.py`
- `app/v2/images/step_01_conditions.py`
- `app/v2/images/step_02_processor.py`
- `app/v2/internal_links/step_01_service.py`
- `app/v2/knowledge_base/step_01_models.py`
- `app/v2/knowledge_base/step_02_loader.py`
- `app/v2/knowledge_base/step_03_validator.py`
- `app/v2/knowledge_base/step_04_service.py`
- `app/v2/models/step_01_session.py`
- `app/v2/models/step_02_payload.py`
- `app/v2/payloads/step_01_transforms.py`
- `app/v2/payloads/step_02_builder.py`
- `app/v2/providers/step_01_interfaces.py`
- `app/v2/providers/step_02_openai.py`
- `app/v2/providers/step_03_wordpress.py`
- `app/v2/sessions/step_01_repository.py`
- `app/v2/sessions/step_02_state_machine.py`
- `app/v2/sessions/step_03_service.py`
- `app/v2/sessions/step_04_gcs_repository.py`
- `app/v2/storage/step_01_local.py`
- `app/v2/storage/step_02_uploads.py`
- `app/v2/storage/step_03_gcs.py`
- `app/v2/validation/step_01_draft.py`
- `app/v2/workflow/step_01_conditions.py`
- `app/v2/workflow/step_02_clarification.py`
- `app/v2/workflow/step_03_registry.py`
- package `__init__.py` files under `app/v2`
- V2 test modules under `tests/v2`
- V2 documentation under `docs/v2`
- V5 validation reports under `data/audits`
- WordPress REST compatibility plugin under `wordpress/` and packaged under `dist/`

## Modified

- `app_main.py` — narrow V2 router/UI/middleware mounting only
- `config.py` — V2 environment settings
- `Dockerfile` — readable `main:app` startup target
- `DEPLOY_CLOUD_RUN.md` — V2 deployment variables and migration guidance

## Intentionally untouched by V2

Legacy V1 generation/import modules remain available and are not imported by
`app/v2`. See `implementation_status.md` for the cleanup candidate list.
