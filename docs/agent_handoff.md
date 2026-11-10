# Speech2Post coding-agent handoff

Verified against the repository on 2026-11-10. This is the current continuation
guide, not a claim that every feature has passed a live end-to-end test.

## Read first

1. Read [AGENTS.md](../AGENTS.md) for mandatory project priorities.
2. Read this guide for architecture, local setup and known gaps.
3. Use [README.md](../README.md) for workbook configuration and
   [deployment.md](deployment.md) for deployment configuration.
4. Inspect the relevant implementation and tests before changing behavior.
   If code and documentation disagree, report the mismatch and update the docs
   with the change; do not silently treat an old plan as implemented behavior.

The active task is the user's current request. There is no confirmed remaining
phase list or authorization to implement the historical roadmap automatically.

## Current architecture

Speech2Post is one multi-client application for different industries. Each active
client supplies its own workbook, credentials and storage paths. Shared runtime
logic must not encode one client's industry, post types, fields or writing rules.

The Next.js frontend is **`frontend/`**, not `speech-2-post-ui/`. The old FastAPI
`/app` UI is no longer served. Backend routes under `/app/knowledge/workbook`
remain active API endpoints; their names do not imply a legacy UI to preserve.

The implemented workflow has Media, Facts, Content and WordPress screens:
sessions, uploads/recording, transcription/analysis, fact corrections, draft
generation/revision, image metadata and processing, approval and publication.
Long operations also have job endpoints with polling. Extend these existing
features rather than building a second backend or parallel workflow.

| Area | Start here |
|---|---|
| Frontend shell, auth and session coordination | `frontend/app/page.tsx` |
| Workflow screens and recording | `frontend/components/` |
| HTTP transport and typed API adapters | `frontend/lib/api.ts`, `frontend/lib/content-sessions.ts` |
| Same-origin `/backend/*` proxy | `frontend/next.config.mjs` |
| Backend composition, authentication, workbook upload/download | `backend/main.py` |
| Content-session routes and jobs | `backend/app/api/step_02_routes.py` |
| Per-client service/provider/storage construction | `backend/app/api/step_03_container.py` |
| Session workflow and orchestration | `backend/app/sessions/step_03_service.py` |
| Session models and API request models | `backend/app/models/`, `backend/app/api/step_01_models.py` |
| Workbook loading and validation | `backend/app/knowledge_base/` |
| App-owned workflow rules | `backend/app/knowledge_base/app_owned/` |
| Generation, media, links, payloads and providers | Corresponding folders under `backend/app/` |
| WordPress integration | `backend/wordpress_api.py`, `backend/app/providers/step_03_wordpress.py`, `integrations/wordpress/` |
| Backend regression tests | `backend/tests/` |

Browser requests use `/backend/*`, proxied to FastAPI (locally port 8000).
The content-session API prefix is `/api/content-sessions`. Reuse the existing
transport/adapters and inspect route/request models instead of copying a static
endpoint inventory into new code. The backend owns generation, validation,
media processing and WordPress publication.

## Workbook versus application ownership

Client-owned sheets define post types, shared/ACF fields, SEO constraints,
blueprints, story/style rules, image metadata schema/rules, internal links,
validation choices, examples and client agent instructions. Consult the loader's
`REQUIRED_SHEETS` and models for the exact current schema. Additional
`agent_instructions*` client overlays are supported, except the app-owned sheet.

Workflow/state/context mechanics, Pillow rules, image analysis rules, internal
link mechanics, output specification and app instructions live in
`backend/app/knowledge_base/app_owned/`. Their deprecated workbook sheets are
ignored with a warning. Do not move client business behavior into these modules.

Adding a configured post type should normally require workbook changes, not new
branches in shared code. Check relevant behavior with unrelated industries and
arbitrary post-type keys, not only one client's fixtures.

## Local setup and secrets

Run backend commands from the repository root. Initial setup, if needed:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
```

Use the existing `.venv` when available. A bare system `uvicorn` can use a Python
environment without FastAPI. Start the backend with:

```bash
.venv/bin/python -m uvicorn main:app --reload
```

In another terminal:

```bash
cd frontend
nvm use
corepack pnpm install --frozen-lockfile
corepack pnpm dev
```

`frontend/.nvmrc` selects Node 20; package metadata requires Node >=20.9.0 and
pins pnpm. Install dependencies only when needed. The default backend proxy is
`http://127.0.0.1:8000`; override with `SPEECH2POST_BACKEND_URL` in
`frontend/.env.local` if necessary. Video processing requires system `ffmpeg`.

| Configuration | Local source | Render source |
|---|---|---|
| Shared provider key (`OPENAI_API_KEY`) and model settings | Root `.env`, shell or IDE environment | Service environment variables |
| Client identity, import keys, WordPress credentials and relative storage paths | Root `clients.json` | `/etc/secrets/clients.json` |
| Google credentials, when accessing GCS | Application Default Credentials or `GOOGLE_APPLICATION_CREDENTIALS` | Referenced service-account secret file |

See `.env.example` and the client JSON schema in the deployment guide. Root
`.env` and `clients.json` are ignored by Git. Never print secret values, commit
them, place provider keys in browser code or use another client's credentials.
The backend loads root `.env` on import without overriding existing environment
variables. Restart it after configuration changes. The frontend import key is
distinct from the OpenAI provider key.

Normal local execution uses `data/knowledge/{client_id}.xlsm` (or `.xlsx`) and
`data/v2_sessions/{client_id}`. With `RENDER` set, configured GCS buckets supply
workbooks, sessions and media. Bucket names can be derived from
`GOOGLE_CLOUD_PROJECT`; inspect `backend/config.py` for resolution details.
Merely setting bucket variables locally does not switch normal runtime storage
to GCS. Workbook initialization is lazy, when the client service is needed.

The current backend does not automatically fetch secrets from Render or Google
Secret Manager. The older Cloud Run helpers in `scripts/` are a separate deploy
path, not the current Render runbook. Do not run deployment helpers as a local
startup step.

## Known gaps to account for

These are observations of current code, not desired design or completed fixes:

- Outside Render, authentication accepts any non-empty unknown import key and
  selects the default client (`backend/main.py`). Use the correct configured key
  during client-isolation checks; do not infer production authentication from a
  successful local login.
- Local workbook resolution can fall back to the first `.xlsm` in
  `data/knowledge/` when the requested workbook is missing
  (`_resolve_local_workbook`). This conflicts with the client-isolation priority.
  Supply each client's correctly named workbook; do not rely on this fallback.
- Missing `OPENAI_API_KEY` leaves providers unconfigured. The draft-chat voice
  transcription route currently raises an unhandled error in that case.
- The frontend currently persists its import key in browser local storage and
  sends `X-API-Key`. The historical cookie-login proposal is not implemented.

No live Render configuration or end-to-end production behavior was verified as
part of writing this guide. Do not claim deployment state from repository files.

## Working and verifying changes

Start with `git status --short`; preserve existing user edits. Implement the
smallest complete change for the current request, reuse existing services and
flag substantial complexity before adding it. Avoid unrelated refactoring.

For backend behavior, run relevant tests from `backend/tests/`; the full suite is:

```bash
.venv/bin/python -m pytest
```

For frontend changes, use the relevant checks from `frontend/`:

```bash
corepack pnpm typecheck
corepack pnpm lint
corepack pnpm build
```

Choose checks appropriate to the change. Report what actually passed, what was
not checked and any blockers. Use a browser smoke check for changed UI flows
when available; static checks alone do not establish recording or publication
success. Keep real provider calls and WordPress publication deliberate because
they incur usage or change external content.

When a task changes architecture, configuration, workflow or a known gap, update
the corresponding documentation in the same task. Keep this guide concise;
record future proposals separately and clearly mark them as unimplemented.

## Historical phase plan

`docs/speech2post_local_phases.md` was deleted in commit `340ff18` during the
multi-client refactor. Its last version can be inspected without restoring it:

```bash
git show 340ff18^:docs/speech2post_local_phases.md
```

It contains useful design history, but obsolete paths and unimplemented Secret
Manager, Supabase and cookie-auth proposals. Do not use it as current truth or
restore its old phase checklist as an active backlog without reviewing it.

## Conversation starter

```text
We are working on Speech2Post at:
/home/ogier-derouineau/IT projects/whatsapp_to_Wordpess_post

Read AGENTS.md and docs/agent_handoff.md first, then the relevant code and tests.
The current Next.js frontend is in frontend/; the FastAPI backend is in backend/.
Reuse existing backend services and API adapters; avoid duplicate business logic.
Keep behavior configurable for multiple clients across different industries,
and keep their data and credentials isolated.
Preserve existing uncommitted changes. Update affected documentation as you work.

Current goal: [describe the change and expected behavior]
```
