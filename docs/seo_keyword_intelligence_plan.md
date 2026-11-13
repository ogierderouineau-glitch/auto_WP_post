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
- Scan the REST collection of the session's configured `wp_post_type`, plus the
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
  3 complete months, per-month clicks and change versus the previous month.
- Credentials per client in `clients.json` (property URL plus service-account
  reference; the service account must be added as a user in Search Console).
  Documented in README/deployment guide when built.
- Unconfigured or failing: the job continues without it and shows that no
  measured values were available. Terms without values stay usable.

## Implementation steps

### Milestone A: scan and proposal table
1. **Config:** add the Search Console fields to the client JSON schema, the container
   ([step_03_container.py](../backend/app/api/step_03_container.py)) and docs.
2. **Providers:** new `WordPressSiteScanner` (REST pagination) and
   `SearchConsoleProvider`, built per client by the container like other providers.
   Both return plain typed rows; each is unit-tested with mocked HTTP.
3. **Plugin:** update the REST compat plugin once, exposing a broad set of Yoast
   meta so it does not need touching again. Register them for every REST-enabled
   post type, bump the version and update its README. Fields marked read-only get an
   `auth_callback` that allows reading but no app writes.
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
5. **Session model:** persist `keyword_proposal` (candidates, scan time, sources
   used) and `selected_keywords`. Selection mutations use `expected_version`,
   ownership and active-job checks like existing routes.
6. **Routes/job:** `POST /{session_id}/keywords/scan` as a job (existing executor
   and polling), `GET .../keywords`, `PUT .../keywords/selection`. Progress stages:
   "Scanning WordPress", "Reading Search Console", "Analysing keywords".
7. **Frontend:** after facts extraction, a keyword step with a table (keyword,
   alternatives, status, clicks, change) and multi-select. Selecting nothing is
   allowed. Adapters in `frontend/lib/content-sessions.ts`.
8. **Tests:** arbitrary post-type keys, an unrelated industry, no-Yoast fallback,
   missing Search Console, and client isolation.

### Milestone B: generation and links
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
