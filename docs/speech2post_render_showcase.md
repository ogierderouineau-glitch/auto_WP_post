# SPEECH2POST Render Showcase Deployment

This deployment is intentionally limited to the `flairlab` client. It puts the
new Next frontend online without replacing or changing the current FastAPI
`/app` UI.

## Shape

- `speech2post-frontend`: Next web service, public phone-facing URL.
- `speech2post-backend`: existing FastAPI app, including `/app` and V2 routes.
- Google Cloud Storage: the existing canonical FLAIRLAB workbook bucket plus a
  separate Render-only bucket for V2 session JSON, images, and audio.
- Render environment secrets: temporary showcase injection for the import key,
  OpenAI key, and FLAIRLAB WordPress credentials.

Both Render services must stay in the same region. The committed
`render.yaml` selects Frankfurt and connects the frontend to the backend over
Render's private network.

## Before Creating The Blueprint

1. Push the intended commit to the Git provider connected to Render.
2. Confirm the existing canonical workbook is available at:

   ```text
   gs://auto-wordpress-post-499518-knowledge-workbook/knowledge/FLAIRLAB_EventPost_Master_Knowledge.xlsm
   ```

3. Confirm the separate Frankfurt data bucket exists:

   ```text
   gs://auto-wordpress-post-499518-speech2post-data
   ```

4. Confirm the Render identity exists:

   ```text
   speech2post-render@auto-wordpress-post-499518.iam.gserviceaccount.com
   ```

   It has `roles/storage.objectViewer` on the workbook bucket and
   `roles/storage.objectUser` on the data bucket. It cannot write to the
   canonical workbook bucket.
5. The JSON key is created outside the repository at
   `/tmp/speech2post-render-key.json`. Treat it as a credential, upload it to
   Render as described below, and delete the local copy afterwards.
6. Generate a new, long import key. Do not reuse a personal password.

## Create The Services

1. In Render, choose **New > Blueprint**.
2. Connect this repository. Render detects the root `render.yaml`.
3. During initial creation, enter every value marked `sync: false`:

   | Variable | Value |
   | --- | --- |
   | `IMPORT_API_KEY` | New long random showcase key |
   | `OPENAI_API_KEY` | Shared application OpenAI key |
   | `FLAIRLAB_WP_BASE_URL` | FLAIRLAB WordPress base URL |
   | `FLAIRLAB_WP_USERNAME` | FLAIRLAB WordPress username |
   | `FLAIRLAB_WP_APP_PASSWORD` | WordPress application password |
   The two GCS locations are committed as non-secret configuration and do not
   need to be entered in Render.

4. Create the Blueprint, but expect the backend's first deploy to fail until
   its Google credential secret file is added.
5. Open `speech2post-backend > Environment > Secret Files` and add:

   ```text
   Filename: gcp-service-account.json
   Contents: the complete contents of `/tmp/speech2post-render-key.json`
   ```

   Render exposes it at `/etc/secrets/gcp-service-account.json`, matching the
   committed `GOOGLE_APPLICATION_CREDENTIALS` setting.
6. Save and redeploy the backend. Then redeploy the frontend if its first build
   completed before the backend became healthy.

## Acceptance Check

Perform this from both phones over mobile data as well as Wi-Fi:

1. Open the `speech2post-frontend.onrender.com` URL.
2. Sign in as `flairlab` with the new import key.
3. Confirm the workbook/post types load.
4. Create a session.
5. Upload a picture smaller than 20 MiB.
6. Record or upload audio smaller than 25 MiB and confirm transcription.
7. Confirm facts and generate a draft.
8. Approve and publish to the intended FLAIRLAB WordPress environment.
9. Reload the page and recover the session from Recent Sessions.
10. Confirm the old backend `/app` URL still opens and works.

Use WordPress staging for the first complete run. Only point the credentials at
production after create/update behavior and returned links have been checked.

## Showcase Limits

- Authentication is one shared FLAIRLAB import key stored in browser
  `sessionStorage`; it is not the future 24-hour cookie login.
- Generate/publish jobs remain in one backend process. A Render restart or
  deploy loses job records, although completed GCS session changes survive.
- Do not redeploy during a showcase job.
- Video remains unsupported.
- Audio is capped at 25 MiB for predictable proxy uploads.
- Secrets are temporarily entered in Render. Moving client credential lookup
  entirely to Google Secret Manager is a separate multi-client hardening step.

## Operational Safety

- Keep both services on paid Starter instances during the showcase so they do
  not sleep.
- Set a small Render workspace spending limit/notification if available.
- Set a Google Cloud billing budget and GCS lifecycle rule only after deciding
  how long source media must be retained.
- Rotate the import key and service-account key after the showcase if either
  was shared outside the intended team.
- Never put `IMPORT_API_KEY`, WordPress credentials, OpenAI keys, or the Google
  JSON key in `render.yaml`, Git, frontend environment variables, or chat logs.
