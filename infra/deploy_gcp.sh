#!/usr/bin/env bash
# Google Cloud side of the mesh: the ADK agent, the coordinator and the UI, three
# Cloud Run services. Gemini through Vertex AI with each service's own service
# account, so no API key is deployed.
#
#   ./infra/deploy_gcp.sh sa            # service accounts and roles (run first: the
#                                       # AWS and Azure trust policies pin the coordinator's)
#   ./infra/deploy_gcp.sh agent         # the ADK agent, private, A2A
#   ./infra/deploy_gcp.sh coordinator   # reads infra/mesh.env for the AWS and Azure legs
#   ./infra/deploy_gcp.sh ui            # public UI; prints its URL
#   ./infra/deploy_gcp.sh verify        # unauthenticated calls must be refused
#   ./infra/deploy_gcp.sh destroy
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
AR="${AR:-currency-mesh}"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/${AR}"
TAG="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || date +%s)"
MODEL="${GENAI_MODEL:-gemini-3.8-flash}"

AGENT_SVC=currency-mesh-gcp
COORD_SVC=currency-mesh-coordinator
UI_SVC=currency-mesh-ui
sa_email() { echo "$1@${PROJECT}.iam.gserviceaccount.com"; }
SA_AGENT="$(sa_email mesh-gcp-agent)"
SA_COORD="$(sa_email mesh-coordinator)"
SA_UI="$(sa_email mesh-ui)"
VERTEX_ENV="GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=global"

url_of() { gcloud run services describe "$1" --region "$REGION" --format='value(status.url)'; }

sa() {
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com aiplatform.googleapis.com iamcredentials.googleapis.com
  gcloud artifacts repositories describe "$AR" --location "$REGION" >/dev/null 2>&1 ||
    gcloud artifacts repositories create "$AR" --location "$REGION" --repository-format docker
  local name
  for name in mesh-gcp-agent mesh-coordinator mesh-ui; do
    gcloud iam service-accounts describe "$(sa_email $name)" >/dev/null 2>&1 ||
      gcloud iam service-accounts create "$name" --display-name "currency mesh: $name"
  done
  for sa in "$SA_AGENT" "$SA_COORD"; do
    gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$sa" \
      --role roles/aiplatform.user --condition=None >/dev/null
  done
  echo "coordinator SA ${SA_COORD}, unique id $(gcloud iam service-accounts describe "$SA_COORD" --format='value(uniqueId)')"
}

image() {  # name dockerfile context
  local img="${REGISTRY}/$1:${TAG}"
  gcloud builds submit "$3" --config "$REPO/infra/cloudbuild-image.yaml" \
    --substitutions "_IMAGE=${img},_DOCKERFILE=$2" >&2
  echo "$img"
}

agent() {
  local img url
  img="$(image mesh-gcp-agent agents/gcp/Dockerfile "$REPO")"
  gcloud run deploy "$AGENT_SVC" --region "$REGION" --image "$img" \
    --service-account "$SA_AGENT" --no-allow-unauthenticated \
    --cpu 1 --memory 2Gi --timeout 300 --min-instances 0 --max-instances 2 \
    --set-env-vars "${VERTEX_ENV},GENAI_MODEL=${MODEL}"
  url="$(url_of "$AGENT_SVC")"
  # Two-phase: the card advertises the service URL, which exists only now.
  gcloud run services update "$AGENT_SVC" --region "$REGION" --update-env-vars "PUBLIC_URL=${url}/"
  gcloud run services add-iam-policy-binding "$AGENT_SVC" --region "$REGION" \
    --member "serviceAccount:$SA_COORD" --role roles/run.invoker >/dev/null
  echo "GCP agent: $url"
}

coordinator() {
  local img envs f
  envs="${VERTEX_ENV},COORDINATOR_MODEL=${MODEL},GCP_A2A_ENDPOINT=$(url_of "$AGENT_SVC")/,GCP_A2A_AUTH=google-id-token"
  # Written by deploy_aws.sh env and deploy_azure.sh env.
  for f in "$REPO/infra/mesh.aws.env" "$REPO/infra/mesh.azure.env"; do
    [[ -f "$f" ]] || { echo "missing $f" >&2; exit 1; }
    envs+=",$(grep -vE '^\s*(#|$)' "$f" | paste -sd, -)"
  done
  img="$(image mesh-coordinator coordinator/Dockerfile "$REPO")"
  gcloud run deploy "$COORD_SVC" --region "$REGION" --image "$img" \
    --service-account "$SA_COORD" --no-allow-unauthenticated \
    --cpu 1 --memory 1Gi --timeout 600 --min-instances 0 --max-instances 2 \
    --set-env-vars "$envs"
  gcloud run services add-iam-policy-binding "$COORD_SVC" --region "$REGION" \
    --member "serviceAccount:$SA_UI" --role roles/run.invoker >/dev/null
  echo "coordinator: $(url_of "$COORD_SVC")"
}

ui() {
  local img
  img="$(image mesh-ui Dockerfile "$REPO/frontend-react")"
  gcloud run deploy "$UI_SVC" --region "$REGION" --image "$img" \
    --service-account "$SA_UI" --allow-unauthenticated \
    --cpu 1 --memory 1Gi --timeout 600 --min-instances 0 --max-instances 2 \
    --set-env-vars "COORDINATOR_URL=$(url_of "$COORD_SVC")/"
  echo "UI: $(url_of "$UI_SVC")"
}

verify() {
  local svc code
  for svc in "$AGENT_SVC" "$COORD_SVC"; do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$(url_of "$svc")/.well-known/agent-card.json")"
    echo "no token -> $svc: $code (expect 403)"
  done
}

destroy() {
  local svc
  for svc in "$UI_SVC" "$COORD_SVC" "$AGENT_SVC"; do
    gcloud run services delete "$svc" --region "$REGION" --quiet 2>/dev/null || true
  done
  gcloud artifacts repositories delete "$AR" --location "$REGION" --quiet 2>/dev/null || true
}

case "${1:-}" in
  sa|agent|coordinator|ui|verify|destroy) "$1" ;;
  url) url_of "$UI_SVC" ;;
  *) echo "usage: $0 {sa|agent|coordinator|ui|verify|url|destroy}" >&2; exit 2 ;;
esac
