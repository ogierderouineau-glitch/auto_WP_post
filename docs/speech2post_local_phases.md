# SPEECH2POST Local Implementation Phases

This document keeps the new Next frontend work separate from the current live
FastAPI UI. The current `/app` UI remains the stable working version while the
new SPEECH2POST interface is built locally and connected to the existing V2
services one slice at a time.

## Local Development Shape

- Current backend remains FastAPI: `main.py` / `app_main.py`.
- Current live UI remains available at `/app`.
- New frontend lives in `speech-2-post-ui/` and should become the future
  product UI.
- The folder is tracked by git; generated Next files and dependencies remain
  ignored by `speech-2-post-ui/.gitignore`.
- During local development, run FastAPI and Next as separate dev servers.
- Local MP4 processing requires `ffmpeg`. On Debian/Ubuntu install it once with
  `sudo apt-get update && sudo apt-get install -y ffmpeg`, then restart FastAPI.
- The Next app should call the existing backend API routes instead of creating a
  parallel backend.
- The V0-generated app currently uses Next 16, which requires Node `>=20.9.0`.
- On a machine where system Node is still 18, the frontend can be run with a
  temporary toolchain:
  - `npx -y -p node@20 -p pnpm@10 pnpm install --frozen-lockfile`
  - `npx -y -p node@20 -p pnpm@10 pnpm run typecheck`
  - `npx -y -p node@20 -p pnpm@10 pnpm run build`
  - `npx -y -p node@20 -p pnpm@10 pnpm run dev`
- Production routing/deployment follows the single-client Render showcase gate
  in Phase 11 after local build and workflow verification.

## Future Storage And Secret Direction

These are not part of the first local UI slices, but they should guide later
backend work.

### Secret Manager

- The project already has Google Secret Manager usage. Extend that existing
  pattern instead of adding a separate secret system.
- Use Secret Manager for credentials and signing secrets:
  - client import-key hashes or equivalent login secrets
  - WordPress usernames and app passwords
  - OpenAI/API provider keys
  - auth cookie/session signing secret
  - webhook or integration secrets
- Do not expose Secret Manager values to the browser. The frontend should only
  receive safe client metadata such as `client_id`, display name, status, and
  enabled post types.
- For the future 24-hour login, prefer:
  - browser submits import key once
  - backend validates against Secret Manager-backed client config
  - backend sets an `HttpOnly`, `Secure`, `SameSite=Lax` cookie
  - frontend stops storing or sending the raw import key
- Keep the current `X-API-Key` flow temporarily for local and legacy
  compatibility until the cookie auth path is proven.

### Supabase

- Supabase is a candidate for future structured session storage, especially for
  the new SPEECH2POST workflow.
- Good fit for Supabase Postgres:
  - session records
  - workflow step state
  - transcripts
  - extracted and confirmed facts
  - generated content fields
  - WordPress sync history
  - job status
  - operation logs
- Media files need a careful decision. Supabase Storage may be enough for the
  current expected sizes, but phone photos/audio can grow quickly. Keep media
  as object-storage references in session rows rather than embedding file data
  in Postgres.
- Do not migrate session storage in one jump. Safer path:
  1. keep current local/GCS storage working;
  2. preserve or introduce a repository abstraction;
  3. add a Supabase-backed repository;
  4. use it locally for the new UI;
  5. keep local/GCS fallback until Supabase is proven.
- Supabase credentials belong in Secret Manager or environment variables on the
  backend, never in browser-visible code unless using intentionally public
  anon-key flows with strict Row Level Security.

## Existing Backend Contracts To Reuse

### Authentication And Client Context

- Current auth is header based: `X-API-Key`.
- V2 ownership context is header based: `X-User-ID`.
- Existing validation is the FastAPI dependency used by `/api/content-sessions`.
- Existing client/config helper routes:
  - `GET /clients`
  - `GET /app/wordpress/preflight`
  - `GET /app/knowledge/status`
  - `GET /app/knowledge/workbook`
  - `POST /app/knowledge/workbook`

Known gap:

- There is no secure backend session/cookie that remembers an import key for 24
  hours. Do not emulate this by storing the raw key in `localStorage`.
- When this is implemented, build from the existing Secret Manager integration
  rather than adding a parallel secrets source.

### Workbook And Post Types

- `GET /api/content-sessions/_workbook`
- `GET /api/content-sessions/_workbook?post_type_key=...`
- `POST /api/content-sessions/_workbook/reload`

The workbook response provides selectable post types and the fact schema for the
selected post type. The Next UI should render facts dynamically from this data.

### Workbook Ownership Split (Current)

Client workbook tabs still used by the backend loader:

- `post_types`
- `shared_fields_schema`
- `seo_rules`
- `ACF_fields_schema`
- `post_blueprint`
- `story_patterns`
- `style_rules`
- `image_metadata_schema`
- `image_metadata_rules`
- `internal_links_database`
- `validation_lists`
- `post_examples`
- `agent_instructions`
- optional secondary client overlays: any sheet starting with `agent_instructions`
  except `agent_instructions_app`

App-owned tabs now sourced from typed code and ignored if present in workbook:

- `agent_workflow`
- `application_state`
- `context_building`
- `image_analysis_rules`
- `image_rules_pillow`
- `internal_link_rules`
- `output_specification`
- `agent_instructions_app`

Loader behavior:

- deprecated app-owned tabs are ignored and a warning is logged
- missing client-owned required tabs still fail validation
- `post_types.knowledge_enrichment` is an optional per-post-type policy:
  - blank or `forbidden` keeps generation bound to supplied and confirmed facts
  - `allowed` permits established general knowledge in generated content fields
  - enrichment never applies to fact extraction or creates confirmed/input facts
  - values are validated through the `knowledge_enrichment` family in
    `validation_lists`

### Sessions

- `POST /api/content-sessions`
  - body: `{ "user_id": string, "post_type_key": string }`
- `GET /api/content-sessions/{session_id}`
- `GET /api/content-sessions/recent`
- `POST /api/content-sessions/delete`
- legacy fallback currently exists through:
  - `GET /app/sessions/recent`
  - `GET /app/sessions/{session_id}`
  - `POST /app/sessions/delete`

Known gap:

- The old UI merges V2 and legacy archives. The first Next version can focus on
  V2 sessions, then add legacy archive fallback if still needed.

### Media

- `POST /api/content-sessions/{session_id}/uploads`
  - multipart form:
    - `expected_version`
    - `kind`: `audio`, `image`, or `video`
    - `use_vision`
    - `upload`
- `GET /api/content-sessions/{session_id}/media/images/{filename}`
- `GET /api/content-sessions/{session_id}/media/images/{filename}/original`
- `GET /api/content-sessions/{session_id}/media/videos/{filename}`
- `DELETE /api/content-sessions/{session_id}/media/{kind}/{filename}`
- `PUT /api/content-sessions/{session_id}/video-metadata`
- `PUT /api/content-sessions/{session_id}/featured-image`
- `PUT /api/content-sessions/{session_id}/image-metadata`
- `POST /api/content-sessions/{session_id}/images/optimize`
- `POST /api/content-sessions/{session_id}/images/restore-original?filename=...`

Video behavior:

- Video upload accepts MP4 only and is capped by `V2_MAX_VIDEO_BYTES`
  (250 MiB by default).
- `ffmpeg` creates an H.264/AAC, fast-start MP4 at no more than 1080p and a
  JPEG poster at 0.5 seconds. The source upload is temporary and is not stored.
- Multiple videos are retained in upload order. Only the first remaining video
  is published, outside the image gallery.
- Workbook `field_key` values remain globally unique internal identifiers and
  may differ by post type. The shared `acf_field_name` destinations `video_url`
  and `video_poster` identify the semantic media roles for every post type.
- WordPress receives the uploaded attachment IDs for the ACF File and Image
  fields, which is the canonical stored value for those field types.
- Reordering media is not exposed as a clear V2 endpoint.
- Upload progress is a frontend feature, but final processing progress depends
  on session/job state exposed by the backend.

### Recording And Transcription

- Browser recording is frontend side using `MediaRecorder`.
- General audio files are uploaded through `/uploads` with `kind=audio`.
- Draft-chat style one-off transcription:
  - `POST /api/content-sessions/{session_id}/draft-chat/transcribe`
- Fact extraction / transcription flow is currently driven by:
  - `POST /api/content-sessions/{session_id}/analyze`

Known gaps:

- TR #001 asks for every stopped recording to be transcribed immediately and
  appended to a shared text area. The existing V2 flow can support this with the
  draft-chat transcription endpoint, but the exact saved interaction history
  model should be checked before treating it as durable session data.

### Facts

- Current fact extraction:
  - `POST /api/content-sessions/{session_id}/analyze`
- Correct and confirm facts:
  - `POST /api/content-sessions/{session_id}/answers`
  - body includes `expected_version` and `corrections`
- Session fields:
  - `extracted_facts`
  - `confirmed_facts`
  - `clarification_questions`

Known gap:

- UI grouping into missing required, missing optional, and AI-populated is a
  frontend adapter concern based on workbook schema plus session fact values.

### Content Generation

- Start durable-ish generation job:
  - `POST /api/content-sessions/{session_id}/generate-job`
- Poll job:
  - `GET /api/content-sessions/jobs/{job_id}`
- Save edited generated fields:
  - `PUT /api/content-sessions/{session_id}/draft-fields`
- Agent-directed regeneration:
  - `POST /api/content-sessions/{session_id}/draft-chat`
- Approve content:
  - `POST /api/content-sessions/{session_id}/approve`

Known gaps:

- Existing jobs are in-process memory jobs. They can be polled and survive a
  browser reload if the server process still has them, but they are not a fully
  durable queue.
- Supabase could later hold durable job status rows for the new workflow, while
  long-running work still executes server-side.
- Targeted regeneration is not guaranteed as a fine-grained backend operation.
  The UI can submit an instruction, but it must not claim only one field changed
  unless the returned session proves that.

### WordPress

- Publish immediately:
  - `POST /api/content-sessions/{session_id}/publish`
- Publish as job:
  - `POST /api/content-sessions/{session_id}/publish-job`
- Poll job:
  - `GET /api/content-sessions/jobs/{job_id}`
- Request body supports:
  - `idempotency_key`
  - `target_post_id`
  - `force_create_new`
  - `partial_update`
  - `shared_fields`
  - `acf_source_fields`
- Session fields:
  - `wordpress_result`
  - `published_wordpress_payload`
  - `wordpress_payload`

Known gap:

- The V2 model stores one `wordpress_result`, not a list of previous WordPress
  targets. "Create another post from the same session and preserve all previous
  targets" likely needs a backend model extension.

## Phase Plan

### Phase 1: Contract Map And Local Strategy

Outcome:

- This document exists and is kept updated.
- We agree the new Next app is the future frontend, but the current `/app` UI
  remains untouched and usable.

### Phase 2: Local Next/FastAPI Bridge

Outcome:

- Next dev server runs locally.
- FastAPI backend runs locally.
- Next has a single API client module:
  - `speech-2-post-ui/lib/api.ts`
- Local API base URL is environment-driven:
  - `SPEECH2POST_BACKEND_URL`
- The Next dev server proxies backend requests through:
  - `/backend/:path*`
- No component should call `fetch` directly except through the API client.
- TypeScript build errors are no longer ignored in `next.config.mjs`.
- Local Node must be upgraded from the current Node 18 runtime before `next
  build` or `next dev` can run.
- The local dev script uses `WATCHPACK_POLLING=true next dev --webpack` because
  Turbopack and default Webpack watching hit the OS file-watch limit in this
  workspace.

Risk:

- This adds frontend build/dependency complexity, but contains it inside
  `speech-2-post-ui/`.

### Phase 3: App Shell With Real Auth, Workbook, And Session

Outcome:

- Auth popup validates the key against a real backend route.
- Key is not stored in `localStorage`.
- Workbook/post types load from `_workbook`.
- User can create a V2 session.
- User can load a recent V2 session.
- Top bar displays real client/session/post type/state.
- Four workflow screens are navigable, even if some screen bodies still show
  supported/unsupported states.

Implemented frontend files:

- `speech-2-post-ui/lib/content-sessions.ts`
- `speech-2-post-ui/components/auth-modal.tsx`
- `speech-2-post-ui/components/session-modal.tsx`
- `speech-2-post-ui/app/page.tsx`

Current behavior:

- The access key is kept in `sessionStorage`, matching the current browser-only
  behavior without using `localStorage`.
- Stored sessions are restored from `sessionStorage` when possible.
- The WordPress step is now reachable in the V0 shell.
- Later phases replaced the original V0 screen-body mock data with the real V2
  media, facts, content, and WordPress slices.

Risk:

- Secure 24-hour auth remains a backend gap unless implemented deliberately.

### Phase 4: Media Slice

Outcome:

- Upload images to the active session.
- Display uploaded images from backend URLs.
- Show original vs processed where available.
- Save featured image.
- Save image metadata.
- Trigger image optimize/restore where supported.
- Upload and process MP4 videos alongside pictures.

Implemented frontend files:

- `speech-2-post-ui/lib/content-sessions.ts`
- `speech-2-post-ui/app/page.tsx`
- `speech-2-post-ui/components/media-screen.tsx`

Current behavior:

- The Media screen uses the active V2 session and updates the parent shell after
  each backend response so the session version stays current.
- Image uploads call `POST /api/content-sessions/{session_id}/uploads`.
- The gold Add pictures & videos control uploads pictures through the standard local
  Pillow pipeline without making a paid Vision request. Its format dropdown
  selects a per-upload Pillow crop ratio: portrait `4:5` (the default),
  landscape `4:3`, square `1:1`, or widescreen `16:9`. The ratio is stored on
  the processed record and reused by a later AI recrop.
- On the Media screen only, the recording agent shows the active post type's
  workbook `voice_instructions` in a collapsed speech-structure panel below the
  Record controls.
- Images are fetched as authenticated blobs because current image routes require
  `X-API-Key`/`X-User-ID` headers and plain `<img src>` cannot send those.
- Original and processed images are shown side by side on desktop.
- Featured image, metadata save, per-picture Vision recrop, image optimize,
  restore original, and remove image actions call the real V2 endpoints.
- The gold control is named **Add pictures & videos**. Videos share the media
  gallery, display a video badge and generated poster, and expose title,
  caption, description, transcript, playback, selection, and removal.
- The existing background image-metadata rules and batch generator also produce
  video title, caption, and description after draft generation. The generated
  poster is treated as the video's image record and the per-video transcript is
  supplied as its image context; Vision remains disabled for videos.
- Image-only before/after, featured-image, Vision, crop, restore, and editing
  controls are not shown for videos.
- Recording/transcript controls remain disabled until Phase 5.

Risk:

- Video processing requires `ffmpeg`; the production Docker image installs it.
- Large phone videos can take noticeably longer than image uploads because the
  request remains open while the MP4 is transcoded.
- Once cookie auth exists, media image rendering can switch away from
  authenticated blob fetching to simpler direct URLs.

### Phase 5: Recording Widget TR #001

Outcome:

- Shared recording widget works on supported browsers.
- Start/stop recording.
- Multiple recordings.
- Immediate transcription into the editable combined transcript.
- Screen-specific submit action routing.
- Clear failure/retry states.
- On the Media screen, transcript text is saved at picture level so image
  metadata can later be generated from picture context even without Vision.
- Media-screen fact extraction combines all saved picture transcripts and sends
  them as the session transcript context.

Implemented frontend/backend files:

- `speech-2-post-ui/components/recording-widget.tsx`
- `speech-2-post-ui/app/page.tsx`
- `speech-2-post-ui/lib/content-sessions.ts`
- `speech-2-post-ui/components/media-screen.tsx`
- `app/v2/sessions/step_03_service.py`

Current behavior:

- The floating recording widget is present across the workflow.
- On the Media screen, it follows the selected picture.
- Each stopped recording is transcribed immediately through
  `POST /api/content-sessions/{session_id}/draft-chat/transcribe`.
- The resulting transcription is copied immediately into the visible Picture
  transcript textarea for the selected image.
- The Media screen shows a single selected-picture transcript editor; image
  metadata stays separate from picture context.
- The editable transcript is saved into a dedicated session field,
  `image_context_transcripts`, keyed by image `media_id`. It is intentionally
  not stored as image metadata.
- Submitting from the Media screen saves the selected picture transcript, builds
  a combined transcript from all picture-level transcripts, saves it through
  `/inputs`, then calls `/analyze` and moves to the Facts screen.
- Facts, Content, and WordPress screen-specific agent actions are present as
  placeholders until their phases connect them.

Risk:

- Mobile browser recording behavior is uneven. Expect testing on actual devices.
- `image_context_transcripts` is now preserved separately from image metadata.
  Image metadata generation uses this picture-level context as its primary
  description together with workbook metadata rules. Broad post fields and the
  WordPress payload are intentionally excluded from the metadata prompt.
- The Media screen has two explicit, per-picture Vision actions:
  - `Recrop with AI ($)` requests a fresh focal point, then reprocesses the
    original upload through the standard Pillow pipeline and overwrites the
    current processed object. Starting from the original avoids cumulative
    crop and JPEG quality loss.
  - Each saved picture has an unchecked-by-default metadata Vision checkbox.
    Only opted-in pictures may expose their stored Vision analysis to metadata
    generation. The choice is persisted in `image_metadata_vision` by
    `media_id`.
- Pillow keeps its conservative 60% retained-area crop guard when no focal
  point is available. A valid Vision focal point permits a subject-centered
  4:3 crop down to 35% retained area, allowing panoramic landscape images to
  normalize instead of remaining visibly shorter than the other pictures.
- Pillow measures luminance percentiles and clipped highlights locally before
  enhancement. Backlit images receive a masked shadow lift with protected
  highlights, generally dark images receive bounded gamma correction, and
  low-contrast images receive a mild 20% autocontrast blend. Well-exposed
  images skip adaptive exposure; conservative color, contrast, and sharpness
  finishing remains deterministic and local.
- Generated picture metadata stores a field-addressable rules trace in
  `generation_trace.image_metadata`, keyed by media ID. Alt text, title,
  caption, and description expose this context through `Rules trace` controls
  on the Media screen.
- OpenAI image optimization runs through `/images/optimize-job` and polls the
  existing session-job endpoint. The synchronous `/images/optimize` route
  remains available for compatibility, but the Next frontend does not hold a
  multi-minute proxy request open.
- Image edits have bounded waits: the OpenAI request defaults to 300 seconds
  with two retries for transient provider failures (`V2_IMAGE_EDIT_TIMEOUT_SECONDS` and
  `V2_IMAGE_EDIT_MAX_RETRIES`), while the UI stops polling after 330 seconds
  and explains that a server job may still complete in the background. The UI
  polls every three seconds; these GET requests only read job status and do not
  submit additional image edits.
- AI edits default to `gpt-image-2` (`V2_IMAGE_EDIT_MODEL`) so edit inputs use
  the current model's high-fidelity image handling. Persistent provider 5xx
  failures include the OpenAI request ID when available for support diagnosis.
- AI picture edits prepend enabled `agent_instructions` for the explicit
  `ai_image_edit` workflow stage to the user's requested change. Matching uses
  the current post type (or `*`), `owner=language_model`, and the `always` or
  `ai_edit_requested` condition. Both `instruction_de` and `expected_behavior`
  are included as preservation constraints. Applied rules and the exact prompt
  sent to the image provider are saved in the processed picture's
  `image_optimization` trace. Keeping this stage explicit
  prevents unrelated content-writing instructions from entering image prompts.
- Image-edit results are normalized again with the workbook Pillow `prepare`,
  `crop`, `resize`, and `export` stages. This deterministically reapplies the
  required aspect ratio, output format, dimensions, and compression target
  without applying enhancement/filter rules a second time.
- Workbook rows for this stage are validated. They must use
  `owner=language_model`; supported conditions are `always` and
  `ai_edit_requested`.

### Phase 6: Facts Slice

Outcome:

- Facts render dynamically from workbook schema plus session data.
- Required missing, optional missing, and AI-populated sections work.
- Fact review supports field-level AI include/exclude selection.
- Corrections save through `/answers`.
- Recheck runs through `/analyze`.
- Confirmation state follows backend validation/state.

Implemented frontend files:

- `speech-2-post-ui/lib/content-sessions.ts`
- `speech-2-post-ui/app/page.tsx`
- `speech-2-post-ui/components/facts-screen.tsx`

Current behavior:

- The Facts screen no longer uses V0 mock fields.
- Fact rows are built from `_workbook.fact_schema` for the active session post
  type.
- Values are read from `confirmed_facts` first, then `extracted_facts`.
- Missing required, missing optional, and populated fact sections are computed
  dynamically from workbook schema plus current drafts.
- Empty fact sections are collapsed by default; the first non-empty section is
  opened automatically.
- Edited corrections save through
  `POST /api/content-sessions/{session_id}/answers`.
- Recheck saves pending corrections, then calls
  `POST /api/content-sessions/{session_id}/analyze` with the selected
  `review_fact_keys`.
- Empty facts are selected for AI review by default; populated facts remain
  unchecked. Each fact row has a checkbox, with `Check all facts` and `Uncheck
  all facts` controls; review is disabled when the selection is empty.
- Targeted fact review builds the extraction schema and fact-rule context only
  for selected keys. Non-selected extracted and confirmed facts remain
  unchanged.
- A non-empty AI result may replace a selected confirmed fact. This replacement
  is limited to explicitly selected keys; initial Media-screen extraction omits
  `review_fact_keys` and continues to analyze the complete fact schema.
- The floating Facts agent uses the same selection as the Facts screen, so typed
  or recorded review instructions cannot bypass the selected scope. It also
  shows the selected count and synchronized `Check all facts` / `Uncheck all
  facts` controls.
- When an agent action returns a newer session version, the Facts screen refreshes
  its local editable values immediately; a browser reload is not required to see
  reviewed facts.
- Confirm facts saves all non-empty visible fact values through `/answers` and
  moves directly to the Content screen once required facts are complete. It
  does not rerun `/analyze`.
- The shell reloads workbook schema when the active session post type changes.
- Enum-backed facts render as selects using `validation_lists.description_de`
  for their visible labels while saving `allowed_value` as the stable session
  value.

Risk:

- Avoid hardcoding V0 example fields.
- Do not treat these checkboxes as publication inclusion: they only scope the
  next AI fact review.

### Phase 7: Content Slice

Outcome:

- Generated shared and ACF fields render from session data.
- Edited fields autosave/debounced through `/draft-fields`.
- Draft revision supports field-level include/exclude selection.
- Prompt trace is shown from `generation_trace`.
- Generated text outside workbook `min_words`/`max_words` targets is retained
  and reported through non-blocking `validation_report.warnings`; required-field,
  character-limit, and structured-schema failures remain blocking.
- Agent regeneration uses `/draft-chat`.
- Approval uses `/approve`.

Implemented frontend files:

- `speech-2-post-ui/lib/content-sessions.ts`
- `speech-2-post-ui/app/page.tsx`
- `speech-2-post-ui/components/content-screen.tsx`

Implemented backend files:

- `app/v2/api/step_01_models.py`
- `app/v2/api/step_02_routes.py`
- `app/v2/context/step_01_builder.py`
- `app/v2/sessions/step_03_service.py`

Current behavior:

- The Content screen no longer uses V0 mock generated fields.
- Draft fields render from the active session's `shared_fields` and
  `acf_source_fields`.
- The Generate Draft action starts `POST /generate-job` and polls
  `GET /jobs/{job_id}` until the backend returns the updated session.
- Edited draft fields autosave through `PUT /draft-fields` after a short
  debounce; a manual Save Edits button remains available.
- The prompt trace panel reads directly from `generation_trace`.
- The content agent saves pending edits and sends the instruction through
  `POST /draft-chat`, together with the selected revision field IDs.
- All draft fields are selected for revision by default. Field checkboxes and a
  `Select all for revision` / `Clear revision selection` control allow a smaller
  revision scope. Revision is disabled when no fields are selected.
- Revision selection controls what the language model regenerates; it does not
  remove fields from the saved draft or WordPress payload.
- Revision field IDs are sent as `revision_field_ids`, using `shared:<key>` and
  `acf:<key>` identifiers. The backend rejects an explicitly empty selection and
  identifiers that do not belong to the current draft.
- Targeted revision builds prompt rules and structured output schemas only for
  selected fields. Field, group, section, and blueprint context is filtered to
  the selected scope; shared instructions that apply to those fields remain.
- The model is asked to output only the selected fields. Returned values are
  merged into the existing draft, so unselected values and generation traces
  remain unchanged, including manual edits.
- Targeted revision does not automatically rerank or complete internal-link
  selections. Existing links and links explicitly queued in the Content screen
  are preserved, and link placement is limited to selected ACF fields.
- The revision stage exposes an `AI-assisted placement` checkbox for queued
  internal links. When unchecked, a link-only revision skips the content model
  and only wraps an approved anchor that already exists in the current draft.
  When checked, the selected fields may be regenerated so the agent can create
  or rewrite wording for the selected links before the backend wraps the final
  approved anchor.
- Queued links require an explicit ACF destination. Their destination fields are
  included in revision selection separately from manual field selections, so a
  dropdown change moves only the link-owned selection and preserves fields the
  user had already checked.
- Internal links are single-use: a target URL or anchor already present in the
  draft is treated as used and will not be injected again during later placement
  passes.
- Omitting `revision_field_ids` preserves the previous full-draft revision
  behavior for older callers.
- Approval saves pending edits, calls `POST /approve`, and moves to the
  WordPress screen.

Why this is implemented in the backend:

- Frontend-only checkboxes would reduce what the UI appears to select while the
  existing `/draft-chat` service would still send every rule and regenerate both
  complete field groups. Enforcing the selection in the existing generation
  service reduces token usage and latency and prevents accidental changes
  without duplicating backend logic.

Verification:

- A structured-pipeline regression test checks that only the selected field
  group is generated and an unselected manual edit remains exactly unchanged.
- The available V2 suite passes. Workbook-dependent generation tests remain
  skipped when the configured test workbook is unavailable.

Risk:

- Keep revision field IDs scoped (`shared:<key>` / `acf:<key>`) so equal keys in
  different draft groups cannot collide.

### Phase 8: WordPress Slice

Outcome:

- Create first post through `/publish-job`.
- Update existing post with `target_post_id` and `partial_update`.
- Display returned post ID, view link, edit link, status, and sent fields.
- Show no-change state when partial update returns no changed fields.
- Show retryable errors.

Implemented frontend files:

- `speech-2-post-ui/lib/content-sessions.ts`
- `speech-2-post-ui/app/page.tsx`
- `speech-2-post-ui/components/wordpress-screen.tsx`

Current behavior:

- The WordPress screen no longer uses simulated post IDs or fake changed fields.
- Create Post starts `POST /publish-job` with `force_create_new: true` and polls
  `GET /jobs/{job_id}` until the backend returns the updated session.
- After the first successful publication, Create Post is disabled while the
  current payload matches the published payload. It becomes Re-create Post
  after content changes; this uses `force_create_new: true` to publish the full
  current content and media to a new WordPress post ID and replaces the
  session's current `wordpress_result`.
- Re-create Post explains this new-post behavior in its tooltip, and only the
  publish action actually running displays a loading spinner.
- Update Post uses the stored `wordpress_result.post_id` as `target_post_id`
  with `partial_update: true`.
- Returned WordPress post ID, status, view link, edit link, and idempotency key
  are displayed from `wordpress_result`.
- The screen compares `wordpress_payload` with `published_wordpress_payload` to
  show pending changed payload fields or a no-change/synced state.
- Sent and current WordPress payloads are visible for inspection.
- Retryable errors from failed publish jobs are shown in the screen status area.
- Full publication rebuilds the exposed `gallery_html` ACF value after media
  upload, using the final WordPress URLs of all non-featured session images.
- The screen represents the current backend model honestly: one current
  `wordpress_result` per session, not a history of multiple targets.

Risk:

- Multiple WordPress targets per session likely requires backend model changes.

### Phase 9: Other Functions, Status, Recovery

Outcome:

- Global status panel tracks concurrent frontend/backend operations.
- Other Functions drawer connects credentials, workbook config, session archive,
  logs, current session info, and usage.
- The top bar uses a labeled New session button to open the Sessions menu; the
  menu can be closed without selecting or creating a session.
- Session archive entries show the session ID first, followed by creation
  timestamp, post type, and status.
- Workbook config can upload a replacement `.xlsm`/`.xlsx` file and download
  the active Database Datei through the existing legacy workbook endpoints.
- Upload reloads the knowledge snapshot when the V2 service is already active;
  it does not initialize unrelated providers merely to refresh the workbook.
- A failure while rendering optional legacy workbook-status details does not
  turn a validated, committed upload into a false HTTP 500 response.
- Local GCS-backed development requires Application Default Credentials plus
  `GOOGLE_CLOUD_PROJECT`; `gcs_required` prevents silent local-only updates.
- Job polling can recover after reload when possible.
- Missing durable queue is documented separately.

Implemented frontend files:

- `speech-2-post-ui/app/page.tsx`
- `speech-2-post-ui/components/other-functions-drawer.tsx`
- `speech-2-post-ui/components/content-screen.tsx`
- `speech-2-post-ui/components/wordpress-screen.tsx`

Current behavior:

- The top bar has an Other Functions button that opens a right-side drawer.
- The drawer orders its tools as Generation settings, Usage, Operations log,
  Sessions archive, Workbook config, Credentials, Current session, Global
  status, and Recovery note.
- Session archive actions can refresh recent sessions and load a selected V2
  session without leaving the workflow.
- Current session recovery can reload the active session from the backend.
- Generate and publish jobs store the last active job ID in `sessionStorage`.
- The drawer can attempt to recover that last job through
  `GET /api/content-sessions/jobs/{job_id}` and refresh the session if the job
  completed while the same backend process was still alive.
- The drawer documents the current in-memory job limitation directly in the UI:
  backend restart still loses job records.

Risk:

- True mobile sleep resilience requires persistent job storage, not only in-memory
  FastAPI jobs.

### Phase 10: Local Verification

Outcome:

- Type checks pass.
- Next production build passes.
- Backend focused tests pass.
- Four workflow screens work locally.
- Current `/app` UI still works.

### Phase 11: Single-Client Render Showcase

Outcome:

- The existing FastAPI app and new Next frontend deploy as separate Render web
  services in Frankfurt.
- The Next service proxies `/backend/*` to FastAPI over Render's private
  network.
- The current `/app` UI remains part of the unchanged FastAPI service.
- Production authentication fails closed when `IMPORT_API_KEY` is absent.
- FLAIRLAB's canonical workbook and all V2 session/media objects remain in GCS.
- Image uploads remain capped at 20 MiB and showcase audio at 25 MiB.

Implemented deployment files:

- `render.yaml`
- `docs/speech2post_render_showcase.md`

Showcase boundary:

- Only the `flairlab` client is supported.
- Keep the backend on a paid Starter instance so AI jobs do not depend on a
  sleeping service. The frontend can use a Free web-service instance; accept a
  possible cold start after 15 idle minutes.
- In-memory generate/publish jobs can still be lost by a backend restart or
  deploy. Do not redeploy while a job is active.
- The shared key in `sessionStorage` is temporary showcase authentication, not
  the planned secure cookie implementation.
- Render environment secrets temporarily inject credentials. Direct
  client-scoped Google Secret Manager resolution remains later multi-client
  work.

Setup and phone acceptance steps are documented in
`docs/speech2post_render_showcase.md`.

## Recent Workflow Evolutions

These behaviors are intentional and should be preserved during later cleanup:

- Draft word-count validation applies a 20% tolerance in both directions.
  Minimums use `ceil(target × 0.8)` and maximums use
  `floor(target × 1.2)`. Character limits remain exact. For example, a field
  with a maximum of 80 words accepts up to 96 words.
- Generation mode is stored per session and can be changed under Other
  Functions:
  - `batched` remains the safer default and generates shared fields followed by
    section-based ACF batches;
  - `single` is an explicit test mode that generates shared and ACF fields in
    one structured call, reducing repeated context but increasing the size and
    timeout risk of one provider request.
- Operation-log entries retain a collapsible per-model-call breakdown with the
  task, model, duration, input/output tokens, total tokens, and estimated cost.
- Generation context sends confirmed fact values without repeating confidence
  and source metadata. Batched ACF calls do not resend prose generated by prior
  ACF batches.
- Internal-link revision selections default to `Auto`, allowing the agent to
  choose the most suitable link-enabled ACF field. A manually selected ACF is a
  preferred destination rather than a hard constraint; if it cannot accept the
  link safely, the agent may fall back to another eligible field.
- Link placement is deterministic-first: when an approved anchor occurs exactly
  once in a linkable field routed to the requested ACF, Python wraps it safely
  without a separate model call. Only unresolved links use the language-model
  placement planner for a safe sentence rewrite or ambiguous placement.
- Explicitly requested links cannot silently disappear. The revision either
  places every requested link or reports which link could not be placed and why.
- All native controls in `speech-2-post-ui/` have stable `s2p-...` IDs. Dynamic
  controls use stable fact, field, link, media, or session identifiers.
- Sections inside Other Functions are collapsed by default to keep the drawer
  navigable.

## Decisions To Keep Code Small

- Build one vertical slice at a time.
- Prefer adapters over backend payload changes.
- Do not duplicate existing V2 service logic in the frontend.
- Disable unsupported UI actions with clear text rather than faking success.
- Keep all new frontend network calls in one API client.
- Keep the current live UI untouched until the Next version is ready to replace
  it.

## OpenAI Image Pricing Table

- `data/openai_image_pricing.json` is the temporary machine-readable pricing
  table used for OpenAI image-output estimates.
- `scripts/update_openai_image_pricing.py` downloads the official image-cost
  documentation, parses the model/quality/size table, validates all required
  GPT Image 2 combinations, and replaces the JSON file atomically.
- A failed download, changed page structure, incomplete table, or invalid price
  exits with an error before replacing the last valid table.
- These are output-image estimates. Text and image input-token charges can make
  the complete API request cost higher.
- OpenAI image edits use `V2_IMAGE_EDIT_QUALITY` (`medium` by default) and a
  documented output size selected from the source orientation. The image
  provider records the matching table price, actual `gpt-image-*` model,
  quality, and size in usage data. Image-operation headers do not inherit the
  unrelated session language model or generation settings.

### Execution Instructions

From the repository root, refresh the table manually:

```bash
.venv/bin/python scripts/update_openai_image_pricing.py
```

Run the parser tests without network access:

```bash
.venv/bin/python -m pytest tests/v2/test_openai_image_pricing.py -q
```

For an optional daily refresh at 06:15, open the current user's crontab with
`crontab -e` and add:

```cron
15 6 * * * cd '/home/ogier-derouineau/IT projects/whatsapp_to_Wordpess_post' && .venv/bin/python scripts/update_openai_image_pricing.py >> /tmp/speech2post-image-pricing.log 2>&1
```
