# CLAUDE.md

Mesh sibling of `~/currency-claude-agui-a2ui1` (ADK + Gemini), `~/currency-strands-agui-a2ui1` (Strands + Nova) and `~/currency-maf-agui-a2ui1` (Agent Framework + Azure OpenAI), and of the comparison in `~/a2ui-three-clouds`. Here the three agents run at once, one per cloud, served over A2A, and an ADK + Gemini coordinator sends each question to one of them or to all three. A2UI 1.0.

## Running locally

Use the active `python3`; never create a virtualenv. Gemini key: `~/gemini.key`. AWS: `aws login`. Azure: `az login`.

| What | Command |
|---|---|
| GCP agent (ADK), A2A :10110 | `cd agents/gcp && GOOGLE_API_KEY=$(cat ~/gemini.key) PORT=10110 python3 main.py` |
| AWS agent (Strands), A2A :10120 | `cd agents/aws && PORT=10120 python3 main.py` |
| Azure agent (Agent Framework), A2A :10130 | `cd agents/azure && AZURE_OPENAI_ENDPOINT=https://<account>.cognitiveservices.azure.com/ PORT=10130 python3 main.py` |
| Coordinator, AG-UI :8110 | `GOOGLE_API_KEY=$(cat ~/gemini.key) python3 coordinator/main.py` |
| UI :3010 | `cd frontend-react && PORT=3010 AGENT_URL=http://127.0.0.1:8110/ npx next dev --webpack -p 3010` |
| One agent over A2A | `python3 tools/ask.py gcp=http://127.0.0.1:10110/ -- "How much is 250 USD in EUR?"` |
| Offline tests | `python3 -m pytest tests` |
| Render suite (stack up) | `UI_URL=http://localhost:3010 python3 tools/render_suite.py 10 LABEL evidence/OUT.jsonl` |
| Routing suite (stack up) | `UI_URL=http://localhost:3010 python3 tools/mesh_suite.py 10 LABEL evidence/OUT.jsonl` |

Sibling ports 3000-3002, 8008, 8080, 8090, 8095, 10000 may be in use. Stop processes by port (`fuser -k 10130/tcp`), never with `pkill -f`: the pattern matches the shell running it.

## Rules

- Code picks the cloud: the coordinator model names a job, `JOB_OWNER` in `coordinator/agent.py` maps it to a cloud. Check routing by the `job` the model sent, not only by which card rendered.
- Every agent is served by `mesh/server.py` and answers with A2UI DataParts (`application/a2ui+json`) from `mesh.sink`; each agent's UI tool calls `record(wire)` after its second validation. Keep the agents' `currency_agent/` packages otherwise as in their sibling repos.
- The Azure agent runs streamed: `A2uiRescueMiddleware` only rewrites streamed responses.
- The Strands agent holds conversation state, so `agents/aws/main.py` serialises requests and clears `agent.messages` per request.
- Surface ids are renamed per cloud in the coordinator so three answers can share one turn.
- Cross-cloud auth is `mesh/auth.py`, from `~/multicloud-adk-a2a-currency`: Google ID token, STS web identity + SigV4, Entra federated credential. Every peer is `none` locally.

## Git

Commit straight to `main` and push.
