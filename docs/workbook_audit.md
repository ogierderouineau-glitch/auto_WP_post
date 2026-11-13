# Workbook audit: which tabs and columns are really integrated

**Status: read-only findings, nothing has been changed.** Audited 2026-11-11 on
`FLAIRLAB V9.xlsm` (17 sheets; since replaced locally by
`data/knowledge/flairlab workbook-DEV.xlsm`), against the loader, models,
validator, context builder, prompts and services under `backend/app/`. This is
input for the workbook documentation and cleanup step in
[google_drive_workbooks_proposal.md](google_drive_workbooks_proposal.md).

## Method and limits

For every column I compared the sheet header with the pydantic model, then searched
the code (excluding models, loader and tests) for reads of that field. A column is
classified as:

| Class | Meaning |
|---|---|
| **Code** | Deterministic code reads it (filtering, routing, validation, payloads). |
| **Prompt** | No code reads it, but the whole row is serialized into the model context (`row.model_dump()` in `context/step_01_builder.py`, then `json.dumps(context)` in `content_generation/step_02_prompts.py`). It matters only as free text the model interprets. |
| **Dead** | Loaded (or ignored as an extra column) and read by nothing. |

Limits: this is a static search, so dynamic access by string (for example validation
families named inside cells) can hide usage; I checked those cases listed below by
hand. Only V9 was audited, so values below describe that client's workbook. I did
not run generation to test what the model does with prompt-only columns.

## Headline

Most of the schema is real: **13 of 17 tabs and about 85% of the modelled columns
are read by code.** The clutter is concentrated in a handful of places.

| Tab | Rows | Verdict |
|---|---|---|
| post_types, taxonomies, shared_fields_schema, ACF_fields_schema, image_metadata_schema, image_metadata_rules, prompt_guidance, HTML_patterns, validation_lists | | Integrated; see column exceptions below |
| post_blueprint, story_patterns, seo_rules, style_rules, agent_instructions, post_examples | | Integrated, but several columns are prompt-only or dead |
| internal_links_database | 86 | Integrated; 1 dead and 3 ignored columns |
| `validation_lists 2` | 27 | **Dead sheet**: not loaded, a stray list of input-fact keys under the header "acf input_facts" |
| README | absent | Loader looks for a `schema_version` row; V9 has none, so the version is always `None` |

## Dead columns

| Sheet.column | Evidence | Note |
|---|---|---|
| post_types.`development_status` | no reads | Required by the model, so it must be filled even though nothing uses it |
| post_types.`image_rules_profile` | no reads; all rows `default` | Required by the model. Suggests per-client image profiles that were never built |
| post_types.`seo_profile` | no reads; all rows `default` | Same as above |
| internal_links_database.`link_role` | no reads; filled on 86/86 rows | Required by the model |
| internal_links_database.`service_tags`, `event_context_tags`, `event_tags` | not in the model, not read | Legacy tag matching; filled on 2, 0 and 0 rows. Loaded only as ignored extras |
| style_rules.`good_example`, `avoid_example` | not in the model; empty | Extra columns. If someone fills them they would be dumped into the prompt by accident |
| validation_lists.`Client-specific values` | not in the model; empty | Unused column |
| story_patterns.`max_patterns` | no reads; every row `1` | The real limit is the constant `[:2]` in the builder, plus `max_items=2` in the app-owned manifest, which itself is never read |
| image_metadata_rules.`notes_de` | no reads | Human note; image metadata uses its own payload, so likely not sent to the model |
| internal_links_database.`notes` | no reads; filled on 81/86 | Human comment column. Harmless, but should be documented as such |

Related dead code: `ContextManifestRow` data (`app_owned/context_manifest.py`) is
loaded into the snapshot but the builder hard-codes the same filters, so the
manifest documents behavior rather than controlling it. That is app-owned, not a
client concern, but it is a second source of truth that can drift.

## Prompt-only columns (no code logic, model interprets)

- post_blueprint: `page_area`, `purpose`, `source_type`, `content_role`,
  `target_paragraphs` (all filled).
- story_patterns: `angle_de`, `avoid_de`, `semantic_prompt_hints`. The code logic
  uses only trigger tags, required facts, signals, `priority`, `use_when_de`,
  `prompt_fragment_de`.
- agent_instructions: `conflict_policy`, `source_reference`, `notes_de`. Only
  `instruction_de` becomes a system rule; the rest travels in context. In particular
  `conflict_policy` looks like it controls precedence, but no code enforces it.
- seo_rules: `action_type` (`generator`/`validator`), which duplicates `stage`
  (`generation`/`validation`); only `stage` filters.
- post_examples: `input_facts_text`, `example_content`, `learning_for_gpt` are
  intentionally model-facing and referenced by name in the prompt. This is a
  legitimate use, just not code logic.

These are not necessarily bad, but a user editing them gets no validation and
no guarantee of effect. The documentation should say so explicitly, and
columns that imply enforcement (`conflict_policy`, `max_patterns`, `action_type`)
are the most misleading.

## Wired but empty in V9

Features exist in code but this workbook never uses them, which makes them hard
to discover and to test: ACF `validation_rule` (0/102), shared `min_characters`
(0/12), story `excluded_tags` (0/6), seo `context_tags` (0/25). Also 3
disabled internal links, 1 disabled shared field and the disabled `location`
post type (no ACF rows). Keep documented; decide per case whether to test or drop.

## Checks I made so absence of references is not misread

- `validation_lists` families with no direct code reference: `client_type` and
  `publish_status` are used dynamically through the `format_or_enum` cell of one
  field each. `session_state` and `blueprint_target_type` have no references at
  all and appear unused (candidates to delete or to wire into validation).
- Every `*_de` column is read. The suffix suggests German, but several hold
  model instructions; for a non-German client the name is misleading. Flag for the
  documentation rather than renaming now.

## Maintenance hazards (these drive the "too complicated" problem)

1. **Dropdowns point at fixed cell ranges.** For example
   `validation_lists!$B$36:$B$42` and `prompt_guidance!$A$2:$A202`, with
   inconsistent ends (`$A$253`, `$A$255`) in the same column. Adding a list value or
   guidance row does not extend the dropdown, and a row appended by phase 2 would not
   be offered in it. Named ranges or open-ended ranges would fix this.
2. **Most cross-references are checked, some are not.** The validator catches
   unknown post types, guidance keys, taxonomies, tags, signals and
   shortcode variables. It does not centrally check uniqueness of `link_id`,
   seo/style `rule_id`, story `pattern_id`, `image_metadata_schema.field_key`
   or blueprint order. No duplicates exist today (verified), but phase 2 appends
   could create them.
3. **Duplicate taxonomy concept.** `assign_taxonomy_to_media` exists on
   both post_types (used) and the taxonomy model (legacy compatibility), and the
   loader still contains a migration path for taxonomy columns on post_types.
4. **Encoded mini-languages in cells**: `condition`, `display_condition`,
   `generation_condition`, taxonomy sources like `acf:<field>`, semicolon lists,
   and `format_or_enum` values mixing enum names and formats (`DD.MM.YYYY`).
   These need a documented grammar and examples.
5. **Required but meaningless columns** (see Dead) force every new client to fill
   values nobody reads.
6. **Mandatory tab set is unclear.** `REQUIRED_SHEETS` lists 13 tabs and
   `taxonomies` is required in practice; `prompt_guidance` and `HTML_patterns` are
   optional. Nothing tells a new customer what a minimal workbook is.
7. **Weak failure feedback in Sheets.** Validation errors are reported with sheet,
   row and column in the API, but there is no friendly place where the client sees
   them (relevant to phase 1's status line).

## Proposed cleanup (not done; for decision)

1. Make the three post_types profile/status columns and `link_role` optional in the
   models, then drop them from the starter workbook; delete the stray
   `validation_lists 2` sheet and the empty extra columns in V9.
2. Drop or honour `max_patterns`, and decide whether `action_type` stays
   (suggest remove; `stage` already encodes it).
3. Decide on `conflict_policy`: enforce it or document it as informational.
4. Move the two dropdown-bearing lists to named ranges so appended rows join the
   dropdown; add central uniqueness checks for the missing ID columns.
5. Remove the legacy taxonomy migration path once no workbook relies on it.
6. Remove the unused `session_state` and `blueprint_target_type` families, or
   validate against them.
7. Generate the per-column reference (purpose, required, allowed values, consumer
   class from this audit) from the models, with a test that fails when a model
   field has no documented consumer, so the doc cannot drift.

Changing required columns affects the other client workbooks, so each change should
be checked against every client's workbook (only the pilot's
`flairlab workbook-DEV.xlsm` exists locally) and loaded with the
existing validator before merging.
