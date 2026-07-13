#!/usr/bin/env bash
set -euo pipefail

SERVICE="${SERVICE:-auto-wp-post}"
PROJECT="${PROJECT:-auto-wordpress-post-499518}"
REGION="${REGION:-europe-west1}"
REPO="${REPO:-cloud-run-source-deploy}"
IMAGE_NAME="${IMAGE_NAME:-auto-wp-post}"
TAG="${TAG:-quick}"
ALLOW_UNAUTH="${ALLOW_UNAUTH:-1}"
OPENAI_API_KEY_SECRET="${OPENAI_API_KEY_SECRET:-projects/1082635308061/secrets/auto-wp-post-openai-key}"

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${IMAGE_NAME}:${TAG}"

echo "Building image: ${IMAGE_URI}"
gcloud builds submit --tag "${IMAGE_URI}"

DEPLOY_CMD=(
  gcloud run deploy "${SERVICE}"
  --image "${IMAGE_URI}"
  --project "${PROJECT}"
  --region "${REGION}"
  --set-secrets "OPENAI_API_KEY=${OPENAI_API_KEY_SECRET}:latest"
)

if [[ "${ALLOW_UNAUTH}" == "1" ]]; then
  DEPLOY_CMD+=(--allow-unauthenticated)
fi

echo "Deploying service: ${SERVICE}"
"${DEPLOY_CMD[@]}"

echo "Done."
