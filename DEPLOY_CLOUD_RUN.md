# Cloud Run Deployment Notes

## Required Environment Variables

For the first FLAIRLAB deployment, set these variables on the Cloud Run service:

```bash
gcloud run services update SERVICE_NAME \
  --region REGION \
  --set-env-vars IMPORT_API_KEY="YOUR_INTERFACE_API_KEY" \
  --set-env-vars OPENAI_API_KEY="YOUR_OPENAI_API_KEY" \
  --set-env-vars WP_BASE_URL="https://staging.flairlab.de" \
  --set-env-vars WP_USERNAME="YOUR_WORDPRESS_USERNAME" \
  --set-env-vars WP_APP_PASSWORD="YOUR_WORDPRESS_APPLICATION_PASSWORD" \
  --set-env-vars SESSION_STATE_GCS_PREFIX="gs://YOUR_BUCKET/session-states" \
  --set-env-vars KNOWLEDGE_WORKBOOK_GCS_URI="gs://YOUR_BUCKET/knowledge/FLAIRLAB_EventPost_Master_Knowledge.xlsm" \
  --set-env-vars KNOWLEDGE_SOURCE_POLICY="gcs_required" \
  --set-env-vars KNOWLEDGE_WORKBOOK_PATH="data/knowledge/FLAIRLAB_EventPost_Master_Knowledge.xlsm" \
  --set-env-vars KNOWLEDGE_WORKBOOK_SHEET="post type-specific output ACF"
```

`IMPORT_API_KEY` is the key the interface/custom action sends as the `X-API-Key` header.

`SESSION_STATE_GCS_PREFIX` is optional but recommended on Cloud Run. When set, each session state is written to and read from GCS (`<prefix>/<session_id>/state.json`), so sessions survive instance switches.

`KNOWLEDGE_WORKBOOK_GCS_URI` should point to the canonical workbook object. With `KNOWLEDGE_SOURCE_POLICY=gcs_required`, the app refuses to run if it cannot load from GCS, preventing silent fallback to an old local file.

`KNOWLEDGE_WORKBOOK_PATH` is the local cache path used after syncing from GCS. `KNOWLEDGE_WORKBOOK_SHEET` is optional; if omitted, the app picks the sheet containing `User field name`, `ACF field name`, and `AI guidance`, preferring sheet names with `ACF`, `output`, and `post`.

## Future Client-Specific WordPress Credentials

The OpenAI API key is shared by the app. WordPress credentials can be client-specific.

For a future client with `client_id=acme`, set:

```bash
gcloud run services update SERVICE_NAME \
  --region REGION \
  --set-env-vars ACME_WP_BASE_URL="https://client-site.example" \
  --set-env-vars ACME_WP_USERNAME="CLIENT_WORDPRESS_USERNAME" \
  --set-env-vars ACME_WP_APP_PASSWORD="CLIENT_WORDPRESS_APPLICATION_PASSWORD"
```

Requests can then pass:

```json
{
  "client_id": "acme"
}
```

If no client-specific variable exists, the app falls back to `WP_BASE_URL`, `WP_USERNAME`, and `WP_APP_PASSWORD`.

## Local `.env`

For local development, use `.env` in the project root. Do not commit it.

```text
IMPORT_API_KEY=...
OPENAI_API_KEY=...
WP_BASE_URL=https://staging.flairlab.de
WP_USERNAME=...
WP_APP_PASSWORD=...
SESSION_STATE_GCS_PREFIX=gs://YOUR_BUCKET/session-states
KNOWLEDGE_WORKBOOK_PATH=data/knowledge/FLAIRLAB_EventPost_Master_Knowledge.xlsm
KNOWLEDGE_WORKBOOK_GCS_URI=gs://YOUR_BUCKET/knowledge/FLAIRLAB_EventPost_Master_Knowledge.xlsm
KNOWLEDGE_SOURCE_POLICY=gcs_required
KNOWLEDGE_WORKBOOK_SHEET=post type-specific output ACF
```

## V2 Migration Configuration

Keep V1 as the default until V2 provider, UI and staging acceptance work is complete:

```text
CONTENT_PIPELINE_VERSION=v1
V2_KNOWLEDGE_WORKBOOK_PATH=data/knowledge/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm
V2_SESSION_ROOT=data/v2_sessions
V2_SESSION_GCS_PREFIX=gs://YOUR_BUCKET/v2-sessions
V2_LANGUAGE_MODEL=gpt-5.5
V2_VISION_MODEL=gpt-5.5
V2_TRANSCRIPTION_MODEL=gpt-4o-transcribe
V2_MAX_IMAGE_BYTES=20971520
V2_MAX_AUDIO_BYTES=52428800
```

Before deploying V2, place the validated V5 workbook at
`data/knowledge/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm` or set
`V2_KNOWLEDGE_WORKBOOK_PATH` to the synchronized local workbook path.

The file-backed `V2_SESSION_ROOT` is suitable for local development.
Set `V2_SESSION_GCS_PREFIX` on Cloud Run to use the GCS repository and object
storage adapters with optimistic object-generation checks.

V1 routes remain unchanged. V2 routes are available separately under
`/api/content-sessions`.
