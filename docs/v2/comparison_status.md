# V1/V2 Comparison Status

V1 remains the default (`CONTENT_PIPELINE_VERSION=v1`), so the UI has not been
switched prematurely.

Automated V2 assertions already confirm:

- required shared and ACF fields are validated;
- `hero_h1` and `verlauf_h2` route to actual ACF destinations;
- Yoast destinations come from workbook metadata;
- image-free sessions omit image workflow and blueprint output;
- internal links can only use eligible database IDs;
- WordPress payload construction does not use CSV or ZIP.
- the familiar UI can run the V2 local workflow through required-fact review,
  generation and draft save without browser console/network/runtime errors.

Still required before the default switch:

1. Run representative manual-text, voice-only, image and no-image inputs through V1 and V2.
2. Compare factual consistency, required fields, ACF/Yoast destinations, images and links.
3. Publish an approved V2 draft to staging WordPress.
4. Record intentional text/structure differences.

Identical prose is not required.

Utility:

```bash
myenv/bin/python tools/v2_compare_payloads.py \
  --v1 /path/to/v1_payload.json \
  --v2 /path/to/v2_payload.json \
  --output data/audits/v1_v2_comparison.json
```
