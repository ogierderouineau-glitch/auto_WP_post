# V2 Requirement Traceability

| Requirement | Implementation | Tests | Status |
|---|---|---|---|
| Typed workbook loading | `knowledge_base/step_01_models.py`, `step_02_loader.py` | `test_knowledge_base.py` | Complete |
| Exact startup validation | `knowledge_base/step_03_validator.py` | duplicate URL/source fact and V5 tests | Complete |
| Workbook version pinning | `step_04_service.py`, `ContentSession.workbook_hash` | API create/get | Complete |
| Explicit post-type routing | `sessions/step_03_service.py` | unknown post type API test | Complete |
| Typed sessions/repository | `models/step_01_session.py`, file and GCS repositories | optimistic version test | Complete |
| State transitions | `sessions/step_02_state_machine.py` | HTTP 409 transition test | Complete |
| Typed conditions/no eval | `workflow/step_01_conditions.py` | manual/image-free tests | Complete |
| Clarification dependencies | `workflow/step_02_clarification.py` | required/optional/correction tests | Complete |
| Field-addressable context | `context/step_01_builder.py` | exact SEO and image blueprint tests | Complete |
| Deterministic links | `internal_links/step_01_service.py` | self/zero-candidate tests | Complete |
| Workbook-driven payload | `payloads/step_02_builder.py` | destination/aggregation test | Complete |
| Provider abstractions | provider interfaces, OpenAI and WordPress adapters | fake-provider and lifecycle tests | Complete |
| V2 routes | `api/step_02_routes.py` | API lifecycle/error/upload tests | Complete |
| No V2 CSV/ZIP | all `app/v2` modules | source scan | Complete |
| Structured AI generation | schema factory, prompts transport, OpenAI provider, session service | structured fake pipeline and schema tests | Complete |
| Image pipeline | Vision adapter, Pillow rules/conditions, metadata generation | Pillow/upload/image-free tests | Complete |
| WordPress publication | direct provider and approval-gated session service | fake complete lifecycle | Complete locally |
| Existing UI migration | `v2_ui.html`, `CONTENT_PIPELINE_VERSION` switch | OpenAPI/import verification | Complete |
| Session ownership/security | API headers, upload validation, safe storage keys | owner and invalid-upload tests | Complete |
| Structured logging | `observability.py` | import/API tests | Complete |
| V1/V2 comparison | report and representative staging inputs | pending | Not started |
| Staging acceptance | `v2_wordpress_staging_preflight.*` | read-only live checks | Blocked by missing REST destinations |
