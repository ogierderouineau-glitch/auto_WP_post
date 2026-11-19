# Project priorities for every coding agent

For current architecture, local setup, known gaps and continuation instructions,
read [docs/agent_handoff.md](docs/agent_handoff.md) before implementation. Keep
affected documentation current when changing architecture or behavior.

## First priority: support multiple clients across different industries

Speech2Post is a multi-client, industry-independent application. Flairlab is one
client, not the application's business model. Apply this requirement to every
design, implementation, prompt, migration and review in this repository.

- Keep shared application code generic. Never hardcode client names, industries,
  post types, ACF field names, retrieval tags, business facts or writing rules
  from an individual client's examples into shared runtime logic.
- Load client-specific behavior from the active client's workbook and configuration.
  Adding a client, industry or configured post type should not require changes to
  shared business logic.
- Keep client data, sessions, credentials, examples and generated context isolated.
  Never use another client's data as a fallback.
- Treat client examples used in tests as fixtures, not as the complete set of
  supported scenarios. Check configurable behavior with unrelated industries and
  arbitrary post-type keys where relevant.
- Before completing a change, check whether it would work for a different client
  in a different industry. Remove accidental assumptions instead of adding
  client-specific branches.

## Collaboration and code simplicity

The user is learning and is most familiar with JavaScript, HTML and CSS. Explain
significant tradeoffs plainly, question questionable assumptions, and flag when
a seemingly simple request would require substantial extra code. Prefer clean,
understandable implementations with as few lines as practical.

## User-facing error messages

Users are people running a business, not developers, and repeated unclear errors are
frustrating. Every error a user can see follows these rules:

- **Say what happened and what to do, in plain language, first.** No HTTP codes, field
  paths or library names in the first sentence. Name the thing involved (file, field, post type).
- **Keep the raw error after it** as `(Technical details: ...)` so it can be debugged. Build the text with
  `explain(friendly, raw)` in [backend/app/errors.py](backend/app/errors.py); never drop the raw text.
- **Say who can fix it.** The user can fix it: say how (list the allowed values, file types,
  size limit in MB, link types). Site or setup problem: "send this to your WordPress administrator".
  Unknown bug: `report_hint()` (uses `V2_SUPPORT_CONTACT`).
- **Raise a `V2Error` subclass, never a bare `ValueError` or `RuntimeError`, for anything a user
  can trigger.** An unhandled exception is turned into a generic "unexpected error" with a
  reference id, which is a last resort, not a design.
- **Stale screens use `SessionVersionConflictError`** (409): it tells the user to reload the page (F5)
  and says the session is kept. Never show "version X to Y" as the main message.
- **Reuse the shared helpers** instead of writing new wording: `ai_failure_message` (AI provider
  errors), `size_label` (sizes in MB, never bytes), `http_error_hint` and `unknown_term_message`
  in [backend/wordpress_api.py](backend/wordpress_api.py), `LINK_HELP` in
  [backend/app/storage/step_02_uploads.py](backend/app/storage/step_02_uploads.py). Add a helper
  when a second place needs the same wording.
- **Frontend:** show the API's message through `<ErrorText text={...} />`
  ([frontend/components/error-text.tsx](frontend/components/error-text.tsx)): it folds
  "(Technical details: ...)" behind a toggle and makes links clickable. `lib/api.ts` only rewrites a
  bare 5xx into "server temporarily unavailable". Do not add per-screen rewording, and do not print
  an error message as plain text.
- **Generic wording only.** No client names, industries or post types in shared messages.
- Add a test when you add a translation rule (see `backend/tests/test_user_error_messages.py`).
