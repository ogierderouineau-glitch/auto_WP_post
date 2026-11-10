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
