# SEO keyword intelligence: implementation plan

**Status: proposal, not implemented.** Written 2026-11-11. Current code has no
keyword selection, WordPress scan, Search Console access or SEO check. Verify each
statement against the code before building on it.

## Goal

Speech2Post proposes keywords that fit the new post, avoids cannibalizing
existing pages, and generates content around the keywords the user selects.

Flow: facts extraction → keyword intelligence job (with progress status) → proposal
table → user multi-selects (or not) → generation and link candidates use the
selection. With no selection, the AI chooses keywords itself and records them.

## Decisions already made

- Data comes from live API scans. **No caching** (WordPress scan and Search Console).
  The cost is a slower step, covered by the progress status.
- No keyword workbook sheets. The pilot client's `keyword_register` and
  `search_console_monate` tables only showed the read structure
  (keyword, status, role, post type, URL / query, month, clicks, click delta).
- WordPress scan uses the best datapoint available per post: Yoast focus keyphrase
  (`_yoast_wpseo_focuskw`) if readable, otherwise slug + title (+ meta description).
- "Title and introduction contain the selected keywords" is a rule of the **pilot
  client**. It must live in that client's workbook instructions, not in shared code.

## Multi-client rules for this feature

- No German column names, client keywords, post types or field names in shared code.
- The title and introduction targets are resolved from the active workbook
  (shared/ACF output descriptors), never by hardcoded field names.
- Rules like "keyword must appear in title and intro" are workbook-configured; a
  client without the rule gets no such check.
- Each client uses its own WordPress and Search Console credentials. A missing
  source is skipped with a visible note, never replaced by another client's data.

## Data sources

### 1. WordPress scan
- Scan the posts of the session's post type, **including legacy posts written before
  the automation**. Several post types share one `wp_post_type` (for the pilot all
  use `post`), so they are told apart by category: a post counts when it has a
  category whose name equals the post type's `display_name_de` or `wp_category_name`
  (exact match, case-insensitive; clients correct names in the workbook). Plus the
  service pages listed in the **internal links tab** (`internal_links_database`):
  rows whose `category` is the client's service category, **regardless of
  `post_type_key`** ([InternalLinkRecord](../backend/app/knowledge_base/step_01_models.py)
  has `category` and `target_url`). Service pages are not tied to the selected post
  type. The category value ("service" for the pilot) is client data, so it comes
  from the client configuration instead of a constant in shared code. Without it
  configured, no service pages are scanned.
- Service rows are resolved to WordPress entries by `target_url` (slug lookup
  across the site's REST-enabled types, since the row has no WordPress type). Rows
  that cannot be resolved are listed in the job result and skipped.
- Request `id, slug, title, link, status` plus meta, paginated (`per_page=100`).
- Focus keyphrase: [speech2post-rest-compat.php](../integrations/wordpress/speech2post-rest-compat/speech2post-rest-compat.php)
  currently registers only the Open Graph keys, and only for post type `post`.
  Needed change: also register `_yoast_wpseo_focuskw` (read-only, `show_in_rest`)
  for all REST-enabled post types. This is a **WordPress-side change the client
  must deploy**. Pages not covered by it fall back to slug + title.
- Each scanned entry gets `focus_keyphrase` (or null), `slug`, `title`, `url`,
  `source` (`yoast` or `slug_title`).
- Classifying "used as focus elsewhere" vs "only mentioned": with Yoast data this is
  an exact match on the focus keyphrase. Without it, the AI only judges slug/title
  overlap and labels the result as an estimate.

### 2. Google Search Console
- API `searchanalytics.query` for the client's property: dimension `query`, last
  the last 3 months up to today (the console's "3 months" view), one total per query, with
  the click change versus the 3 months before. Up to 25,000 queries per window are read.
- Credentials per client in `clients.json` (property URL plus service-account
  reference; the service account must be added as a user in Search Console).
  Documented in README/deployment guide when built.
- Unconfigured or failing: the job continues without it and shows that no
  measured values were available. Terms without values stay usable.

## Implementation steps

### Milestone A: scan and proposal table (implemented; UI not yet checked in a browser)
1. **Config:** add the Search Console fields to the client JSON schema, the container
   ([step_03_container.py](../backend/app/api/step_03_container.py)) and docs.
2. **Providers:** new `WordPressSiteScanner` (REST pagination) and
   `SearchConsoleProvider`, built per client by the container like other providers.
   Both return plain typed rows; each is unit-tested with mocked HTTP.
3. **Plugin:** update the REST compat plugin once, exposing a broad set of Yoast
   meta so it does not need touching again. Register them for every REST-enabled
   post type, bump the version and update its README. The app only reads these
   keys; the plugin keeps the same `edit_posts` permission as the existing keys so
   Yoast's own editor saving is not affected.
   - Needed now (read-only): `_yoast_wpseo_focuskw` (focus keyphrase).
   - Likely useful soon (read-only): `_yoast_wpseo_keywordsynonyms`,
     `_yoast_wpseo_focuskeywords` (related keyphrases, Premium, JSON string),
     `_yoast_wpseo_title`, `_yoast_wpseo_metadesc`, `_yoast_wpseo_linkdex` (SEO score),
     `_yoast_wpseo_content_score` (readability score), `_yoast_wpseo_is_cornerstone`,
     `_yoast_wpseo_canonical`, `_yoast_wpseo_meta-robots-noindex`,
     `_yoast_wpseo_primary_category`.
   - Also included, so the plugin is not updated again later:
     `_yoast_wpseo_twitter-title`, `_yoast_wpseo_twitter-description`,
     `_yoast_wpseo_opengraph-image`, `_yoast_wpseo_bctitle` (breadcrumb title).
   - Verify each key against the pilot's installed Yoast version (Premium-only keys
     simply stay empty on free installs). Keep the field list in one array so a
     later addition is a one-line change.
4. **Service:** `keyword_service` in `backend/app/` (new folder) that takes facts,
   post type, scanned entries and Search Console rows, and makes one structured AI
   call returning candidates: `keyword`, `alternatives[]`, `status`
   (`free` / `focus_elsewhere` / `mentioned_elsewhere`), `conflicting_url`,
   `clicks`, `click_delta`, `rationale`. Prompt text lives in the app-owned
   instructions; client rules come from the workbook.
   Built in `backend/app/keywords/`: the service gives the model numbered refs for
   existing pages and checks the answer in code. An exact Yoast focus-keyphrase match
   forces `focus_elsewhere`, unknown refs are dropped, and clicks/impressions/change
   come from Search Console data, never from the model. Phrases are compared ignoring
   case, spaces and hyphens. It reuses the session service's retrying structured call.
5. **Session model:** persist `keyword_proposal` (candidates, scan time, sources
   used) and `selected_keywords`. Selection mutations use `expected_version`,
   ownership and active-job checks like existing routes.
6. **Routes/job:** `POST /{session_id}/keywords/scan` as a job (existing executor
   and polling), `GET .../keywords`, `PUT .../keywords/selection`. Progress stages:
   "Scanning WordPress", "Reading Search Console", "Analysing keywords".
7. **Frontend:** the new Screen 3 (between Facts and Content, see
   [seo_diagnostic_proposal.md](seo_diagnostic_proposal.md)) with a table (keyword,
   alternatives, status, clicks, change) and multi-select. Selecting nothing is
   allowed. Adapters in `frontend/lib/content-sessions.ts`.
8. **Tests:** arbitrary post-type keys, an unrelated industry, no-Yoast fallback,
   missing Search Console, and client isolation.

### Milestone B: generation and links (implemented, no UI yet)
1. Pass `selected_keywords` (or the AI-chosen ones, recorded in the session) into
   the generation context for title, slug and introduction, filtered per the
   existing context rules.
2. The workbook-configured rule (keyword in title and intro) enters through that
   client's agent instructions or SEO constraints. Add validation only when the
   workbook declares the rule.
3. Boost link candidates whose keyword/anchor overlaps the selected keywords in
   [internal_links/step_01_service.py](../backend/app/internal_links/step_01_service.py).
4. Open question to confirm: "ACF content should stem from WordPress fields
   content, slug drives title + introduction". Proposed reading: the focus keyword
   shapes the slug, and title and introduction derive from it, via workbook
   generation rules. Confirm before building.
5. Regeneration keeps the selection; changing the selection offers regeneration
   through the existing confirmation hook.

### Milestone C: Quality check container and SEO check
1. The Quality check container ([content-screen.tsx](../frontend/components/content-screen.tsx))
   shows as soon as a post exists, with the run button active.
2. Two subsections: the existing internal findings (shown after that run) and a new
   SEO subsection with its own button and results.
3. Deterministic SEO checker (see effort below) in `backend/app/validation/`,
   reading the real WordPress/ACF/Yoast field values from the payload.
4. "Revise content" sends the failed checks into the existing targeted-revision job.
5. False positives: checks run on the fields the workbook declares, not only
   `post_content`, and each check can be disabled per client in the workbook.

## Effort to replicate Yoast

Exact score parity is not realistic: Yoast's analysis runs in the browser, and for
German it uses its own stemming and word lists. A faithful port is a large,
language-specific project, so the plan does not attempt one.

| Part | Effort | Plan |
|---|---|---|
| ~8-10 SEO checks: keyphrase in title/intro/slug/meta description, meta description and title length, subheadings with keyphrase, keyphrase density, image alt text, internal/outbound links, text length | About 1-2 days, roughly 250-350 lines plus tests | Build. Results are traffic lights, not a Yoast score |
| Keyphrase matching (inflected forms) | A simple normalised/word-stem match is cheap but approximate | Accept approximation; let the AI judge borderline matches |
| Readability (sentence length, passive voice, transition words) | Several days per language, large word lists | Not built; the existing AI quality review covers readability |
| Reading stored scores (`_yoast_wpseo_linkdex`, content score) | Small | Optional reference only; stale for API-created posts until opened in the editor |

## Pilot workbook instructions (proposal for `agent_instructions`)

Client rules live in the client's workbook, not in code. The app will give the
generation context three new keys when a keyword proposal or selection exists:
`selected_keywords` (ordered; the first one is the focus keyphrase),
`keyword_alternatives` (keyword → variants) and `keyword_conflicts` (every focus
keyphrase found on the site scan → the URLs using it, the post's own URL excluded;
present whenever a proposal ran). The condition must be `always`
(context only understands `always` or a content signal).

**1. Replace the text of `client_010`.** It refers to `keyword_register`, which the
app does not provide:

> Wenn keyword_conflicts (Zuordnung Fokus-Keyphrase zu URLs) im Kontext verfügbar ist:
> eine Fokus-Keyphrase, die dort bereits als Fokus einer anderen URL belegt ist, nicht
> erneut als Fokus wählen; stattdessen eine Alternative aus keyword_alternatives oder
> ein anderes Keyword verwenden. Die Verwendung eines Begriffs nur als Textbegriff sperrt
> keinen neuen Fokus. Kein Fokus-Zwang bei fehlender Relevanz. Für Barkeeper-Profile
> gilt die profilspezifische Buchungsregel.

**2. New row `client_015`** (scope `global`, post_type_key `*`, workflow_stage
`generation`, applies_to `focus_keyword`, owner `language_model`, priority `high`,
condition `always`, conflict_policy `higher_priority_wins`):

> Wenn selected_keywords im Kontext verfügbar ist: Das erste Keyword ist die
> Fokus-Keyphrase und wird unverändert in focus_keyword gesetzt. Den slug zuerst aus
> dieser Fokus-Keyphrase bilden (ohne Füllwörter); post_title, seo_title und die
> Einleitung (hero_intro bzw. das Einleitungsfeld des Post-Typs) leiten sich daraus ab.
> Die Fokus-Keyphrase kommt in slug, post_title, seo_title (möglichst weit vorn),
> meta_description und in den ersten ein bis zwei Sätzen der Einleitung vor. Weitere
> Keywords aus selected_keywords nimmt die Einleitung und der Titel auf, soweit es
> natürlich klingt; mindestens einmal kommt jedes weitere Keyword im übrigen Text vor.
> Varianten aus keyword_alternatives und grammatisch angepasste Wortformen sind
> erlaubt. Kein Keyword-Stuffing: Lesbarkeit und belegte Fakten haben Vorrang. Die
> Regel zu post_title und hero_h1 (keine gleiche Formulierung) bleibt bestehen.
> Ohne selected_keywords wählt die KI die Keywords selbst nach client_010.

Suggested `expected_behavior`: "Fokus-Keyphrase in Slug, Titel, SEO-Titel,
Meta-Beschreibung und Einleitung; weitere Keywords natürlich im Text."
`source_reference`: "SEO-Experten-Workflow".

Decisions this wording makes: only the focus keyphrase is mandatory in title and
introduction (several keywords cannot all fit a title), and the selection order marks
the focus. The Screen 3 table therefore needs a way to mark or reorder the primary
keyword. The context keys above are not built yet (next implementation step).

## SEO check (milestone C, implemented)

`GET /{session_id}/seo-check` runs `backend/app/validation/step_02_seo.py` on the current draft: no model call,
nothing saved, so it is never stale. Yoast/WordPress fields are found through their destination keys
(`yoast_wpseo_focuskw`, `yoast_wpseo_title`, `yoast_wpseo_metadesc`, WordPress `title` and `slug`), so no client field
names are in code. Which ACF fields are the heading, introduction or body, and which length limits apply, come from
`seo_rules` rows. Rows use `stage` = `quality_check` (generation prompts never load them), and these new `action_type`s:

| action_type | value | meaning |
|---|---|---|
| `check_role` | `heading`, `introduction` or `body` | focus keyphrase (or an alternative) in the heading; in the first two sentences of the introduction; body text feeds the density check |
| `check_length` | `min;max` (characters) | length limit for that field |

Checks: focus keyphrase set; not used by another scanned page (own URL excluded); in post title, SEO title (and near
its start), meta description, slug (umlaut spellings and dropped short words tolerated), heading, introduction; other
selected keywords used somewhere; density 0.5-3% (only with 100+ words); internal links placed; configured lengths.
Text is compared without HTML, shortcodes and `{{ }}` markers, with small word endings and compound spellings tolerated
(false-positive handling for ACF content, which Yoast does not see). A published post's slug is never offered for revision.
After publishing, the check also shows the scores Yoast stored on WordPress as a read-only reference.

Pilot rows to add to `seo_rules` (columns: rule_id, enabled, post_type_key, target_type, target_key, stage, action_type,
instruction_de, value, value_type, condition, priority, source; `example` and `context_tags` may stay empty):

| rule_id | target_key | action_type | value | instruction_de |
|---|---|---|---|---|
| seo_check_01 | hero_h1 | check_role | heading | SEO-Check: Die Fokus-Keyphrase oder eine Alternative soll in der Hauptüberschrift vorkommen. |
| seo_check_02 | hero_intro | check_role | introduction | SEO-Check: Die Fokus-Keyphrase steht in den ersten ein bis zwei Sätzen der Einleitung. |
| seo_check_03 | event_story | check_role | body | SEO-Check: Haupttext für die Keyword-Dichte. |
| seo_check_04 | meta_description | check_length | 120;156 | SEO-Check: Meta-Beschreibung 120 bis 156 Zeichen. |
| seo_check_05 | seo_title | check_length | 30;60 | SEO-Check: SEO-Titel 30 bis 60 Zeichen. |

All rows: enabled TRUE, post_type_key `*`, target_type `field`, stage `quality_check`, value_type `string`, condition
`always`, priority `medium`, source `SEO-Experten-Workflow`. Other post types with differently named fields get their own rows (no need to rename ACF fields or templates; a row only applies where its field exists). A post type with no heading or introduction row shows a "not applicable" note in the SEO check.

## Resolved and open questions

Resolved:
- Service pages come from the internal links tab rows whose `category` is the
  client's service category, independent of post type.
- The title/introduction keyword rule is configured in the client file, not in code.

Open:
1. The pilot runs Yoast SEO Premium 28.8 (reported by the user, 2026-11-12), so
   Premium keys such as related keyphrases can exist. Still confirm the actual keys
   returned by REST after the plugin update, then deploy the updated plugin (step A3). Verification method: after deployment, one
   read-only REST request for an existing post shows which keys come back.
2. Search Console access: the app reads data through a Google service account,
   which is a robot login with its own email address. Someone with owner rights in
   the client's Search Console must add that address under Settings → Users and
   permissions (read access is enough). Setup steps:
   1. In Google Cloud Console, create or choose a project and enable the
      "Google Search Console API".
   2. Create a service account (IAM → Service accounts) and a JSON key. The key is a
      secret: store it like the other credentials, never in Git or browser code.
   3. In Search Console (property owner), add the service account's email as a
      user with read access.
   4. Put the property URL and key reference into the client's `clients.json`.
