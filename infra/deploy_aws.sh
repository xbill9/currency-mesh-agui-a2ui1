#!/usr/bin/env bash
# AWS side of the mesh: the Strands agent on Amazon Bedrock AgentCore Runtime with
# protocol A2A, and the IAM role the GCP coordinator assumes with its Google ID
# token (STS AssumeRoleWithWebIdentity) to call it with SigV4.
#
#   ./infra/deploy_aws.sh deploy   # stage build/aws, agentcore deploy (CodeZip, ARM64 built by AgentCore)
#   ./infra/deploy_aws.sh role     # federated role: trust pins the coordinator SA's unique id
#   ./infra/deploy_aws.sh env      # writes infra/mesh.aws.env for the coordinator
#   ./infra/deploy_aws.sh verify   # unsigned calls must get 403
#   ./infra/deploy_aws.sh destroy
#
# Trust policy rules, all from the earlier three-cloud mesh: Principal.Federated
# is the literal "accounts.google.com" with no IAM OIDC provider; the audience
# condition is :oaud (the token's aud), not :aud; :sub is the numeric unique id.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGION="${AWS_REGION:-us-east-1}"
RUNTIME_NAME="${RUNTIME_NAME:-currency_mesh_aws}"
ROLE_FEDERATED="${ROLE_FEDERATED:-currency-mesh-a2ui-federated}"
AUDIENCE="${AWS_A2A_AUDIENCE:-sts.amazonaws.com}"
GCP_PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
COORD_SA="mesh-coordinator@${GCP_PROJECT}.iam.gserviceaccount.com"
export AWS_REGION="$REGION"

runtime_arn() {
  aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
    --query "agentRuntimes[?contains(agentRuntimeName, '${RUNTIME_NAME}')].agentRuntimeArn | [0]" \
    --output text
}

runtime_url() {
  local arn; arn="$(runtime_arn)"
  [[ -z "$arn" || "$arn" == "None" ]] && { echo "runtime ${RUNTIME_NAME} not deployed in ${REGION}" >&2; exit 1; }
  echo "https://bedrock-agentcore.${REGION}.amazonaws.com/runtimes/$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$arn")/invocations/"
}

stage() {
  # AgentCore's CodeZip build packages one directory: the agent, its MCP
  # server, the shared mesh package, and a pyproject.toml of its requirements.
  local out="$REPO/build/aws"
  rm -rf "$out" && mkdir -p "$out"
  cp -r "$REPO/agents/aws/main.py" "$REPO/agents/aws/mcp_server.py" "$REPO/agents/aws/currency_agent" "$out/"
  cp -r "$REPO/mesh" "$out/mesh"
  find "$out" -name __pycache__ -prune -exec rm -rf {} +
  python3 - "$REPO/agents/aws/requirements.txt" "$out/pyproject.toml" <<'PY'
import json, sys
reqs = [l.strip() for l in open(sys.argv[1]) if l.strip() and not l.lstrip().startswith("#")]
open(sys.argv[2], "w").write(
    '[project]\nname = "currency-mesh-aws"\nversion = "1.0.0"\nrequires-python = ">=3.13"\n'
    "dependencies = " + json.dumps(reqs, indent=4) + "\n"
)
PY
  echo "staged $out"
}

deploy() {
  stage
  local account; account="$(aws sts get-caller-identity --query Account --output text)"
  printf '[\n  {"name": "default", "account": "%s", "region": "%s"}\n]\n' "$account" "$REGION" \
    > "$REPO/agentcore/aws-targets.json"
  (cd "$REPO" && agentcore deploy)
  echo "runtime: $(runtime_arn)"
}

role() {
  local sub policy arn
  sub="$(gcloud iam service-accounts describe "$COORD_SA" --format='value(uniqueId)')"
  [[ -z "$sub" ]] && { echo "cannot read the unique id of $COORD_SA (run deploy_gcp.sh sa)" >&2; exit 1; }
  policy="$(sed -e "s/\${AUDIENCE}/${AUDIENCE}/" -e "s/\${COORDINATOR_SA_UNIQUE_ID}/${sub}/" \
    "$REPO/infra/aws-trust-policy.json")"
  if aws iam get-role --role-name "$ROLE_FEDERATED" >/dev/null 2>&1; then
    aws iam update-assume-role-policy --role-name "$ROLE_FEDERATED" --policy-document "$policy"
  else
    aws iam create-role --role-name "$ROLE_FEDERATED" \
      --description "Assumed by the GCP mesh coordinator via AssumeRoleWithWebIdentity" \
      --assume-role-policy-document "$policy" >/dev/null
  fi
  arn="$(runtime_arn)"
  [[ -z "$arn" || "$arn" == "None" ]] && { echo "deploy the runtime first" >&2; exit 1; }
  # Two actions: the agent-card fetch is GetAgentCard, separate from the call.
  aws iam put-role-policy --role-name "$ROLE_FEDERATED" --policy-name invoke-currency-mesh-aws \
    --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"bedrock-agentcore:InvokeAgentRuntime\",\"bedrock-agentcore:GetAgentCard\"],\"Resource\":[\"${arn}\",\"${arn}/*\"]}]}"
  echo "role ${ROLE_FEDERATED}: trust pins sub=${sub}, aud=${AUDIENCE}; invoke scoped to ${arn}"
}

env_block() {
  local url role_arn
  url="$(runtime_url)"
  role_arn="$(aws iam get-role --role-name "$ROLE_FEDERATED" --query Role.Arn --output text)"
  [[ -z "$url" || -z "$role_arn" || "$role_arn" == "None" ]] && { echo "unresolved value" >&2; exit 1; }
  cat > "$REPO/infra/mesh.aws.env" <<ENV
AWS_A2A_ENDPOINT=${url}
AWS_A2A_AUTH=aws-sigv4
AWS_A2A_ROLE_ARN=${role_arn}
AWS_A2A_REGION=${REGION}
AWS_A2A_AUDIENCE=${AUDIENCE}
AWS_A2A_SIGNING_SERVICE=bedrock-agentcore
ENV
  cat "$REPO/infra/mesh.aws.env"
}

verify() {
  local url; url="$(runtime_url)"
  echo "unsigned POST       -> $(curl -s -o /dev/null -w '%{http_code}' -X POST "$url") (expect 403)"
  echo "unsigned agent card -> $(curl -s -o /dev/null -w '%{http_code}' "${url}.well-known/agent-card.json") (expect 403)"
}

destroy() {
  aws iam delete-role-policy --role-name "$ROLE_FEDERATED" --policy-name invoke-currency-mesh-aws 2>/dev/null || true
  aws iam delete-role --role-name "$ROLE_FEDERATED" 2>/dev/null || true
  aws cloudformation delete-stack --region "$REGION" --stack-name AgentCore-currencymesh-default
}

aws sts get-caller-identity >/dev/null 2>&1 || { echo "AWS session expired: run aws login" >&2; exit 1; }
case "${1:-}" in
  deploy|stage|role|verify|destroy) "$1" ;;
  env) env_block ;;
  url) runtime_url ;;
  *) echo "usage: $0 {deploy|stage|role|env|verify|url|destroy}" >&2; exit 2 ;;
esac
