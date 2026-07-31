# Deployment

The root `Dockerfile` builds the FastAPI backend. `render.yaml` defines the
backend and the `frontend/` Next.js service.

## Render backend

The backend uses these global environment variables:

```text
OPENAI_API_KEY=...
GOOGLE_CLOUD_PROJECT=auto-wordpress-post-499518
GCS_DATA_BUCKET=auto-wordpress-post-499518-speech2post-data
GCS_KNOWLEDGE_BUCKET=auto-wordpress-post-499518-speech2post-knowledge
GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/gcp-service-account.json
V2_MAX_IMAGE_BYTES=20971520
V2_MAX_AUDIO_BYTES=26214400
```

Add these Render secret files:

```text
/etc/secrets/clients.json
/etc/secrets/gcp-service-account.json
```

`clients.json` is the only source of client identity, access keys, WordPress
credentials, and client-relative storage paths. It must not be committed.

```json
{
  "flairlab": {
    "name": "FLAIRLAB",
    "country": "DE",
    "language": "de-DE",
    "import_api_key": "CLIENT_ACCESS_KEY",
    "wordpress": {
      "base_url": "https://flairlab.de",
      "username": "WORDPRESS_USERNAME",
      "app_password": "WORDPRESS_APPLICATION_PASSWORD"
    },
    "storage": {
      "session_prefix": "clients/flairlab/v2-sessions",
      "knowledge_workbook": "clients/flairlab/knowledge/current.xlsm"
    }
  }
}
```

Client IDs must contain only lowercase letters, digits, `_`, or `-`. Import
keys must be unique. The backend fails at startup if the file is missing or
invalid.

For client `flairlab`, the configured bucket names and relative paths resolve
to:

```text
gs://auto-wordpress-post-499518-speech2post-data/clients/flairlab/v2-sessions
gs://auto-wordpress-post-499518-speech2post-knowledge/clients/flairlab/knowledge/current.xlsm
```

The knowledge workbook is downloaded to the disposable runtime cache
`/tmp/speech2post/knowledge/flairlab.xlsm`. GCS remains the required canonical
source in production.

## Adding a client

Add one object to `clients.json`, using a new unique access key and
client-relative paths:

```json
{
  "acme": {
    "name": "ACME",
    "country": "DE",
    "language": "de-DE",
    "import_api_key": "ANOTHER_UNIQUE_ACCESS_KEY",
    "wordpress": {
      "base_url": "https://example.com",
      "username": "WORDPRESS_USERNAME",
      "app_password": "WORDPRESS_APPLICATION_PASSWORD"
    },
    "storage": {
      "session_prefix": "clients/acme/v2-sessions",
      "knowledge_workbook": "clients/acme/knowledge/current.xlsm"
    }
  }
}
```

Upload that client's workbook to its knowledge object before redeploying. The
backend validates every configured client workbook during startup.

## Local development

Place an ignored `clients.json` in the repository root using the same schema.
An `.env` file is optional; global values can instead be exported by the shell
or supplied by the IDE.

If GCS bucket variables are present, development uses the same isolated GCS
paths as production. Without them, it uses:

```text
data/knowledge/{client_id}.xlsm
data/v2_sessions/{client_id}
```

Use Google Application Default Credentials locally or set
`GOOGLE_APPLICATION_CREDENTIALS` to a credential file outside source control.

## Production verification

Before production use, verify authentication for each client, workbook
loading, session creation and recovery, media upload, transcription, draft
generation, and WordPress publication against staging.
