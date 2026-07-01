# FLAIRLAB V2 Implementation Status

## Architecture

V2 lives under `app/v2` and does not add business logic to the V1 monolith.
The existing application mounts `/api/content-sessions` through a narrow router.
`main.py` is the readable deployment entry point.

Implemented:

- immutable typed workbook snapshot;
- SHA-256 workbook version pinning per session;
- exact startup validation with stable row-level errors;
- explicit post-type routing;
- typed session model with optimistic file and GCS repositories;
- workbook state machine;
- registered non-`eval` conditions;
- required-fact clarification and correction precedence;
- field-addressable context selection;
- deterministic story/style/SEO filtering;
- internal-link filtering, ID-based selection and Python HTML rendering;
- workbook-driven WordPress/Yoast/ACF payload routing;
- deterministic aggregation transform registry;
- structured OpenAI response parsing with dynamic Pydantic schemas and targeted retry;
- OpenAI transcription and Vision adapters;
- secure multipart audio/image upload validation;
- workbook-driven Pillow processing with preserved originals;
- local and GCS object-storage adapters;
- workbook-driven image metadata generation;
- direct WordPress provider with media, ACF, Yoast, categories, tags and slug idempotency;
- required-field and length validation before review;
- session ownership enforcement;
- structured V2 request logging;
- V2 lifecycle API and switchable V2 interface with a red critical-error modal.

## API routes

- `POST /api/content-sessions`
- `GET /api/content-sessions/_workbook`
- `POST /api/content-sessions/_workbook/reload`
- `GET /api/content-sessions/_readiness`
- `GET /api/content-sessions/{session_id}`
- `POST /api/content-sessions/{session_id}/inputs`
- `POST /api/content-sessions/{session_id}/uploads`
- `POST /api/content-sessions/{session_id}/analyze`
- `POST /api/content-sessions/{session_id}/answers`
- `POST /api/content-sessions/{session_id}/generate`
- `GET /api/content-sessions/{session_id}/preview`
- `POST /api/content-sessions/{session_id}/approve`
- `POST /api/content-sessions/{session_id}/publish`

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CONTENT_PIPELINE_VERSION` | `v1` | UI/default-flow migration switch |
| `V2_KNOWLEDGE_WORKBOOK_PATH` | V5 repository path | V2 source-of-truth workbook; never falls back to a V1 workbook |
| `V2_SESSION_ROOT` | `data/v2_sessions` | Initial file-backed V2 session repository |
| `V2_SESSION_GCS_PREFIX` | empty | GCS session and object root for Cloud Run |
| `V2_LANGUAGE_MODEL` | `gpt-5.5` | OpenAI model used for structured text tasks |
| `V2_VISION_MODEL` | `gpt-5.5` | OpenAI model used for structured image analysis |
| `V2_TRANSCRIPTION_MODEL` | `gpt-4o-transcribe` | Speech-to-text model |
| `V2_MAX_IMAGE_BYTES` | 20 MiB | Maximum image upload size |
| `V2_MAX_AUDIO_BYTES` | 50 MiB | Maximum audio upload size |

## Local run

```bash
export V2_KNOWLEDGE_WORKBOOK_PATH=/absolute/path/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm
export V2_LANGUAGE_MODEL=YOUR_STRUCTURED_OUTPUT_MODEL
export V2_VISION_MODEL=YOUR_VISION_MODEL
export CONTENT_PIPELINE_VERSION=v1
myenv/bin/uvicorn main:app --reload
```

The familiar interface remains at `/` and `/app`. When
`CONTENT_PIPELINE_VERSION=v2`, a compatibility adapter routes its core workflow
to `/api/content-sessions`; the small `/v2` page remains a developer-only fallback.

## Test command

```bash
V2_TEST_WORKBOOK=/absolute/path/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm \
  myenv/bin/python -m unittest discover -s tests/v2 -v
```

Current result: **77 tests passed** on June 29, 2026.

Old-UI/V2 browser smoke command:

```bash
CONTENT_PIPELINE_VERSION=v2 IMPORT_API_KEY=browser-smoke-key \
  V2_BROWSER_SMOKE_ROOT=/tmp/flairlab-v2-browser-smoke \
  myenv/bin/uvicorn tools.v2_browser_smoke_app:app --host 127.0.0.1 --port 8765

V2_BROWSER_BASE_URL=http://127.0.0.1:8765 node tools/v2_browser_smoke.js
```

Current result: **passed** on June 27, 2026. The smoke test drives the
familiar UI through API-key startup, session creation, transcript save,
required-fact review/correction, draft generation and field save. It does not
publish to WordPress.

The V2-backed familiar interface supports session creation, audio/image upload,
transcription and analysis, explicit fact confirmation, generation, direct field
editing, approval and publication. V1-only controls are visibly disabled instead
of calling legacy endpoints.

## Migration status

The local implementation is functionally complete behind provider configuration.

Still pending:

- comparison tests against V1;
- staging WordPress publication and final UI acceptance;
- production verification of GCS permissions and registered WordPress REST meta/ACF fields;
- final decision to switch `CONTENT_PIPELINE_VERSION=v2`.

Business/content prompts come from the workbook. Code contains only technical transport
instructions enforcing schema-only output and prohibiting invented facts/URLs, plus a
deterministic German clarification fallback. If desired, that fallback can be moved into
the workbook before production.

## Intentionally untouched legacy files

The V1 CSV/ZIP/import modules remain operational and are not called by V2:

- `app_draft_generator.py`
- `legacy/run_event_import.py`
- `legacy/action_api_event_import.py`
- `legacy/step_10_event_payload.py`
- `legacy/step_20_prepare_images.py`
- `legacy/step_21_compress_photo.py`
- `legacy/step_30_wordpress_payload.py`
- `legacy/step_50_batch_workflow.py`
- `legacy/step_51_drive_sync.py`
- `legacy/step_52_processed_files.py`

## Cleanup recommendation

Retire the legacy modules only after provider integration, full V2 API/UI tests,
comparison tests and staging publication succeed.

## Remaining risks

- `gpt-5.5` is the current configured default; representative production-content
  quality and cost still require acceptance evaluation.
- Staging WordPress does not yet expose `related_links_html` or the two Yoast
  Open Graph destination keys required by V5.
- A staging publication has not been performed because it creates external state.
- GCS IAM and object-generation preconditions require deployment-environment testing.
- V1/V2 representative comparison remains required before changing the default switch.

A reviewable compatibility plugin is available at
`wordpress/flairlab-v2-rest-compat`, with an uploadable package at
`dist/flairlab-v2-rest-compat.zip`. It has not been installed or activated on staging.

## Current local configuration check

- OpenAI API key: configured
- WordPress URL/username/application password: configured
- `V2_LANGUAGE_MODEL`: defaults to `gpt-5.5`
- `V2_VISION_MODEL`: defaults to `gpt-5.5`
- `V2_SESSION_GCS_PREFIX`: not configured

Live preflight and smoke evidence:

- `gpt-5.5` model access: passed
- synthetic structured-output call: passed
- synthetic Vision structured-output call: passed
- complete synthetic V2 analysis/generation call: passed
- old-UI/V2 browser smoke without WordPress publication: passed
- confirmed date `24.06.2026` preserved exactly
- unconfirmed bartender/focus/challenge/solution facts omitted
- facts HTML generated without escaped list markup
- WordPress authentication/capabilities: passed
- WordPress destination contract: blocked by the three fields listed above

Paid API calls remain excluded from automated tests. The explicit synthetic smoke
result is recorded in `data/audits/v2_live_generation_smoke.json`; it created no
WordPress post.
