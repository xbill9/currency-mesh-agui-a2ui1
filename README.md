# A2UI currency mesh across Google Cloud, AWS and Azure

The A2UI 1.0 currency agent, run as three agents at once, one per cloud, joined over A2A. One chat UI talks to a coordinator; the coordinator sends each question to the cloud that owns that job, or to all three clouds when you ask it to compare them. Every answer comes back as A2UI cards and charts, labelled with the cloud, framework and model that built them.

| Cloud | Agent | Model | Owns | Hosting |
| :--- | :--- | :--- | :--- | :--- |
| Google Cloud | Google ADK | `gemini-3.8-flash` (Vertex AI) | rate cards | Cloud Run |
| AWS | Strands Agents | `us.amazon.nova-2-lite-v1:0` (Bedrock) | history charts | AgentCore Runtime, protocol A2A |
| Azure | Microsoft Agent Framework | `gpt-5.4-mini` (Azure OpenAI) | comparisons | Container Apps |
| Google Cloud | coordinator: Google ADK | `gemini-3.8-flash` | routing | Cloud Run |
| Google Cloud | UI: Next.js, CopilotKit, `@a2ui/react` | | | Cloud Run |

Each agent is the one from its single-cloud sibling repository, unchanged apart from one line that hands its validated A2UI to the A2A server:

- https://github.com/xbill9/currency-claude-agui-a2ui1 (ADK, Gemini)
- https://github.com/xbill9/currency-strands-agui-a2ui1 (Strands, Nova)
- https://github.com/xbill9/currency-maf-agui-a2ui1 (Agent Framework, Azure OpenAI)

## How a question travels

1. The browser sends the question to the UI over AG-UI; the UI forwards it to the coordinator with a Google ID token.
2. The coordinator model picks a tool. `route_to_cloud(job, question)` names a job (`rate`, `history` or `comparison`); a table in code maps the job to its cloud. `ask_all_clouds(question)` sends the question to all three.
3. Each cloud agent is served by `mesh/server.py` (a2a-sdk). It runs the agent, and answers with one A2A message: reply text as a TextPart, and every A2UI message its UI tool validated as an A2UI DataPart (`application/a2ui+json`), with the cloud, framework and model in the message metadata.
4. The coordinator renames each surface id per cloud, so three answers can share one turn, and returns them as the tool result. The UI renders one labelled block per cloud.

## Cross-cloud calls, with no stored secret

`mesh/auth.py` comes from https://github.com/xbill9/multicloud-adk-a2a-currency. The coordinator runs on Cloud Run and starts every leg from its own Google ID token:

| Leg | Credential | Enforced by |
| :--- | :--- | :--- |
| coordinator → GCP agent | Google ID token | Cloud Run IAM, `roles/run.invoker` |
| coordinator → AWS agent | STS AssumeRoleWithWebIdentity, then SigV4 | IAM role trusting the coordinator's service account id |
| coordinator → Azure agent | Entra federated credential exchange | Container Apps authentication, 401 without a token |
| UI → coordinator | Google ID token from the metadata server | Cloud Run IAM |

## Run it locally

See `CLAUDE.md` for every command. Short version: start the three agents on 10110, 10120 and 10130, the coordinator on 8110 and the UI on 3010, then open http://localhost:3010 and ask:

- How much is 250 USD in EUR? (Google Cloud)
- Show me the USD to JPY trend over the last 90 days (AWS)
- Compare 1 USD in EUR, GBP, JPY and CAD (Azure)
- Ask all three clouds: how much is 100 USD in EUR? (all three)

## Deploy

```shell
./infra/deploy_gcp.sh sa            # service accounts first: AWS and Azure trust the coordinator's
./infra/deploy_gcp.sh agent
./infra/deploy_aws.sh deploy && ./infra/deploy_aws.sh role && ./infra/deploy_aws.sh env
./infra/deploy_azure.sh deploy && ./infra/deploy_azure.sh fic && ./infra/deploy_azure.sh auth && ./infra/deploy_azure.sh env
./infra/deploy_gcp.sh coordinator
./infra/deploy_gcp.sh ui
```

Tear down with `destroy` on each script.

## Tests

```shell
python3 -m pytest tests                                                     # offline
UI_URL=http://localhost:3010 python3 tools/render_suite.py 10 LABEL out.jsonl   # every reply renders
UI_URL=http://localhost:3010 python3 tools/mesh_suite.py 10 LABEL out.jsonl     # every question reaches the right clouds
```
