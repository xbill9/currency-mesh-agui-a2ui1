---
title: "One Chat, Three Clouds: An A2UI 1.0 Agent Mesh Over A2A on Google Cloud, AWS and Azure"
published: false
description: "Three A2UI 1.0 currency agents, one per cloud, joined over A2A behind one AG-UI coordinator. Google ADK and Gemini, Strands and Amazon Nova, Microsoft Agent Framework and Azure OpenAI answer in the same chat, one at a time or all three at once."
tags: a2ui, a2a, multicloud, agents
cover_image: https://raw.githubusercontent.com/xbill9/currency-mesh-agui-a2ui1/main/devto-cover.d72a23ed.jpg
---

This article provides a step by step guide to a cross-cloud generative UI mesh. Three A2UI 1.0 currency agents run at once, one each on Google Cloud, AWS and Azure, and an AG-UI coordinator sends every chat question over A2A to one of them or to all three. Every answer comes back as A2UI cards and charts, labelled with the cloud, framework and model that built it.

https://github.com/xbill9/currency-mesh-agui-a2ui1

**The three agents joined the mesh with two added lines each.** Each agent is the one from its single-cloud repository. One shared A2A server runs all three frameworks, and each agent's UI tool hands its validated A2UI to that server with one `record(wire)` call. The coordinator model names a job and a table in code picks the cloud. In a ten-prompt routing suite run ten times through the chat UI, **100 of 100 turns reached the right clouds with the right job**, and every agent call that should return A2UI did.

Demo video: https://www.youtube.com/watch?v=PtLc5apk8AU

---

#### What Was Built?

| Role | Cloud | Framework | Model | Hosting |
| :--- | :--- | :--- | :--- | :--- |
| Rate cards | Google Cloud | Google ADK | `gemini-3.8-flash` | Cloud Run |
| History charts | AWS | Strands Agents | `us.amazon.nova-2-lite-v1:0` on Bedrock | AgentCore Runtime, protocol A2A |
| Comparisons | Azure | Microsoft Agent Framework | `gpt-5.4-mini` on Azure OpenAI | Container Apps |
| Coordinator | Google Cloud | Google ADK | `gemini-3.8-flash` | Cloud Run |
| Chat UI | Google Cloud | Next.js, CopilotKit, `@a2ui/react` | | Cloud Run |

A question travels in four hops:

1. The browser sends the question to the UI over AG-UI, and the UI forwards it to the coordinator.
2. The coordinator model calls one of two tools. `route_to_cloud(job, question)` names a job: `rate`, `history` or `comparison`. `ask_all_clouds(question)` sends the question to all three agents.
3. Each agent answers with one A2A message: its reply text as a TextPart, and every A2UI message its UI tool validated as a DataPart with MIME type `application/a2ui+json`. The message metadata names the cloud, framework and model.
4. The coordinator gives each surface a per-cloud id and returns the A2UI as its tool result. The UI renders one labelled block per cloud.

The three single-cloud agents this mesh is built from:

- Google Cloud: https://github.com/xbill9/currency-claude-agui-a2ui1
- AWS: https://github.com/xbill9/currency-strands-agui-a2ui1
- Azure: https://github.com/xbill9/currency-maf-agui-a2ui1

---

#### At This Point You Should Have…

- Python 3.14 and Node.js 24
- A Gemini API key, for the Google Cloud agent and the coordinator
- An AWS account with Amazon Nova 2 Lite enabled in Bedrock, signed in with `aws login`
- An Azure subscription with a `gpt-5.4-mini` deployment in Azure OpenAI, signed in with `az login`

The library versions, read from the machine that ran the tests (`evidence/versions.txt`):

| Component | Version |
| :--- | :--- |
| `a2a-sdk` | 0.3.26 |
| `a2ui-agent-sdk` / `a2ui-a2a` | 0.11.0 / 0.3.0 |
| `google-adk` / `strands-agents` / `agent-framework-core` | 2.14.1 / 1.64.0 / 1.25.0 |
| `@a2ui/react` / `@copilotkit/react-core` / `next` | 0.15.0 / 1.56.4 / 16.1.1 |

---

#### Step 1 — One A2A Server for Three Frameworks

`mesh/server.py` serves every agent. It takes one function from each, `run(prompt) -> reply text`, and wraps it in an a2a-sdk `AgentExecutor`:

```python
async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
    prompt = context.get_user_input()
    with capture() as wire:
        text = await self._run(prompt)
    parts = [Part(root=TextPart(text=text.strip()))] if text.strip() else []
    parts.extend(create_a2ui_parts(wire))
    message = new_agent_parts_message(parts, context_id=context.context_id, task_id=context.task_id)
    message.metadata = {**self._provenance, "a2ui_messages": len(wire)}
    await event_queue.enqueue_event(message)
```

`create_a2ui_parts` comes from `a2ui-a2a`, the A2UI SDK's A2A package, and turns each validated A2UI message into a DataPart. The agent card advertises the A2UI 1.0 extension with the two catalogs the agents use: the Basic catalog and the currency charts catalog.

Each agent's `main.py` is the `run` function plus its card. On Azure, `run` streams, because the agent's reply-text rescue middleware rewrites streamed responses only:

```python
async def run(prompt: str) -> str:
    text = ""
    async for update in agent.run(prompt, stream=True):
        text += update.text or ""
    return text
```

On AWS, one Strands `Agent` keeps its conversation in `agent.messages`, so requests take turns and each starts from an empty conversation:

```python
async def run(prompt: str) -> str:
    async with _lock:
        agent.messages.clear()
        result = await agent.invoke_async(prompt)
        return str(result)
```

---

#### Step 2 — Two Lines per Agent

The A2UI an agent sends is already validated inside its UI tool, `send_a2ui_json_to_client`: the tool compiles the model's A2UI, expands the server-side macros and validates the result against the catalogs. The mesh needs that validated list in the A2A response. `mesh/sink.py` carries it there with a `ContextVar`, so concurrent requests stay apart and every task the framework starts sees the same list:

```python
def record(wire: list[dict]) -> None:
    sink = _sink.get()
    if sink is not None:
        sink.extend(wire)
```

`tools/compare_siblings.py` diffs each agent's `currency_agent/` package against its single-cloud repository at git `HEAD`:

```shell
python3 tools/compare_siblings.py
```

```text
== aws: agents/aws/currency_agent vs currency-strands-agui-a2ui1@802cb1c
app/agent/currency_agent/a2ui_rescue.py: 122 lines, 0 changed
app/agent/currency_agent/agent.py: 165 lines, 2 changed
    +from mesh.sink import record
    +    record(wire)  # mesh: hand the validated A2UI to the A2A executor
app/agent/currency_agent/custom_catalog.json: 95 lines, 0 changed
app/agent/currency_agent/macros.py: 181 lines, 0 changed
total changed lines: 2
== azure: agents/azure/currency_agent vs currency-maf-agui-a2ui1@fd2268b
app/agent/currency_agent/a2ui_rescue.py: 122 lines, 0 changed
app/agent/currency_agent/agent.py: 204 lines, 2 changed
    +from mesh.sink import record
    +    record(wire)  # mesh: hand the validated A2UI to the A2A executor
app/agent/currency_agent/custom_catalog.json: 95 lines, 0 changed
app/agent/currency_agent/macros.py: 181 lines, 0 changed
total changed lines: 2
== gcp: agents/gcp/currency_agent vs currency-claude-agui-a2ui1@294caee
currency_agent/a2ui_rescue.py: 118 lines, 0 changed
currency_agent/agent.py: 176 lines, 65 changed
currency_agent/custom_catalog.json: 95 lines, 0 changed
currency_agent/macros.py: 181 lines, 0 changed
currency_agent/test_client.py: 154 lines, 154 changed (absent here)
total changed lines: 219
```

The AWS and Azure agents changed by the two `record` lines. The Google Cloud agent changed by 65 lines in `agent.py`: its single-cloud repository served A2A from inside that file with ADK's `to_a2a` and a streaming patch on the card builder, and reached its MCP server over HTTP. The mesh removes that server in favour of the shared one and starts the MCP server as a stdio child, as the AWS and Azure agents do. The catalog, the macros and the reply-text rescue are unchanged in all three.

---

#### Step 3 — Code Picks the Cloud

The coordinator is an ADK `LlmAgent` on `gemini-3.8-flash` with two tools. The model chooses a job; a dictionary chooses the cloud:

```python
JOB_OWNER = {"rate": "gcp", "history": "aws", "comparison": "azure"}

async def route_to_cloud(job: str, question: str, tool_context: ToolContext) -> dict:
    cloud = JOB_OWNER.get(job.strip().lower())
    if cloud is None:
        return {"error": f"unknown job {job!r}; use one of {sorted(JOB_OWNER)}"}
    return _result([await _ask(cloud, question)], tool_context, job)

async def ask_all_clouds(question: str, tool_context: ToolContext) -> dict:
    pairs = await asyncio.gather(*(_ask(c, question) for c in CLOUDS))
    return _result(list(pairs), tool_context, None)
```

Moving a job to another cloud is a one-word change in `JOB_OWNER`, with no prompt to retune. The model's instruction describes the three jobs in terms of the question: a rate or a conversion, a trend over time, several currencies against one.

When an agent returns A2UI, `_result` sets `skip_summarization`, so the cards end the turn. When an agent returns text only, the text goes back to the coordinator model, which relays it in a sentence or two.

---

#### Step 4 — Three Answers in One Turn

Each agent names its surface `main`. Three `main` surfaces in one turn would collide in the renderer, so the coordinator prefixes every surface id with the cloud and a short random tag:

```python
def _rename_surfaces(messages: list[dict], cloud: str) -> list[dict]:
    tag = f"{cloud}-{uuid.uuid4().hex[:6]}"
    out = []
    for m in messages:
        m = dict(m)
        for key, body in m.items():
            if isinstance(body, dict) and "surfaceId" in body:
                m[key] = {**body, "surfaceId": f"{tag}-{body['surfaceId']}"}
        out.append(m)
    return out
```

The tool result carries one `sources` entry per cloud, with its framework, model, seconds and A2UI. In the browser, `MeshSources.tsx` renders each entry under a label such as `AWS · Strands Agents · us.amazon.nova-2-lite-v1:0 · 2.0 s`, read from the agent's own A2A metadata.

---

#### Step 5 — Run It Locally

Five processes, each in its own terminal:

```shell
cd agents/gcp && GOOGLE_API_KEY=$(cat ~/gemini.key) PORT=10110 python3 main.py
cd agents/aws && PORT=10120 python3 main.py
cd agents/azure && AZURE_OPENAI_ENDPOINT=https://<account>.cognitiveservices.azure.com/ PORT=10130 python3 main.py
GOOGLE_API_KEY=$(cat ~/gemini.key) python3 coordinator/main.py
cd frontend-react && PORT=3010 AGENT_URL=http://127.0.0.1:8110/ npx next dev --webpack -p 3010
```

`tools/ask.py` sends one question to one agent over A2A, with no coordinator, and prints what came back:

```shell
python3 tools/ask.py azure=http://127.0.0.1:10130/ -- "Compare 1 USD in EUR, GBP, JPY and CAD"
```

```text
{"cloud": "azure", "seconds": 6.97, "metadata": {"cloud": "azure", "framework": "Microsoft Agent Framework", "model": "gpt-5.4-mini", "seconds": 6.89, "a2ui_messages": 1}, "text": "", "a2ui_messages": 1, "components": ["Text", "Text", "Text", "Text", "Text", "BarChart", "Text", "Column", "Card"], "error": null}
```

```shell
python3 tools/ask.py aws=http://127.0.0.1:10120/ -- "Show me the USD to JPY trend over the last 90 days"
```

```text
{"cloud": "aws", "seconds": 2.09, "metadata": {"cloud": "aws", "framework": "Strands Agents", "model": "us.amazon.nova-2-lite-v1:0", "seconds": 2.03, "a2ui_messages": 1}, "text": "", "a2ui_messages": 1, "components": ["Text", "LineChart", "Text", "Column", "Card"], "error": null}
```

Open http://localhost:3010 and ask for a rate, a trend, a comparison, or ask all three clouds.

---

#### Step 6 — The Routing Suite

`tools/mesh_suite.py` sends ten prompts through the UI's CopilotKit endpoint, ten times each, and reads the AG-UI event stream. A prompt passes when the coordinator called the expected tool with the expected job, exactly the expected clouds answered, each of them answered with A2UI, and no raw `<a2ui` text reached the chat. Two prompts accept text: the weather question, which the coordinator declines, and an unknown currency code.

```shell
UI_URL=http://localhost:3010 python3 tools/mesh_suite.py 10 local-2026-11-21 evidence/mesh-suite-local-2026-11-21.jsonl
python3 tools/summarize_suite.py evidence/mesh-suite-local-2026-11-21.jsonl
```

```text
local-2026-11-21: 100 of 100 passed
```

| Prompt | Tool, job sent | Clouds | Passed | Turn median s |
| :--- | :--- | :--- | :--- | :--- |
| How much is 250 USD in EUR? | route_to_cloud rate x10 | gcp | 10 of 10 | 10.1 |
| What's a thousand euros in dollars? | route_to_cloud rate x10 | gcp | 10 of 10 | 9.9 |
| Show me the USD to JPY trend over the last 90 days | route_to_cloud history x10 | aws | 10 of 10 | 4.1 |
| Show me EUR to USD for the past 6 months and the current rate | route_to_cloud history x10 | aws | 10 of 10 | 5.0 |
| Compare the euro, pound and Swiss franc against the dollar in a bar chart | route_to_cloud comparison x10 | azure | 10 of 10 | 5.2 |
| Compare 1 USD in EUR, GBP, JPY and CAD | route_to_cloud comparison x10 | azure | 10 of 10 | 4.7 |
| Ask all three clouds: how much is 100 USD in EUR? | ask_all_clouds x10 | aws+azure+gcp | 10 of 10 | 10.2 |
| Compare the clouds: show me the USD to JPY trend over the last 90 days | ask_all_clouds x10 | aws+azure+gcp | 10 of 10 | 10.6 |
| What's the weather in Paris? | none x10 | - | 10 of 10 | 2.4 |
| Convert 100 USD to XYZ | route_to_cloud rate x10 | gcp | 10 of 10 | 30.9 |

Each agent call inside those turns, as timed by the agent's A2A server:

| Cloud | Model | Calls | With A2UI | Agent median s | Agent max s |
| :--- | :--- | :--- | :--- | :--- | :--- |
| aws | us.amazon.nova-2-lite-v1:0 | 40 | 40 | 0.9 | 1.9 |
| azure | gpt-5.4-mini | 40 | 40 | 1.6 | 2.0 |
| gcp | gemini-3.8-flash | 50 | 48 | 7.6 | 48.2 |

The coordinator sent the expected job in all 100 turns: `rate` 30 times, `history` 20, `comparison` 20, `ask_all_clouds` 20 times, and no tool for the weather question.

All 80 AWS and Azure calls returned A2UI. The Google Cloud agent returned A2UI in 48 of 50; the other two were the unknown currency code `XYZ`, where it answered in text, which the coordinator relayed. The `XYZ` prompt rendered an error card in the other 8 runs and is the slowest prompt in the suite, a median of 27.3 s in the Google Cloud agent. Without it, the Google Cloud agent's median is 7.4 s over 40 calls.

In the 20 ask-all turns, the three calls run in parallel and the Google Cloud agent was the slowest of the three every time. Those turns took a median of 10.2 and 10.6 s, the same as a rate question routed to Google Cloud alone.

---

#### Step 7 — Cross-Cloud Calls With No Stored Secret

Locally every peer is plain HTTP. Deployed, `mesh/auth.py` signs each leg from the coordinator's own Google identity on Cloud Run, so no cloud holds a key for another:

| Leg | Credential | Enforced by |
| :--- | :--- | :--- |
| UI → coordinator | Google ID token from the metadata server | Cloud Run IAM |
| coordinator → Google Cloud agent | Google ID token | Cloud Run IAM, `roles/run.invoker` |
| coordinator → AWS agent | STS `AssumeRoleWithWebIdentity`, then SigV4 | IAM role that trusts the coordinator's service account id |
| coordinator → Azure agent | Entra federated credential exchange | Container Apps authentication, 401 without a token |

Three scripts deploy it, service accounts first, because AWS and Azure trust the coordinator's identity:

```shell
./infra/deploy_gcp.sh sa
./infra/deploy_gcp.sh agent
./infra/deploy_aws.sh deploy && ./infra/deploy_aws.sh role && ./infra/deploy_aws.sh env
./infra/deploy_azure.sh deploy && ./infra/deploy_azure.sh fic && ./infra/deploy_azure.sh auth && ./infra/deploy_azure.sh env
./infra/deploy_gcp.sh coordinator
./infra/deploy_gcp.sh ui
```

`deploy_aws.sh` serves the Strands agent on AgentCore Runtime with protocol A2A, on port 9000 at the root path. `deploy_azure.sh verify` checks that an unauthenticated call to the Azure agent gets a 401. Each script tears its side down with `destroy`.

---

#### 🔎 Tip: Check Routing by the Job the Model Sent

A card on screen tells you which agent answered, but a wrong job can still land on a plausible card: a trend question sent as `rate` gets a rate card. The suite reads the `job` argument from the coordinator's tool call in the AG-UI stream and compares it with the expected job, then checks which clouds answered.

---

#### 🔎 Tip: Carry Provenance in the A2A Message

The coordinator labels each answer from the A2A message metadata the agent sent: cloud, framework, model and seconds. The label in the UI is the agent's own claim about itself, read at the time of the answer, so a redeployed agent on a new model shows the new model with no change to the coordinator or the UI.

---

#### 🔎 Tip: Serialise an Agent That Holds Conversation State

A Strands `Agent` keeps its conversation in `agent.messages`. Behind an A2A server that takes concurrent requests, two questions would share one conversation. A lock and `agent.messages.clear()` per request make each A2A call a single, separate turn. An `ask_all_clouds` call sends one request per agent, so the lock costs nothing there.

---

#### Compare and Contrast

| | Google Cloud | AWS | Azure |
| :--- | :--- | :--- | :--- |
| Job | rate | history | comparison |
| Framework | Google ADK | Strands Agents | Microsoft Agent Framework |
| Model | `gemini-3.8-flash` | `us.amazon.nova-2-lite-v1:0` | `gpt-5.4-mini` |
| Changed lines against its single-cloud repo | 65 in `agent.py` | 2 | 2 |
| How `run()` calls the agent | ADK `Runner`, a new session per request | `invoke_async`, one request at a time | streamed `agent.run` |
| Calls with A2UI in the suite | 48 of 50 (2 text, allowed) 🥉 | 40 of 40 🥇 | 40 of 40 🥇 |
| Agent median seconds in the suite | 7.6 🥉 | 0.9 🥇 | 1.6 🥈 |
| Deployed on | Cloud Run | AgentCore Runtime, protocol A2A | Container Apps behind Entra auth |
| Credential from the coordinator | Google ID token | STS web identity, then SigV4 | Entra federated credential |

---

#### So, Which One?

Route by job when each cloud owns a different kind of answer. The coordinator makes one model call to pick the job, one agent answers, and the turn costs that agent's time plus the coordinator's.

Ask all three when the point is the comparison: the same question, three frameworks and three models, side by side in one turn. The three calls run in parallel, so the turn waits for the slowest agent.

Keep the job-to-cloud table in code either way. The model picks from three words it can be checked on, and the cloud behind each word is a deployment decision.

---

#### Summary

The goal of this article was to join three A2UI 1.0 agents on three clouds into one chat. The key to the solution was a shared A2A server that sends each agent's validated A2UI as DataParts, and a coordinator that names a job while code picks the cloud. The results were:

- 🟢 100 of 100 suite turns reached the right clouds with the job the question called for
- 🟢 The AWS and Azure agents joined the mesh with two added lines each; their catalog, macros and reply-text rescue are unchanged
- 🟢 One A2A server, `mesh/server.py`, serves ADK, Strands and Agent Framework agents and sends their A2UI as `application/a2ui+json` DataParts
- 🟢 Three answers share one turn once the coordinator gives each surface a per-cloud id
- 🟢 All 80 AWS and Azure calls returned A2UI, at medians of 0.9 s and 1.6 s per call
- ⚠️ The Google Cloud agent is the slowest leg, a median of 7.6 s, and sets the time of every ask-all turn
- ⚠️ An unknown currency code took a median of 27.3 s on Google Cloud and answered in text in 2 of 10 runs
- ❌ The Google Cloud agent needed 65 changed lines, because its single-cloud repository served A2A from inside `agent.py`

Scope: one run on 2026-11-21, all five processes on one Linux machine, ten runs per prompt. The agents called `gemini-3.8-flash` through the Gemini API, `us.amazon.nova-2-lite-v1:0` on Bedrock in us-east-1 and `gpt-5.4-mini` on Azure OpenAI in eastus2. Every peer was plain HTTP on the same machine, so the suite measures routing and rendering, and the timings exclude cross-cloud network and authentication. The deployed legs and their credentials in Step 7 come from the repository's deploy scripts and were not part of this run. Seconds are wall-clock times for one request at a time, with three different models, and describe the three deployments as built.

The strategy for joining generative UI agents across Google Cloud, AWS and Azure was validated with an incremental step by step approach.

---

#### References

- This mesh, its tests and evidence: https://github.com/xbill9/currency-mesh-agui-a2ui1
- Google Cloud agent (ADK, Gemini): https://github.com/xbill9/currency-claude-agui-a2ui1
- AWS agent (Strands, Nova): https://github.com/xbill9/currency-strands-agui-a2ui1
- Azure agent (Agent Framework, Azure OpenAI): https://github.com/xbill9/currency-maf-agui-a2ui1
- Cross-cloud auth adapters: https://github.com/xbill9/multicloud-adk-a2a-currency
- What Changes With the A2UI 1.0 Release: https://dev.to/gde/what-changes-with-the-a2ui-10-release-31eo
- A2UI 1.0 on AWS: https://dev.to/aws-builders/a2ui-10-on-aws-a-strands-currency-agent-with-amazon-nova-agentcore-runtime-and-ecs-express-mode-2pgl
- A2UI 1.0 on Azure: https://dev.to/xbill/a2ui-10-on-azure-a-microsoft-agent-framework-currency-agent-with-azure-openai-and-container-apps-1lgj
- Strands to Strands over A2A on Bedrock AgentCore: https://dev.to/aws-builders/strands-to-strands-over-a2a-on-bedrock-agentcore-with-iam-as-the-only-credential-19hp
- A2UI v1.0 specification: https://a2ui.org/specification/v1.0-a2ui/
- A2A protocol: https://a2a-protocol.org
- AG-UI: https://docs.ag-ui.com
- CopilotKit: https://github.com/CopilotKit/CopilotKit
- Google Agent Development Kit: https://github.com/google/adk-python
- Strands Agents: https://strandsagents.com
- Microsoft Agent Framework: https://github.com/microsoft/agent-framework
- Frankfurter API: https://www.frankfurter.dev
