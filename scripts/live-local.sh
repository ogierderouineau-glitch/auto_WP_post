#!/usr/bin/env bash
set -euo pipefail

SERVICE="${SERVICE:-auto-wp-post}"
PROJECT="${PROJECT:-auto-wordpress-post-499518}"
REGION="${REGION:-europe-west1}"
PORT="${PORT:-8000}"

echo "Proxying Cloud Run service ${SERVICE} to http://localhost:${PORT}"
exec gcloud run services proxy "${SERVICE}" \
  --project "${PROJECT}" \
  --region "${REGION}" \
  --port "${PORT}"
