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

## UX safeguards and session labels

Session names are optional persisted labels; never replace or derive session IDs
from them. `PUT /api/content-sessions/{session_id}/name` accepts `name` (1–80
characters) and `expected_version`; `name: null` requests an optional AI suggestion.
Ownership and active-job checks apply. Naming runs during first extraction or when
an older unnamed session with saved facts/draft is opened through the frontend
adapter. A persisted attempt flag prevents repeated calls after failure; manual
names take precedence. `facts_extracted` records extraction even with empty output;
older sessions also use extracted fields/successful analysis logs as evidence.

Repeated extraction, draft regeneration and post re-creation share a native modal
confirmation hook. Alternatives open the existing revision agent or update flow
only when usable. Media drag-and-drop reuses the existing uploader and backend
validation. Template links come from the active post type's workbook configuration.
See README for user-facing behavior and the configurable workbook test command.

The recording widget animates its decorative bars as a staggered wave only while
recording. Reduced-motion preferences keep them static; the existing Recording
label remains visible. This is a recording indicator, not microphone-level data.

## Internal-link editing

`selected_links` is the persisted session candidate list; `excluded_link_ids`
records explicit removals across regeneration. `GET /{session_id}/links` returns
eligible workbook links, the candidate maximum, actual placed-link IDs/fields,
linkable ACF fields and local destination suggestions using the session snapshot.
`PUT /{session_id}/link-candidates` supports add/remove/refresh. `POST
/{session_id}/links` wraps a selected source-text range in an HTTP(S) link. These
mutations require ownership, no active job and the expected session version.

The Content screen reuses the existing revision job for free candidates. Explicit
link requests first use deterministic injection, then one focused structured AI
revision for unresolved destinations (provider/schema retries still apply).
Field choice is local; examples and unrelated fields are excluded from fallback
context. Existing anchors are masked with per-request slots before the model
rewrite and restored byte-for-byte afterward by `protect_links`/`restore_links`.
The model sees readable anchor text separately, without the existing link markup.
Model-created anchor tags are unwrapped before the app injects configured URLs;
slot integrity and the existing-link check still guard the saved result. No requested-link placement is saved if any request or final validation
fails. HTML source edits use the small parser in `internal_links/step_02_editor.py`;
selection offsets are converted from browser UTF-16 units. Removing a placed link
or inserting a manual link rebuilds the payload and clears approval. The legacy
`ai_assisted_link_placement` API parameter is accepted but ignored by this flow.
See README for user behavior and `backend/tests/test_link_workflow.py` for tests
with arbitrary post-type/field keys and an unrelated industry.

## Editorial quality check

Review instructions use the `instruction_de` property consumed by
`structured_task_input`; an `instruction` property is silently omitted from system
rules. The reviewer follows `session.language` and ignores template placeholders,
shortcodes, HTML and inline-style critiques in its summary, findings and rating.
This is editorial-review policy only; source content and validation are unchanged.
Targeted revisions retain `quality_check` and prune findings only for explicitly
requested fields with changed values after a successful non-link-only revision.
`applied_finding_count` and `last_applied_at` track that action. The UI shows
remaining counts and retains the original diagnostic as collapsed reference;
ratings are not recalculated without a new review. Failed/no-op revisions and
link edits preserve remaining findings. Full regeneration clears the report.


## External-link targets

The container passes each client's configured `wp_base_url` to its session service
and `PayloadBuilder`. `payloads/step_03_link_targets.py` adds `_blank`/`noopener` to
external HTTP(S) anchor tags in WordPress and ACF payload values, including nested
ACF structures. It reuses source offsets from `LinkMarkup` to preserve text and
unrelated HTML. No other client's domain is used when configuration is absent.
Session reads project this rule onto the returned payload without writing source
or storage; publication applies it before payload diffs, including text-only
updates. This makes existing posts show pending changes and lets the normal update
button apply the policy without regeneration. Published payloads retain the new
attributes so subsequent unchanged updates stay synchronized.

## Required outputs added to older drafts

Targeted generation extends the requested field scope with missing/empty required
shared and eligible ACF outputs from the active workbook. Existing populated,
unselected fields remain unchanged. Fact-derived outputs are filled locally;
AI-generated outputs use the existing generation groups and filtered context.
Link-only revisions also fill required outputs when necessary. Full validation
still runs before saving, and failure preserves the saved draft. No placeholder
values or client-specific field names are used to bypass required-field checks.
`GET /{session_id}/draft-fields` returns eligible output descriptors from the active
workbook with ownership checks. The frontend merges blank display slots with
saved values; reading metadata does not persist placeholders. Newly configured
fields are valid explicit revision targets. Manual draft edits use the current
workbook when rebuilding the payload, so newly added fields are routed correctly.

## Dev-only client usage report

`GET /api/content-sessions/_usage-report` aggregates the stored per-call
`ai_usage.calls` of the active client's sessions by day, ISO week and month (grouped
by service, model and call name). It returns 404 when `RENDER` is set. The Other
functions drawer shows its "All client uage report" button (label as requested) only when
`NODE_ENV === "development"`; it opens a dialog. Each session keeps its last 500
calls, so very large sessions undercount; calls without a timestamp are "undated".
Tests: `backend/tests/test_usage_report.py`.

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

## Proposals (not implemented)

[google_drive_workbooks_proposal.md](google_drive_workbooks_proposal.md) designs
Google Sheets-hosted client workbooks (phase 1) and natural-language workbook
edits (phase 2). Treat it as a proposal; current code still uses GCS/local files.

[seo_keyword_intelligence_plan.md](seo_keyword_intelligence_plan.md) plans keyword
proposals from live WordPress/Search Console scans and a deterministic SEO check.
Not implemented.

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

## Model migration (2026-11-11)

`backend/model_settings.py` owns text-model choices and legacy-ID/effort aliases.
Generation defaults to Sol, smaller-model roles (including vision) to Terra.
Provider construction handles old environment values; session/API validators
handle saved settings without bulk-editing client storage. The picker uses the
shared model choices. Responses schemas and prompts are unchanged. See README
for cost-estimate limitations and the Sol promotional pricing expiry. Regression
coverage is in `backend/tests/test_model_migration.py`.

Local dev workbook (2026-11-13): `data/knowledge/flairlab workbook-DEV.xlsm`; run
workbook tests with `V2_TEST_WORKBOOK` pointing at it (261 passed, the same 8 known
failures). The app itself still loads `{client_id}.xlsm`, so that file name is not
picked up automatically.

Migration validation: 11 targeted checks passed; frontend typecheck and lint
passed (38 existing warnings). Full V9 workbook suite: 247 passed, 8 known
failures (3 workbook expectations, 2 production-auth checks, 3 image-metadata
mock signatures). No paid API calls or live model-access verification performed.
