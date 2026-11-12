#!/usr/bin/env bash
# Azure side of the mesh: the Agent Framework agent on Azure Container Apps,
# serving A2A behind Entra authentication, and the Entra app registration whose
# federated credential trusts the GCP coordinator's service account.
#
#   ./infra/deploy_azure.sh deploy   # AI account + model, ACR image, identities, env, app
#   ./infra/deploy_azure.sh fic      # Entra app registration + federated credential
#   ./infra/deploy_azure.sh auth     # require an Entra token at the ingress (401 otherwise)
#   ./infra/deploy_azure.sh env      # writes infra/mesh.azure.env for the coordinator
#   ./infra/deploy_azure.sh verify   # unauthenticated calls must get 401
#   ./infra/deploy_azure.sh destroy
#
# fic and auth are two halves: the federated credential decides who can obtain a
# token for this app, auth decides whether the app demands one.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RG="${RG:-currency-mesh-a2ui-rg}"
LOC="${LOC:-eastus2}"
SUFFIX="$(az account show --query id -o tsv | cut -c1-6)"
AI="${AI:-currency-mesh-ai$SUFFIX}"
MODEL="${MODEL:-gpt-5.4-mini}"
MODEL_CAPACITY="${MODEL_CAPACITY:-200}"
ACR="${ACR:-currencymesh$SUFFIX}"
ENV_NAME="${ENV_NAME:-currency-mesh-env}"
APP="${APP:-currency-mesh-azure}"
APP_REG="${APP_REG:-currency-mesh-a2ui-coordinator}"
TAG="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || date +%s)"
GCP_PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
COORD_SA="mesh-coordinator@${GCP_PROJECT}.iam.gserviceaccount.com"

app_url() {
  local fqdn
  fqdn="$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null)"
  [[ -z "$fqdn" ]] && { echo "container app not deployed" >&2; exit 1; }
  echo "https://${fqdn}"
}

identity() {
  az identity show -g "$RG" -n "$1" -o none 2>/dev/null || az identity create -g "$RG" -n "$1" -o none
  az identity show -g "$RG" -n "$1" --query "[id,principalId,clientId]" -o tsv
}
grant() {  # principal, role, scope
  az role assignment list --assignee "$1" --role "$2" --scope "$3" --query "[0].id" -o tsv | grep -q . ||
    az role assignment create --assignee-object-id "$1" --assignee-principal-type ServicePrincipal \
      --role "$2" --scope "$3" -o none
}

deploy() {
  echo "=== 1/5 resource group, AI account, model deployment ==="
  az group create -n "$RG" -l "$LOC" -o none
  if ! az cognitiveservices account show -g "$RG" -n "$AI" -o none 2>/dev/null; then
    # A deleted account is soft-deleted and keeps its name until purged.
    az cognitiveservices account purge -g "$RG" -n "$AI" -l "$LOC" -o none 2>/dev/null || true
    az cognitiveservices account create -g "$RG" -n "$AI" -l "$LOC" --kind AIServices \
      --sku S0 --custom-domain "$AI" --yes -o none
  fi
  local version
  version="$(az cognitiveservices model list -l "$LOC" \
    --query "[?model.name=='$MODEL'].model.version" -o tsv | sort -u | tail -1)"
  az cognitiveservices account deployment show -g "$RG" -n "$AI" --deployment-name "$MODEL" -o none 2>/dev/null ||
    az cognitiveservices account deployment create -g "$RG" -n "$AI" --deployment-name "$MODEL" \
      --model-name "$MODEL" --model-version "$version" --model-format OpenAI \
      --sku-name GlobalStandard --sku-capacity "$MODEL_CAPACITY" -o none
  local ai_id ai_endpoint
  ai_id="$(az cognitiveservices account show -g "$RG" -n "$AI" --query id -o tsv)"
  ai_endpoint="$(az cognitiveservices account show -g "$RG" -n "$AI" --query properties.endpoint -o tsv)"

  echo "=== 2/5 container registry and image (built in ACR) ==="
  az acr show -g "$RG" -n "$ACR" -o none 2>/dev/null || az acr create -g "$RG" -n "$ACR" --sku Basic -o none
  az acr build -r "$ACR" -t "currency-mesh-azure:$TAG" -f "$REPO/agents/azure/Dockerfile" "$REPO" -o none
  local acr_id registry="$ACR.azurecr.io"
  acr_id="$(az acr show -g "$RG" -n "$ACR" --query id -o tsv)"

  echo "=== 3/5 managed identities and roles ==="
  local pull_id pull_principal agent_id agent_principal agent_client
  read -r pull_id pull_principal _ <<<"$(identity currency-mesh-pull | paste -sd' ')"
  read -r agent_id agent_principal agent_client <<<"$(identity currency-mesh-agent | paste -sd' ')"
  grant "$pull_principal" AcrPull "$acr_id"
  grant "$agent_principal" "Cognitive Services OpenAI User" "$ai_id"

  echo "=== 4/5 Container Apps environment ==="
  az containerapp env show -g "$RG" -n "$ENV_NAME" -o none 2>/dev/null ||
    az containerapp env create -g "$RG" -n "$ENV_NAME" -l "$LOC" -o none

  echo "=== 5/5 agent app (external ingress, A2A on 8080) ==="
  local envs=(AZURE_OPENAI_ENDPOINT="$ai_endpoint" AZURE_OPENAI_DEPLOYMENT="$MODEL" AZURE_CLIENT_ID="$agent_client")
  if az containerapp show -g "$RG" -n "$APP" -o none 2>/dev/null; then
    az containerapp update -g "$RG" -n "$APP" --image "$registry/currency-mesh-azure:$TAG" \
      --set-env-vars "${envs[@]}" -o none
  else
    az containerapp create -g "$RG" -n "$APP" --environment "$ENV_NAME" \
      --image "$registry/currency-mesh-azure:$TAG" \
      --user-assigned "$pull_id" "$agent_id" --registry-server "$registry" --registry-identity "$pull_id" \
      --ingress external --target-port 8080 --transport http \
      --cpu 1 --memory 2Gi --min-replicas 1 --max-replicas 2 \
      --env-vars "${envs[@]}" -o none
  fi
  # Two-phase: the card advertises the ingress URL, which exists only now.
  az containerapp update -g "$RG" -n "$APP" --set-env-vars "PUBLIC_URL=$(app_url)/" -o none
  echo "Azure agent: $(app_url)"
}

fic() {
  local app_id sub body
  app_id="$(az ad app list --display-name "$APP_REG" --query '[0].appId' -o tsv 2>/dev/null)"
  if [[ -z "$app_id" ]]; then
    app_id="$(az ad app create --display-name "$APP_REG" --query appId -o tsv)"
    az ad sp create --id "$app_id" -o none 2>/dev/null || true
    echo "created app registration $APP_REG ($app_id)"
  fi
  # Pin the service account's numeric unique id, never its email.
  sub="$(gcloud iam service-accounts describe "$COORD_SA" --format='value(uniqueId)')"
  [[ -z "$sub" ]] && { echo "cannot read the unique id of $COORD_SA (run deploy_gcp.sh sa)" >&2; exit 1; }
  body="$(python3 -c 'import json,sys; print(json.dumps({"name":"gcp-mesh-coordinator","issuer":"https://accounts.google.com","subject":sys.argv[1],"audiences":["api://AzureADTokenExchange"],"description":"GCP mesh coordinator, keyless"}))' "$sub")"
  az ad app federated-credential create --id "$app_id" --parameters "$body" -o none 2>/dev/null &&
    echo "federated credential pins subject $sub" ||
    echo "federated credential exists; check: az ad app federated-credential list --id $app_id"
}

auth() {
  local app_id tenant
  app_id="$(az ad app list --display-name "$APP_REG" --query '[0].appId' -o tsv)"
  [[ -z "$app_id" ]] && { echo "no app registration; run: $0 fic" >&2; exit 1; }
  tenant="$(az account show --query tenantId -o tsv)"
  az containerapp auth microsoft update -n "$APP" -g "$RG" --client-id "$app_id" \
    --issuer "https://sts.windows.net/${tenant}/" --allowed-audiences "$app_id" --yes -o none
  # Return401: an A2A client given a redirect to a sign-in page sees HTML, not an auth error.
  az containerapp auth update -n "$APP" -g "$RG" --enabled true \
    --unauthenticated-client-action Return401 -o none
  echo "ingress requires an Entra token for audience $app_id"
}

env_block() {
  local app_id url tenant
  app_id="$(az ad app list --display-name "$APP_REG" --query '[0].appId' -o tsv)"
  url="$(app_url)"
  tenant="$(az account show --query tenantId -o tsv)"
  [[ -z "$app_id" || -z "$url" || -z "$tenant" ]] && { echo "unresolved value" >&2; exit 1; }
  cat > "$REPO/infra/mesh.azure.env" <<ENV
AZURE_A2A_ENDPOINT=${url}/
AZURE_A2A_AUTH=entra-fic
AZURE_A2A_TENANT_ID=${tenant}
AZURE_A2A_CLIENT_ID=${app_id}
ENV
  cat "$REPO/infra/mesh.azure.env"
}

verify() {
  local url; url="$(app_url)"
  echo "no token, agent card -> $(curl -s -o /dev/null -w '%{http_code}' -m 30 "$url/.well-known/agent-card.json") (expect 401)"
  echo "no token, /health    -> $(curl -s -o /dev/null -w '%{http_code}' -m 30 "$url/health") (expect 401)"
}

destroy() {
  az group delete -n "$RG" --yes -o none || true
  az cognitiveservices account purge -g "$RG" -n "$AI" -l "$LOC" -o none 2>/dev/null || true
  local app_id; app_id="$(az ad app list --display-name "$APP_REG" --query '[0].appId' -o tsv 2>/dev/null)"
  [[ -n "$app_id" ]] && az ad app delete --id "$app_id" -o none || true
}

case "${1:-}" in
  deploy|fic|auth|verify|destroy) "$1" ;;
  env) env_block ;;
  url) app_url ;;
  *) echo "usage: $0 {deploy|fic|auth|env|verify|url|destroy}" >&2; exit 2 ;;
esac
