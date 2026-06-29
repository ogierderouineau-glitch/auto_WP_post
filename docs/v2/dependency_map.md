# V2 Repository Dependency Map

## Existing reusable infrastructure

| Concern | Existing implementation | V2 treatment |
|---|---|---|
| FastAPI/Cloud Run | `app_main.py`, `Dockerfile` | Retained; V2 mounted through a narrow router and `main.py` entry point |
| Environment configuration | `config.py` | Retained; V2 adds isolated workbook/session/version settings |
| WordPress authentication/API | `step_40_wordpress_api.py` | Candidate for a provider adapter; not called by V2 foundation yet |
| Transcription | `app_transcription.py` | Candidate for `SpeechToTextProvider` adapter |
| GCS | `app_main.py`, `tools/knowledge_workbook_audit.py` | Candidate for repository/storage adapters |
| Pillow processing | `app_main.py`, `step_21_compress_photo.py` | Values replaced by workbook-driven V2 rules in the future image adapter |
| Existing UI | inline HTML/JS in `app_main.py` | V1 remains operational; V2 compatibility adapter routes the core old-UI workflow |

## Legacy-only flow

`app_draft_generator.py`, `run_event_import.py`, `action_api_event_import.py`,
`step_10_event_payload.py`, and `step_50_*` retain CSV/ZIP behavior for V1.
No module under `app/v2` imports or invokes them.

The old-UI/V2 compatibility adapter also does not call the legacy CSV/ZIP
workflow. It talks to `/api/content-sessions` and disables V1-only controls
that have no V2 equivalent.

## V2 dependency direction

`API → session service → domain services → provider/repository interfaces`

`session service → immutable workbook snapshot`

`context / clarification / links / payloads → typed workbook models`

Provider implementations may depend on existing infrastructure; domain services do not.
