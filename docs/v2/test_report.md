# V2 Test Report

Command:

```bash
V2_TEST_WORKBOOK=/home/ogier-derouineau/Downloads/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm \
  myenv/bin/python -m unittest discover -s tests/v2 -q
```

Result: **77 tests passed** on June 29, 2026.

Covered:

- workbook loading, exact joins, enums, dependencies and failure cases;
- workflow registry and condition skips;
- field-addressable context;
- clarification required/optional behavior and correction precedence;
- structured schemas, unknown-field rejection and word limits;
- separate fake-model extraction/generation/link-ranking tasks;
- internal-link self filtering, empty evidence and safe rendering;
- deterministic aggregation and WordPress/Yoast/ACF routing;
- image upload MIME/decode checks;
- workbook-driven Pillow processing and original preservation;
- optimistic repository versions;
- session ownership;
- strict OpenAI-compatible nullable schemas;
- voice-only transcription orchestration;
- complete image Vision/Pillow/metadata orchestration with fakes;
- upload-time image metadata generation without repeated Vision calls;
- publish-time image metadata refinement with confirmed facts, final draft context,
  and bartender/show-specific priority facts;
- old-UI publish recovery from already-approved `ready_to_publish` V2 sessions;
- old-UI/V2 recorded voice upload, fact-review table, and image metadata save routing;
- Vision-guided Pillow crop focus and visible operation reporting;
- V1/V2 payload comparison utility;
- complete image-free create/analyze/generate/approve/publish lifecycle;
- direct mocked WordPress REST publication with ACF and Yoast routing;
- stable API errors and OpenAPI registration.
- create-session → save-inputs API regression coverage;
- old-interface V2 adapter routing and explicit fact-confirmation coverage;
- regeneration of reviewed V2 drafts after direct field edits;
- optional ACF fields omitted unless their confirmed dependencies or content signals exist;
- synthetic smoke-test invariants for exact confirmed dates, unescaped facts HTML,
  and absence of unconfirmed bartender/focus/challenge facts.

A paid synthetic OpenAI smoke test was also run with `gpt-5.5`. It passed without
WordPress publication. Evidence is stored in
`data/audits/v2_live_generation_smoke.json`.
