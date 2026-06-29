# FLAIRLAB WordPress Post Generator

This project turns event inputs — voice notes, manual notes and images — into a structured WordPress post draft, then publishes it through WordPress REST APIs.

The current V2 workflow is workbook-driven. The workbook is the source of truth for post types, fact extraction, draft fields, image metadata, internal links, style rules and payload routing.

## Current V2 workflow

1. Create a V2 content session.
2. Upload or record voice notes, add manual notes and optionally upload images.
3. Transcribe and analyze the input.
4. Review/edit extracted facts under the transcript panel.
5. Generate a structured draft.
6. Optionally refine the draft with the agent message box.
7. Review image metadata and draft fields.
8. Publish to WordPress.

The old UI is still used as the main interface, but in V2 mode its core actions are routed to `/api/content-sessions`.

## Terminal milestones

V2 prints readable milestones to the server terminal for longer-running stages, for example:

```text
[V2 milestone] session=abc12345 state=generating shared field generation started
[V2 milestone] session=abc12345 state=generating ACF field generation finished
[V2 milestone] session=abc12345 state=needs_review draft generation finished
```

This helps follow the pipeline while testing. Disable these logs with:

```bash
export V2_MILESTONE_LOGS=0
```

## Running locally

```bash
export CONTENT_PIPELINE_VERSION=v2
export V2_KNOWLEDGE_WORKBOOK_PATH=/absolute/path/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm
myenv/bin/uvicorn main:app --reload
```

Useful environment variables:

| Variable | Purpose |
|---|---|
| `CONTENT_PIPELINE_VERSION=v2` | Activates the V2 adapter in the familiar UI |
| `V2_KNOWLEDGE_WORKBOOK_PATH` | Workbook source of truth |
| `V2_SESSION_ROOT` | Local file-backed session storage |
| `V2_SESSION_GCS_PREFIX` | Cloud/GCS session/object prefix |
| `V2_LANGUAGE_MODEL` | Structured text generation model |
| `V2_VISION_MODEL` | Image analysis model |
| `V2_TRANSCRIPTION_MODEL` | Speech-to-text model |
| `V2_MILESTONE_LOGS=0` | Disables terminal milestone logs |

## Testing

Run the full suite:

```bash
myenv/bin/python -m unittest discover -s tests -p 'test*.py'
```

Run focused V2 checks:

```bash
myenv/bin/python -m unittest tests.v2.test_structured_pipeline tests.v2.test_legacy_ui_adapter tests.v2.test_api
```

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

2. **`ACF_fields_schema`**
   - This is one of the most important tabs.
   - Define the input facts and generated fields for the post type.
   - Mark required facts carefully; too many required facts can block generation, too few can weaken the result.
   - Use `field_role = input_fact` for facts the system must extract/confirm before drafting.
   - Use generated/direct/aggregation roles for fields that become draft or ACF payload values.

3. **`post_blueprint`**
   - This is the skeleton of the post.
   - Use it to tell the generator what sections belong in this post type and in what order.

4. **`agent_instructions`**
   - This is where the “brain” gets its operating rules.
   - Add instructions for `analysis`, `generation`, `image_metadata` and `internal_links` where relevant.
   - Keep instructions specific to the post type, not generic marketing fluff.

5. **`seo_rules`**
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

For WordPress media descriptions, V2 prefers the workbook field mapped to destination key `description`. Older `image_description_wp` values are kept as fallback only.

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
- UI compatibility.

If a seemingly simple request requires a lot of code, first ask whether the same behavior can be expressed in the workbook with fewer moving parts.
