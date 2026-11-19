# SEO site diagnostic and new Screen 3: proposal

**Status: proposal, not implemented.** Written 2026-11-13. It builds on
[seo_keyword_intelligence_plan.md](seo_keyword_intelligence_plan.md), which is also
unimplemented beyond the scan/Search Console providers already committed.

## Why

Scanning the pilot's staging site for the `event` post type (19 event posts and 20
service pages) already exposed problems nobody had listed:

- two pages sharing a focus keyphrase ("Mobile Bar mieten Berlin" on an event post
  and a service page; "Kaffee-Catering" on two service pages);
- a keyphrase that does not fit its page ("Messe" on a page about multilingual
  bartenders);
- a service URL in the internal links tab that does not exist on the site;
- many event posts with close variants of the same phrase ("... Store-Event").

The same scan data the keyword proposal needs can produce this report. It is a
**side quest**: optional, separate from writing a post, and never required.

## Where it lives: new Screen 3

Workflow today: Media → Facts → Content → WordPress. Proposed:

**Media → Facts → Keywords (new) → Content → WordPress**

Screen 3 gets two tabs, so there is room for an interactive page:

| Tab | Bound to | Purpose |
|---|---|---|
| **Keywords for this post** | the open session | Proposal table, alternatives, multi-select (milestone A of the keyword plan) |
| **Site diagnostic** | the client, not a session | Optional audit of keyword use across the site |

Skipping the screen is allowed: with no selection the AI picks keywords itself,
exactly as the keyword plan already says.

## Diagnostic design

**Scope selection.** The user ticks one or more post types (chips from the active
workbook's enabled post types) and toggles "include service pages". A run scans the
same set the keyword proposal would: posts matched by category name
(`display_name_de` or `wp_category_name`, exact match) plus internal-links rows in
the client's service category.

**Checks.** Deterministic first, so most of the report costs nothing:

| Check | Signal |
|---|---|
| Duplicate focus keyphrase | Same normalised phrase on two or more pages (cannibalization) |
| Near-duplicate keyphrases | High word overlap between different phrases; optional AI step labelled as an estimate |
| Keyphrase not on the page | Phrase missing from slug, title and meta description |
| Missing focus keyphrase | Page fell back to slug and title |
| Broken registry row | Internal-links service URL not found on the site |
| No demand | Phrase with zero Search Console impressions in the last months |
| Opportunity | Search Console query with impressions that no scanned page targets |
| Weak or hidden page | Stored Yoast SEO score low, noindex set, or meta description missing |

Phrase normalisation must be language-neutral and tolerant of compounds and hyphens
("Kaffeecatering" vs "Kaffee-Catering"); thresholds are configuration, not
client-specific code.

**Result view.** Summary cards (count per check, with severity), then a table grouped
by check: page type | URL | keyword | issue | related URLs. Clicking a row shows the
competing pages and Search Console numbers. Two actions per row:
- **Use in current post:** pushes an opportunity or an alternative keyword into the
  Keywords tab selection;
- **Export CSV** of the whole report.

**Read-only.** No write-back to WordPress in the first version. Changing live pages'
SEO fields is outward-facing, so it deserves a separate, deliberate feature.

## Implementation steps

1. **Shared snapshot service:** one function that gathers scan entries and Search
   Console rows for a client and scope. The keyword proposal and the diagnostic both
   use it, so there is one place that talks to the providers. No caching.
2. **Check functions:** pure functions over the snapshot, one per check, each unit
   tested with arbitrary post-type keys and an unrelated industry.
3. **Job and routes.** The existing job machinery belongs to sessions
   (`session_job` in [step_02_routes.py](../backend/app/api/step_02_routes.py)), but
   the diagnostic is client-level. Two options:
   - **Recommended:** a small client-scoped job registry and endpoints
     (`POST /api/seo-diagnostic`, `GET /api/seo-diagnostic/jobs/{id}`), mirroring the
     session job behaviour. A moderate amount of new code.
   - Cheaper but hacky: run it inside whichever session is open. This breaks when no
     session exists, so I advise against it.
4. **Optional AI step:** near-duplicate clustering as one structured call over the
   short phrase list, run only when the user ticks a box.
5. **Frontend:** the new Screen 3 shell with the two tabs, the post-type chips, a
   run button with the same progress-status pattern as other jobs, the grouped
   result table and CSV export. The Keywords tab and this tab share the table and
   multi-select components.
6. **Docs and tests:** README section, handoff update, regression tests with a fake
   WordPress and Search Console like [test_seo_sources.py](../backend/tests/test_seo_sources.py).

## Effort and order

Build the keyword proposal first. The diagnostic then mostly reuses the scanner and
snapshot, so the extra cost is the checks (small), the client-level job (moderate)
and the interactive UI (the largest part).

## Open questions

1. Persist the last report per client so it opens instantly, or always run fresh?
   Default here: always fresh and not stored, matching the no-caching decision.
2. Who may run it: any authenticated user of the client, like the rest of the app?
3. Should the AI near-duplicate step be on by default or opt-in? Proposed: opt-in.
4. Which checks matter most to the pilot, so the first release can ship a subset?
