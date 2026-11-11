# Proposal: client workbooks hosted on Google Sheets

**Status: design only, nothing here is implemented.** Written 2026-11-11 against
the code in `backend/main.py`, `backend/app/api/step_03_container.py` and
`backend/app/knowledge_base/`.

## Goal

1. Each client edits its workbook directly in Google Drive; Speech2Post picks the
   change up without a manual download/upload.
2. Later: a client describes a change in plain language ("add this link", "turn
   off that post type") and the app edits the workbook for them.

## How workbooks work today

- `_configured_workbook_path` (container) resolves one file per client: a
  local `data/knowledge/{client_id}.xlsm`, or on Render a copy downloaded from
  GCS to `/tmp` before every service construction.
- `POST /app/knowledge/workbook` validates an upload, writes it to GCS and
  calls `reload_v2_knowledge_if_initialized()`.
- `KnowledgeBaseService` already hashes each validated workbook into an immutable
  `WorkbookSnapshot`, so "load, validate, swap" exists. `reload()` also validates
  before replacing the current snapshot, but a failing reload raises to the caller.
- `WorkbookLoader` reads with `openpyxl(data_only=True)`, so only cached cell
  values matter, never formulas or macros.

## Phase 1: Google Sheet as the source of truth

### Recommended design

**Native Google Sheet per client, read by a service account, pulled on demand.**

```text
Client edits Google Sheet
        │  (Drive version number changes)
        ▼
Backend: cheap metadata call (files.get?fields=version,modifiedTime)
   changed? ──no──► keep current snapshot
        │yes
        ▼
files.export as .xlsx  ─►  WorkbookLoader + WorkbookValidator (existing)
        │ valid                         │ invalid
        ▼                               ▼
KnowledgeBaseService swaps snapshot   keep last good snapshot,
(+ copy to GCS as last-known-good)    show sheet/row errors in the UI
```

Why this shape:

- **No new parsing code.** The export is an ordinary `.xlsx`; the loader and
  validator stay untouched. I checked the current workbook (`FLAIRLAB V9.xlsm`):
  17 sheets, ~4,900 cells, no macros (no `vbaProject.bin`), longest cell 4,960
  characters (Sheets allows 50,000), 26 formulas (exports carry computed values),
  dropdown validations (carried over by Sheets). Fidelity should be fine, but verify
  with a real converted copy before migrating a client (see "First steps").
- **Pull, not push.** Drive push notifications need a public webhook and
  channel renewal. A version check with a short cache (about 30-60 s) when a
  session starts or the workbook is read is far simpler and cheap.
- **Service account, shared per file.** The client clicks *Share* and adds the
  service account email (Viewer in phase 1). The existing GCP service account
  can be reused; Drive API must be enabled in that project. No OAuth consent
  screen or per-user tokens.
- **Last good snapshot wins.** People edit live, so half-finished edits will
  happen. An invalid version must never replace a valid one; the UI shows the
  validation error so the editor can fix it.
- **Free history.** Google keeps revisions, which gives rollback of bad edits.

### Rejected alternatives

| Option | Why not |
|---|---|
| `.xlsx` file kept in Drive, edited via Office mode | Weaker collaboration, awkward versions, no safe write API for phase 2 |
| "Publish to web" CSV | Public URL leaks business rules, one CSV per tab |
| Per-user OAuth | Token storage, consent screen and refresh handling for little gain |
| Drive push webhooks | Public endpoint + renewals; pull is enough here |

### Code shape (small)

- Introduce a tiny `WorkbookSource` seam in `knowledge_base/`: `current_version()`
  and `fetch(dest) -> Path`. Two implementations: the existing GCS/local logic
  moved out of `step_03_container.py`, and `GoogleSheetSource`.
- `GoogleSheetSource` uses `google.auth` with `AuthorizedSession` and two REST
  calls, so there is no new heavy dependency (`google-auth` is already installed
  through `google-cloud-storage`).
- `KnowledgeBaseService.current()` asks the source for its version (cached) and
  reloads when it changed; a failing reload keeps the old snapshot and records
  the error for `/health`/the UI.
- Per-client config in `clients.json`, for example
  `"storage": {"knowledge_source": {"type": "google_sheet", "file_id": "..."}}`.
  Clients without it keep the GCS/upload path, so migration is per client and
  nothing client-specific enters shared code.
- Frontend: for Drive clients, replace the upload control with *Open workbook in
  Google Sheets*, a *Refresh now* button (existing `/_workbook/reload`) and a
  status line (last synced version, current validation errors).
- Hide or disable `POST /app/knowledge/workbook` for Drive clients; otherwise
  an upload would be silently overwritten by the next sync.

Rough size: about 150-200 backend lines plus tests and a small UI change.

### Decisions (confirmed 2026-11-11)

- Old sessions always follow the latest valid workbook. Keep the current-snapshot
  fallback; no per-session pinning or version archive is needed.

### Open points

1. ~~**Old sessions and workbook changes.**~~ (decided, see above)
   Original question: Sessions store the workbook hash, but
   `by_hash` keeps snapshots only in memory and falls back to the current one
   (`V2_ALLOW_CURRENT_WORKBOOK_FALLBACK`). The recent feature importing new ACF
   fields into old sessions suggests the current workbook applying to old
   sessions is wanted. With live edits, hashes change often, so confirm that
   behavior is intended (the alternative is storing each adopted version in GCS
   by hash and pinning sessions to it).
2. **Who may edit the Sheet.** Anyone with edit access can change business rules
   and prompts. That is the client's own call, but the onboarding guide should say so.
3. **Local development.** Keep local `data/knowledge/*.xlsm`; only use the
   Google source when configured. While here, consider removing the
   "first `.xlsm` in the folder" fallback (known gap in the handoff).

### First steps

1. Upload `FLAIRLAB V9.xlsm` to Drive as a native Sheet, export it to `.xlsx`,
   and diff the loaded `WorkbookSnapshot` against the original (fidelity test).
2. Enable the Drive API, share the Sheet with the service account, call
   `files.get`/`files.export` from a script.
3. Implement the source seam and `GoogleSheetSource`, behind per-client config.
4. Migrate one client, run in parallel with the GCS copy for a week.

## Phase 2: natural-language workbook updates (exploration)

Feasible, but a different risk class: the model would write to the data that
steers every later generation. The design below keeps the model away from the
Sheet and puts deterministic checks between request and write.

```text
Request (text/voice)
  → model proposes structured OPERATIONS (not cell edits)
  → backend applies them to an in-memory copy of the latest export
  → WorkbookValidator on the result  (invalid → reject / one retry with errors)
  → diff preview shown to the user    (before → after, per row)
  → user confirms
  → write via Sheets API, only if the Drive version is unchanged since the preview
  → reload snapshot, append audit entry
```

Key points:

- **Operations, not free text.** A small closed set: `append_row`, `update_row`,
  `set_enabled`. No delete in the first version (disable instead, where the sheet
  has an enabled column). A per-request cap (for example 10 rows).
- **Schema comes from the workbook at runtime.** Sheet names, headers, dropdown
  values and key columns are read from the loaded workbook and models, then
  given to the model as the allowed vocabulary. Row identity (which row is "the
  link to /contact"?) needs a key per sheet; derive it from the loader's models or
  from a small app-owned table, never from one client's field names.
- **Allowlist of editable sheets.** Only client-owned sheets, never app-owned
  rules, never columns containing formulas.
- **Write with the Sheets API, never by uploading a modified `.xlsx`.** An
  openpyxl round-trip would flatten the client's formatting, comments and
  validations. Writes use `values.append` / `batchUpdate` with the
  service account promoted to Editor.
- **Optimistic concurrency.** Compare the Drive version at confirm time with the
  one used for the preview; if someone edited meanwhile, re-run the diff.
- **Audit and undo.** Log who, when, request text and operations (GCS per
  client); undo through Google revision history or inverse operations.
- **Identity gap.** Today there is one import key per client, so "who asked" is
  just the client. Fine for a first version, but note it in the audit log.

Lower-risk stepping stone to consider first: the assistant writes proposed rows
to a `proposals` tab in the Sheet, and a human copies the good ones. It validates
the prompt and the operation vocabulary before any automatic write exists.

Suggested prototype once phase 1 is stable: dry-run only (preview, no write),
limited to one or two sheets with simple keys (for example internal links, which
were previously imported via TSV), tested against two unrelated sample workbooks.

Estimated effort is substantially higher than phase 1 (operation schema, key
derivation, diff UI, Sheets write path, audit), so it should be a separate
decision after phase 1 has run with a real client.

## Agreed sequencing

Phase 2 depends on workbook work that is not coding the writer itself. Order:

1. **Phase 1**: Google Sheet source (above).
2. **Workbook documentation and cleanup** (prerequisite for phase 2):
   - Per-tab and per-column reference generated from the loader/models where
     possible, so it cannot drift from the code: purpose, required or optional,
     allowed values, which runtime component consumes it, and one worked example.
   - Audit of every tab and column (**done**, see [workbook_audit.md](workbook_audit.md)): *consumed by code*, *loaded but unused*, or
     *not loaded*. Unused ones are removed or marked deprecated (the loader
     already warns on deprecated app-owned sheets). Existing helpers:
     `tools/validate_workbook.py`, `tools/export_validation_reference.py` and
     `docs/reference/validation_choices.md`; `tools/knowledge_workbook_audit.py`
     still imports config names that no longer exist and needs repair or removal.
   - A "new client" starter workbook and a short onboarding guide, so a new
     customer does not start from the pilot client's 17 tabs.
   - Per-sheet key columns made explicit, because phase 2 row edits need them.
3. **Phase 2a, propose and preview**: requests become validated operations and a
   diff; nothing is written. Also tests the operation vocabulary against the
   pilot client's real requests (they already use ChatGPT for this, so collect
   a sample of those requests first).
4. **Phase 2b, confirmed write** through the Sheets API with version check,
   audit log and undo. Needs the careful testing the writer deserves: conflict
   cases, formula columns, validation lists and unrelated-industry fixtures.
