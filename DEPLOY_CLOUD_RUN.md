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
  --set-env-vars KNOWLEDGE_WORKBOOK_PATH="data/knowledge/FLAIRLAB_EventPost_Master_Knowledge.xlsm" \
  --set-env-vars KNOWLEDGE_WORKBOOK_SHEET="post type-specific output ACF"
```

`IMPORT_API_KEY` is the key the interface/custom action sends as the `X-API-Key` header.

`KNOWLEDGE_WORKBOOK_PATH` points to the bundled workbook used for AI field guidance. Replace the workbook file and redeploy to activate a new durable version. `KNOWLEDGE_WORKBOOK_SHEET` is optional; if omitted, the app picks the sheet containing `User field name`, `ACF field name`, and `AI guidance`, preferring sheet names with `ACF`, `output`, and `post`.

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
KNOWLEDGE_WORKBOOK_PATH=data/knowledge/FLAIRLAB_EventPost_Master_Knowledge.xlsm
KNOWLEDGE_WORKBOOK_SHEET=post type-specific output ACF
```
