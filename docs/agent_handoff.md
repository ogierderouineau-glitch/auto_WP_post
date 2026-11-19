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

The implemented workflow has Media, Facts, Keywords, Content and WordPress screens:
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

## PDF documents as context (e.g. a CV)

The Media screen has "Add a PDF document" under the picture format selector.
`POST /{session_id}/documents` reads the PDF's text with `pypdf` (`extract_pdf_text` in
`backend/app/storage/step_02_uploads.py`: max 30 pages, 30 000 characters, `V2_MAX_DOCUMENT_BYTES`
default 10 MB, text PDFs only, scans are refused with a clear message) and stores it in
`session.document_texts` (file name -> text). The PDF file itself is not kept. Fact extraction receives it as
`documents`, facts get `source="document"` when it is the only text, and the generation context lists it
under `source_text`. Removal uses `DELETE /media/documents/{filename}`. The UI warns that the text is sent
to the AI provider. `remove_personal_data` first replaces emails, links, IBANs, labelled birth dates and phone numbers with `[removed]` (regex only: addresses and names are NOT removed; the UI says so). Session-wide only (not per picture); DOCX is not supported. Tests: `test_document_upload.py`.
Not checked in a real browser or with a real multi-column CV yet.

## Media upload from a link

The Media screen has a "paste a link" field under the picture format selector.
`POST /{session_id}/fetch-media` (`download_media_url` in
`backend/app/storage/step_02_uploads.py`) downloads a public image/MP4 link into a
temp file and returns it; the frontend (`fetchMediaFromUrl`) wraps it in a `File` and
calls the normal `uploadFiles`, so validation, vision and retries are unchanged.
Guards: http(s) only, hosts resolving to non-public IPs refused, redirects followed
manually (max 3) with the same check, size cap `V2_MAX_VIDEO_BYTES`, HTML pages
refused (share-page links from Drive/Dropbox/WhatsApp are not direct file links).
Residual risk: DNS rebinding between check and download is not covered.
Tests: `test_media_link_download.py`. Not checked in a real browser yet.

## Video cover

New videos get an automatic poster (frame at 0.5 s). The "Change cover" button next
to "Remove video" calls `PUT /{session_id}/media/videos/{filename}/cover` (picture
validated like an upload); `replace_video_cover` converts it to a JPEG (max 1280 px)
and overwrites the poster at the same storage key, so the `video_poster` ACF flow is
unchanged. Choosing a cover before the upload is not implemented. Already
published posts need the normal update flow to pick up a new poster.

## Videos from the client's WordPress library

A pasted link on the client's own `wp_base_url` host that resolves (REST search by
file URL, `wordpress_api.find_media_by_url`) to a `video/*` media item is registered by
`POST /{session_id}/wordpress-video` (`attach_wordpress_video`): no download, GCS copy
or ffmpeg. `processed_videos` gets `wp_media_id`/`source_url`; publication media carries
`wp_media_id`, so the provider reuses the attachment instead of uploading. Other links
return `session: null` and fall back to the normal download. Title/caption/description
are loaded into `video_metadata` with `keep_existing_metadata: true` (checkbox "Don't
overwrite metadata", default on): generation then fills only empty fields; unticked, it
regenerates everything. Publishing writes the metadata row back to the library item.
"Change cover" uploads the picture as a new image and sets the poster field.
Needs a live WordPress test; only mocked tests exist.

Featured video: `PUT /{session_id}/featured-video` (`set_featured_video`) flags one
`processed_videos` row `is_featured` (requires a cover) and demotes a featured picture;
`set_featured_image` clears the flag. The video's poster payload item then carries
`image_usage: "featured"`, so the provider sets it as `featured_media` (WordPress needs an
image). The publishing checklist's "Featured image assigned" accepts a featured video.

Video ACF destinations are the post type's enabled `direct_acf` rows whose name ends
with `video_url` / `video_poster` (a hard-coded exact name used to drop videos silently
for post types such as `event_video_url`).

Invalid workbook: an upload is validated before it replaces the live file, so a rejected upload changes
nothing. If the live file itself is invalid (edited by hand), `GET /_workbook` answers normally with
no post types and `workbook_error` (one line per problem); the Other functions drawer shows it next to
the upload button. Other routes that need the workbook still fail with the same message.

Taxonomy-backed facts: an `input_fact` row whose key is the `acf:<fact>` source of a `taxonomies`
row (value_type `list` or `string`) is limited during fact extraction to the existing WordPress
terms of that taxonomy (`_fact_term_choices` in step_03_service.py, `term_choices` in
`build_fact_extraction_model`; the terms are also sent to the model as `allowed_terms`). The model
matches the transcript to a term by meaning, so the row's `guidance_de` should say so. If
WordPress cannot be reached the fact falls back to free text and a milestone line is logged. Needs
a live test; only mocked tests exist. Limit: one enum per fact, the longest list today is 75 terms.

Relationship / post-object ACF fields (the WordPress schema lists `items: integer`) only
accept lists of post IDs. At publish time `_prepare_acf_payload` turns the names in such a
field (text split on `;` and `,`, or a list) into IDs with `find_linked_posts`
(backend/wordpress_api.py). The only workbook input is the `validation_rule` of the
`direct_acf` row: `lookup:taxonomy=<slug>[,category=<name>][,type=<rest_base>]` (flairlab:
`lookup:taxonomy=barkeeper,category=auto bartender post` on `mitwirkende`;
`lookup:taxonomy=highlight` on `video_highlights`). The name is matched to a term of that
taxonomy (existing `match_registered_term`, so accents/case and close spellings work as for
taxonomy assignment); the published posts carrying the term are the candidates, optionally
limited to `category`. When several posts carry the term, the ones titled with the name (exact, or starting with it plus a space) are preferred, so a profile is picked over an event post tagged with the same person; without such a title match all stay and the user chooses. The post types searched are the ones WordPress lists for the taxonomy
(`/wp/v2/taxonomies`, attachments excluded; `type=` in the rule overrides this), so taxonomies of
custom post types work without configuration. A "not found" warning says which step failed
(term missing, or term found but no published post carries it). Posts of the kind being published (the current post type's
`wp_category_name`) are always excluded, so a video never links to another video. Without
`taxonomy` the post title is matched instead. A name is used only when exactly one post
matches. Unknown, ambiguous or unconfigured names are omitted
and reported in `wordpress_result.warnings`, shown in a box on the WordPress screen; this
avoids WordPress's HTTP 400 "Invalid parameter(s): acf". Limits: no interactive "pick one"
step, no read-back check, the ACF field's own filters cannot be read (no ACF REST route),
published posts only, at most 100 posts per lookup, a few WordPress requests per name on
every publish. Needs a live WordPress test; only mocked tests exist.

Media consistency: every payload rebuild, including the one at publish time, builds media with
`_publication_media` so entries carry the same `binary_revision` (and `image_analysis`). Building
them differently at publish made the stored published payload differ from any later rebuild and
flagged unchanged pictures after every ACF edit. Sessions published before this fix are flagged
once; the provider does not re-upload (paths equal). The provider also checks that a remembered
WordPress media ID still exists (`wordpress_media_exists`) and uploads again if it was deleted.

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

`POST /{session_id}/update-workbook` (`ContentSessionService.update_workbook`, icon button on the
facts screen and next to the search box on the content screen) moves a session to the newest
workbook without an AI revision. Without a draft only the workbook version moves; the page then
reloads its workbook status (`session.workbook_hash` is an effect dependency in page.tsx), which
is what the facts screen builds its fact fields from. With a draft: new fields appear in `draft-fields`, empty fact-derived ACF fields are
filled, and the WordPress payload is rebuilt (approval resets). AI-written new fields stay
empty until revised. Regeneration still refreshes the workbook itself (`_on_latest_workbook`).
Optional `derived_from_facts` ACF fields that the AI never writes (`include_in_ai_schema` FALSE, e.g.
relationship fields) stay listed in `draft-fields` even when their source facts are not confirmed, so
the user can type the value (names for a `lookup:` rule) instead of the field being hidden.

## Memory and capacity (Render)

The backend runs on a Render **Starter** instance with **512 MB RAM** in one uvicorn process; the
frontend (free plan) only proxies `/backend/...` to it. When the backend runs out of memory Render
restarts it, and the frontend proxy answers 500 (often seen on the login screen) until it is back.

Incident 2026-11-17: the instance failed 11 s after a video upload. Cause: the ffmpeg re-encode
in `backend/app/videos/step_01_processor.py` (default: all CPU cores, preset medium) peaked at
~810 MB on a 20 s 1080p test clip. Now one thread + preset veryfast: ~280 MB (about 1.6x slower
on that clip). Memory was measured locally with `/usr/bin/time -v ffmpeg ...`; not re-checked on Render.

The frontend (`lib/api.ts`, `failureMessage`) turns a bare 5xx into "The server is temporarily
unavailable (it may be restarting)...", and `app/page.tsx` keeps the saved access key unless the
backend answered 401 (before, any error on page load logged the user out).

Settings to revisit when the Render plan gets more memory (environment variables, set in Render):

| Variable | Default | What it controls | Memory effect |
|---|---|---|---|
| `V2_FFMPEG_THREADS` | 1 | Threads ffmpeg uses to re-encode an uploaded video | Biggest lever: ~280 MB at 1, ~390 MB at 2, ~590 MB at all cores (1080p test clip) |
| `V2_VISION_CONCURRENCY` | 3 | How many uploaded pictures the AI "vision" step analyses at the same time. Each one holds its decoded picture in memory | Each extra one adds one decoded picture (a 48 MP photo is ~150 MB) |
| `V2_ACF_GENERATION_WORKERS` | 6 | Parallel AI calls when generating content fields | Small per call (text only); mainly an API rate-limit setting |
| `V2_SESSION_JOB_WORKERS` | 2 | Background jobs (e.g. keyword proposal) running at once | Small |
| `V2_MAX_IMAGE_BYTES` / `V2_MAX_AUDIO_BYTES` / `V2_MAX_VIDEO_BYTES` | 20 / 50 / 250 MB | Upload size limits (uploads stream to disk, not memory) | None directly |

Not yet protected: pictures are decoded at full resolution (see `images/step_02_processor.py`,
`step_02_uploads.py`). If Metrics → Memory shows spikes on picture uploads, downscale on load.

## User-facing error messages

Rules are in AGENTS.md. Helpers: `backend/app/errors.py` (`explain`, `report_hint`, `ai_failure_message`,
`size_label`, `SessionVersionConflictError`), `unexpected_error_handler` in `api/step_02_routes.py`
(registered in `main.py`; logs the traceback under a reference id shown to the user), WordPress
wording in `backend/wordpress_api.py`. `V2_SUPPORT_CONTACT` (set in `render.yaml` to the clients-only
bug-tracker Google Sheet; an email also works) is what "report this" messages point to; without it they
say "the person who runs this app". Raw errors stay in the message as "(Technical details: ...)"; the
frontend `components/error-text.tsx` folds them behind a "Show technical details" toggle. The Other functions drawer has a "Bug tracker" button (top bar) using `NEXT_PUBLIC_BUG_TRACKER_URL` (frontend env, read at build time; hidden when unset).

## Dev-only client usage report

`GET /api/content-sessions/_usage-report` aggregates the stored per-call
`ai_usage.calls` of the active client's sessions by day, ISO week and month (grouped
by service, model and call name). It returns 404 when `RENDER` is set. The Other
functions drawer shows its "All client uage report" button (label as requested) only when
`NODE_ENV === "development"`; it opens a dialog. Each session keeps its last 500
calls, so very large sessions undercount; calls without a timestamp are "undated".
Tests: `backend/tests/test_usage_report.py`.

## Keyword proposal

`POST /{session_id}/keywords-job` runs `ContentSessionService.propose_keywords` as a
session job; the job reports `stage` ("Scanning WordPress", "Reading Search Console",
"Analysing keywords"). It scans live (no cache) through `backend/app/keywords/step_03_sources.py`:
posts whose category name equals the post type's `display_name_de` or `wp_category_name`
(for custom post types with no matching category, the whole collection), plus
internal-links rows in the client's `seo.service_link_category`. Search Console is
optional (`search_console` in `clients.json`, see deployment.md) and its failure is
reported in `keyword_proposal.notes`. `backend/app/keywords/step_02_service.py` makes one
structured call and verifies the answer in code. The result is stored in
`session.keyword_proposal`; `PUT /{session_id}/keywords/selection` stores
`session.selected_keywords` (up to 12). Generation adds `selected_keywords`,
`keyword_alternatives` and `keyword_conflicts` (site-wide focus keyphrase → URLs, the
post's own URL excluded) to every generation payload once a proposal or selection
exists; the client's workbook instructions (`client_010`, `client_015` for the pilot)
decide how to use them. Without a keyword step, the first generation of a session runs the WordPress scan
(no Search Console, no model call) to fill `site_focus_keyphrases`; a failed scan never
blocks generation. The scan is stored with the session (`site_scanned_at`) and is not
repeated. Internal-link ranking gives selected keywords and their alternatives extra
weight (`InternalLinkService.rank(keywords=...)`, used for generation and candidate
refresh). Search Console numbers are the last-3-months totals per query (the console's "3 months" view) and the
click change versus the 3 months before; the exact phrase match ignores case, spaces and hyphens, and
`keywords/step_04_measure.py` adds up to 3 related searches (shared meaningful words; words found in more than
5% of all queries do not count alone). The busiest 1,000 queries are stored in `keyword_proposal.queries`, so
keywords typed in by hand get the same numbers in `keyword_proposal.custom`. Typed-in keywords survive a new
search; earlier proposals that are no longer listed are dropped from the selection.
Screen 3 (`frontend/components/keywords-screen.tsx`, step between Facts and Content) starts the job, shows
the stage progress and a table of proposed keywords with alternatives, status, Search Console numbers and
related pages, and autosaves the multi-selection (first keyword = focus, changed with the star; custom keywords
allowed; skipping lets the AI choose). The recording widget is hidden on this screen. Not checked in a real
browser yet. Plan: [seo_keyword_intelligence_plan.md](seo_keyword_intelligence_plan.md).
Tests: `test_seo_sources.py`, `test_keyword_service.py`, `test_keyword_workflow.py`.

## SEO check

The Content screen's Quality check container (shown once a draft exists) has two subsections: the existing AI content
review and the SEO check. The SEO check (`GET /{session_id}/seo-check`, `validation/step_02_seo.py`) is deterministic,
workbook-driven (`seo_rules` rows with `action_type` `check_role` / `check_length`, `stage` `quality_check`) and
unsaved. "Revise N fields" selects the failing fields and opens the existing content agent with the failed checks as
the instruction; revisions use the normal job. Details and pilot rows: [seo_keyword_intelligence_plan.md](seo_keyword_intelligence_plan.md).
Tests: `test_seo_check.py`. Not checked in a browser yet.

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

[seo_diagnostic_proposal.md](seo_diagnostic_proposal.md) proposes an optional site
SEO diagnostic and a new Screen 3 (Keywords). Not implemented.

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
