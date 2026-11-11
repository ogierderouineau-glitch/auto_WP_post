# Speech2Post

This project turns voice notes, manual notes and images into a structured WordPress post draft, then publishes it through WordPress REST APIs.

Speech2Post supports multiple clients across different industries. Client-specific
post types, fields and business rules belong in each client's workbook and
configuration, rather than shared application logic. See [AGENTS.md](AGENTS.md)
for the project priorities that apply to every coding agent.

Coding agents should start with [the continuation guide](docs/agent_handoff.md)
for current architecture, setup, known gaps and a reusable conversation starter.

The current production workflow is workbook-driven. The workbook is the source of truth for post types, fact extraction, draft fields, image metadata, internal links, style rules and payload routing.

## Current production workflow

1. Create a content session.
2. Upload or record voice notes, add manual notes and optionally upload images.
3. Transcribe and analyze the input.
4. Review/edit extracted facts under the transcript panel.
5. Generate a structured draft.
6. Optionally refine the draft with the agent message box.
7. Review image metadata and draft fields.
8. Publish to WordPress.

The Next.js app in `frontend/` is the user interface. It talks to the
FastAPI backend through the structured `/api/content-sessions` API.

## Session names and workflow safeguards

Click the session label in the top bar to rename a session (up to 80 characters).
The first successful fact extraction suggests a short name in the session language
when no manual name exists. Older unnamed sessions are named when opened if they
contain saved facts or draft content. Empty sessions show “Untitled session”.
Naming uses the existing language-model provider and usage tracking; failure does
not block the workflow or repeat automatically. Session IDs remain unchanged and
appear as tooltips in both archives. Names are also shown under Current session.

Repeated fact extraction, full draft regeneration and post re-creation use red
buttons and confirmation dialogs. A selected-fact/field revision alternative is
offered only when there is a selection; post updates are offered when available.
Re-creating a post creates a separate WordPress post and switches the session's
current target. The original post remains online.

Media AI recropping, restoring an original picture and removing a picture require
OK/Cancel confirmation before executing.

The Media status indicators stay unchecked until media is uploaded; counts include
both images and videos.
The Media screen accepts dropped pictures and MP4 videos through the same upload
flow as the file picker. Drops elsewhere on that screen cannot navigate away.
“Tell your story” highlights the selected media transcript until text is added or
the selected media changes. The recording button opens the agent and starts/stops
recording. Fact sections expand independently and empty sections start collapsed; revision
checkboxes appear after extraction. Extraction is disabled until a non-empty
transcript has been saved (general text, audio transcript, picture or video notes).
The Media agent provides “Save transcript” for its general text. Fact updates stay
disabled until the first extraction; content revision requires a generated draft
and selected fields or free link candidates. The Content screen’s Quality check and Revise selected fields
buttons are hidden until a draft exists. Disabled actions explain the prerequisite on hover or keyboard
focus. Content revision opens the existing agent for the selected fields.

On the WordPress screen, “Open template” opens the active post type's
`post_types.single_template_url` in a new tab when an HTTP(S) URL is configured.
The publishing checklist checks “Featured image assigned” only when an uploaded
image is marked as featured; sessions without images leave it unchecked.
Workbook uploads show a prominent confirmation with the uploaded filename.
Operations from today show local time; older operations show local date and time.
Agent-popup errors appear in red; progress and success messages remain neutral.
Targeted revision also fills absent or empty required outputs from the active
workbook, using the existing generation request or confirmed-fact derivation.
Missing configured output fields also appear as blank editors in the Content
screen for existing drafts. Users can type into them (using the existing autosave)
or select them for AI revision. The list excludes input facts, ineligible outputs
and fields populated only during publication. Loading the list makes no AI calls.
It preserves other populated fields and keeps full-draft validation. This allows
older sessions to acquire newly required fields without a full regeneration.
Optional missing fields are not generated automatically. If required outputs still
cannot be filled, the error lists them and suggests full regeneration.

## Internal links

The Content screen shows the session's candidate list, including placed links.
Use **Add candidate…** to search all eligible links in this client's workbook by
anchor, URL or description. The configured post type, language and active flags
still apply. The workbook maximum applies to the total candidate list, including
placed and manually added workbook candidates.

**Refresh unplaced candidates** retains placed links and ranks alternatives locally,
excluding the previous unplaced set. Fewer suggestions appear when there are not
enough relevant alternatives. Removing an unplaced candidate only removes it from
the list. Removing a placed candidate unwraps its link while preserving anchor text
and inner formatting, updates the payload and requires approval again. Removed IDs
stay excluded across reloads and full regeneration until manually re-added.

Select free candidates and use **Revise selected fields**, then submit through the
content agent. No extra instruction or manually checked field is necessary for
link-only placement. Each destination defaults to **- choose for me -**: local
scoring prefers approved anchor matches, then an explicitly preferred destination,
keyword/context relevance and workbook field priority, respecting field capacity.
No AI tokens are used to choose destinations or place existing anchors. Placed
candidates show their destination fields.

If exact placement fails, the app requests a small AI revision for only the needed
eligible fields, without sending examples or unrelated draft fields. This can
include a field outside the manually checked set. The app then injects links and
validates the draft. Existing links must survive unchanged. If any requested link
cannot be placed safely, the saved draft stays unchanged and the action reports an
error. The former AI-assisted-placement checkbox is no longer needed.

For a pasted internal or external URL, select text in a generated link-enabled ACF
field and click **Add link to selected text**. In HTML fields, select text in the
source editor. Paste an HTTP(S) URL and confirm. The app wraps that selection without
rewriting surrounding content; selections spanning tags or existing links are
rejected with guidance. Field link limits and spacing rules still apply. A pasted
URL matching an eligible workbook link joins the candidate list and counts toward
its maximum. Other pasted URLs remain direct content edits rather than candidates.
Changing content refreshes the WordPress payload but does not update the live post
until the normal approval and update/publish flow is used.

## Project structure

```text
backend/
  app/          application features and providers
  tests/        backend regression tests
  main.py       FastAPI composition root
  config.py     environment configuration
  wordpress_api.py
  requirements.txt
frontend/       Next.js user interface
integrations/   WordPress plugins and snippets
data/           workbook inputs and ignored local runtime data
tools/          diagnostics and maintenance commands
scripts/        deployment and local proxy helpers
docs/           deployment guide and generated workbook reference
main.py         compatibility entry point for uvicorn
```

## Terminal milestones

The workflow prints readable milestones to the server terminal for longer-running stages, for example:

```text
[pipeline milestone] session=abc12345 state=generating shared field generation started
[pipeline milestone] session=abc12345 state=generating ACF field generation finished
[pipeline milestone] session=abc12345 state=needs_review draft generation finished
```

This helps follow the pipeline while testing. Disable these logs with:

```bash
export V2_MILESTONE_LOGS=0
```

## Running locally

Create the Python environment once:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
```

Start the backend:

```bash
.venv/bin/python -m uvicorn main:app --reload
```

Add an ignored `clients.json` first and supply `OPENAI_API_KEY` through a root
`.env` or the process environment. Restart the backend after changing secrets.
Normal local execution uses `data/knowledge/{client_id}.xlsm` (or `.xlsx`) and
`data/v2_sessions/{client_id}`. Render uses configured isolated GCS paths.
See [deployment configuration](docs/deployment.md) for details.

In another terminal:

```bash
cd frontend
nvm use
corepack pnpm dev
```

Useful environment variables:

| Variable | Purpose |
|---|---|
| `GCS_KNOWLEDGE_BUCKET` | Canonical client workbook bucket |
| `GCS_DATA_BUCKET` | Client session and uploaded-object bucket |
| `V2_SESSION_ROOT` | Local file-backed session storage |
| `V2_LANGUAGE_MODEL` | Structured text generation model |
| `V2_VISION_MODEL` | Image analysis model |
| `V2_TRANSCRIPTION_MODEL` | Speech-to-text model |
| `V2_MILESTONE_LOGS=0` | Disables terminal milestone logs |

## Older Cloud Run helpers

The current deployment configuration is [Render](docs/deployment.md).
The following scripts target the older Cloud Run deployment; they are not
required to start the application locally.

Use the helper scripts in `scripts/` for quick loops:

1. Mirror live on localhost (no deploy needed):

```bash
./scripts/live-local.sh
```

This proxies Cloud Run to `http://localhost:8000`.

2. Fast image-based deploy:

```bash
./scripts/deploy-fast.sh
```

Defaults:

- `SERVICE=auto-wp-post`
- `PROJECT=auto-wordpress-post-499518`
- `REGION=europe-west1`
- `REPO=cloud-run-source-deploy`
- `IMAGE_NAME=auto-wp-post`
- `TAG=quick`

Override any value inline, for example:

```bash
TAG=$(date +%Y%m%d-%H%M%S) ./scripts/deploy-fast.sh
```

## Testing

Run the full suite:

```bash
.venv/bin/python -m pytest
```

Workbook-dependent tests use `data/knowledge/test-client.xlsm` by default and
skip when it is absent. To use another compatible workbook without renaming it:

```bash
V2_TEST_WORKBOOK="data/knowledge/your-client.xlsm" .venv/bin/python -m pytest
```

Run focused structured workflow checks:

```bash
.venv/bin/python -m pytest backend/tests/test_structured_pipeline.py backend/tests/test_api.py
```

## Generation latency diagnostics

To flag slow generation jobs from local sessions (default threshold: 45 seconds):

```bash
.venv/bin/python tools/generation_latency_report.py --threshold 45
```

Useful options:

- `--operation content_generation` (default)
- `--session-id <session_id>` to inspect one session
- `--limit 50` to print more rows
- `--json` for machine-readable output

## Validation References Runbook

Regenerate validation choice references after updating `validation_lists` values:

```bash
.venv/bin/python tools/export_validation_reference.py data/knowledge/{client_id}.xlsm
```

Generated artifacts:

- `docs/reference/validation_choices.md`
- `docs/reference/validation_choices.csv`

The CSV includes both a human-readable `allowed_value` column and an `allowed_value_json` column that preserves typed values.

## Adding a new post type

The key idea: `post_type_key` is the beacon. Every workbook tab that supports post-type-specific behavior should use the same `post_type_key` value for the new type.

Example:

```text
post_type_key = product_launch
```

Use that same value across all relevant tabs.

### Minimum viable setup

To get a new post type working, configure these first:

1. **`post_types`**
   - Define the new `post_type_key`.
   - Enable generation/template flags.
   - Set WordPress post type, default language/status/category.
   - Select zero or more entries from `taxonomies` in `wp_taxonomies`
     (semicolon-separated when selecting several).

2. **`taxonomies`**
   - Define each `(post_type_key, wp_taxonomy)` relationship once.
   - Set its term source as `fixed:<value>`, `shared:<field_key>`,
     `acf:<field_key>`, or `fact:<input_fact_key>`.
   - The same WordPress taxonomy may use different term sources for different
     post types.
   - Set `post_types.assign_taxonomy_to_media` when all terms selected by that
     post type should also be assigned to uploaded media.

3. **`ACF_fields_schema`**
   - This is one of the most important tabs.
   - Define the input facts and generated fields for the post type.
   - Mark required facts carefully; too many required facts can block generation, too few can weaken the result.
   - Use `field_role = input_fact` for facts the system must extract/confirm before drafting.
   - Use generated/direct/aggregation roles for fields that become draft or ACF payload values.

4. **`post_blueprint`**
   - This is the skeleton of the post.
   - Use it to tell the generator what sections belong in this post type and in what order.

5. **`agent_instructions`**
   - This is where the “brain” gets its operating rules.
   - Add instructions for `analysis`, `generation`, `image_metadata` and `internal_links` where relevant.
   - Keep instructions specific to the post type, not generic marketing fluff.

6. **`seo_rules`**
   - Controls exact field-level constraints and SEO behavior.
   - Use this to keep titles, descriptions, headings, excerpts and link behavior consistent.

If those five are solid, the machine has enough structure to produce useful drafts.

### High-impact quality tabs

These tabs are where you get the most “juice out of the machine”:

| Priority | Tab | Why it matters |
|---|---|---|
| 1 | **`ACF_fields_schema`** | Defines what facts and fields exist; bad schema means bad or blocked output |
| 2 | **`agent_instructions`** | Gives task-specific behavior and prevents generic writing |
| 3 | **`post_blueprint`** | Controls structure, section order and what the final post should contain |
| 4 | **`seo_rules`** | Adds field-level quality constraints and SEO discipline |
| 5 | **`style_rules`** | Controls voice, tone and phrasing for the post type |
| 6 | **`story_patterns`** | Helps the model choose a narrative shape when facts match a known scenario |
| 7 | **`post_examples`** | Provides high-quality reference patterns; useful when approved and representative |
| 8 | **`internal_links_database`** | Gives the system eligible links and anchors for contextual internal linking |

### Maintaining `post_examples`

Keep one approved example per row, using these columns:
`post_type_key`, `example_id`, `enabled`, `approved`, `quality_score`,
`input_facts_text`, `post_title`, `example_content`, `learning_for_gpt`,
`retrieval_tags`, and `url`.

Put labelled copy in `example_content`; exact ACF field names make the labels
easier to associate with the schema. Examples guide writing quality, while the
current field schema, blueprint and instructions determine the output.

Separate `retrieval_tags` with semicolons. Use concise, distinctive descriptions
such as `hotel; luxury; team integration`. Descriptive phrases and system tags
such as `luxury_hotel` both work. Selection counts distinct matching words
(case-insensitive, splitting punctuation and underscores, excluding common words)
against confirmed fact values and session context tags. It considers only enabled,
approved examples of the current post type, then ranks by word overlap, quality
score, and example ID for stable ties. With no overlap it selects the highest-quality
example. This is lexical matching, so synonyms in different languages do not match
automatically; use the vocabulary present in the client's facts and tags.

Only one example is sent for post generation. Image metadata uses
`image_metadata_schema` and `image_metadata_rules`, together with the current
picture context; post examples and legacy image-caption columns are excluded.

### Tabs to extend for a new post type

Add rows using the new `post_type_key` in:

- `ACF_fields_schema`
- `post_blueprint`
- `story_patterns`
- `style_rules`
- `internal_links_database`
- `post_examples`
- `agent_instructions`
- `seo_rules`

Use `*` only for rules that are truly global across post types. If behavior should differ, create a post-type-specific row instead.

### Practical setup checklist 

For each new post type:

- Confirm the `post_type_key` exists and is enabled in `post_types`.
- Add required `input_fact` rows in `ACF_fields_schema`.
- Add generated fields that map to the WordPress/ACF payload.
- Add a `post_blueprint` section sequence.
- Add generation-specific `agent_instructions`.
- Add field and section `seo_rules`.
- Add `style_rules` for tone.
- Add a few strong `post_examples` if available.
- Add relevant `internal_links_database` rows with active links.
- Run workbook validation before coding against the new type.

### Common pitfalls

- Using a different `post_type_key` spelling in different tabs.
- Marking too many facts as required and making generation hard to unblock.
- Adding generic examples that do not match the new post type.
- Forgetting `seo_rules`, then wondering why output length/tone varies too much.
- Adding internal links without useful anchor variants or usage context.
- Expecting code changes for content behavior that should live in the workbook.

## Image metadata behavior

Image upload does Pillow processing immediately. Vision for metadata is controlled by the UI checkbox:

```text
Metadata mit Vision nach dem ersten Entwurf generieren lassen
```

When checked, contextual Vision analysis runs during draft generation/save, after the draft context is available. This helps metadata use confirmed facts such as bartender names or show/service details.

For WordPress media descriptions, the workflow prefers the workbook field mapped to destination key `description`. Older `image_description_wp` values are kept as fallback only.

## Test voice message

Hover over `Aufnahme starten` in the UI to see a compact test prompt. It is designed to exercise:

- event facts;
- bartender names;
- show/service facts;
- challenge and solution;
- concrete drinks;
- guest reaction;
- image metadata context.

## Development principle

Keep business behavior in the workbook whenever possible. Code should mainly provide:

- typed validation;
- deterministic routing;
- structured model calls;
- safe file/media handling;
- WordPress publication;
- a small authenticated API for the frontend.

If a seemingly simple request requires a lot of code, first ask whether the same behavior can be expressed in the workbook with fewer moving parts.
