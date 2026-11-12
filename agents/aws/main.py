"""AWS leg: the Strands + Amazon Nova currency agent, served over A2A. Owns history charts.

    cd agents/aws && PYTHONPATH=../.. PORT=10120 python3 main.py
On AgentCore Runtime (protocol A2A) it serves on port 9000 at the root path.
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from a2a.types import AgentSkill

from currency_agent.agent import DEFAULT_MODEL, build_agent, mcp_client
from mesh.server import build_app, build_card, public_url, serve

logging.basicConfig(format="[%(levelname)s] %(name)s: %(message)s", level=logging.INFO)

DEFAULT_PORT = 10120
PROVENANCE = {
    "cloud": "aws",
    "framework": "Strands Agents",
    "model": os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL),
}

agent = build_agent([mcp_client()])
# One Strands Agent holds its conversation in agent.messages, so requests take
# turns and each starts from an empty conversation.
_lock = asyncio.Lock()


async def run(prompt: str) -> str:
    async with _lock:
        agent.messages.clear()
        result = await agent.invoke_async(prompt)
        return str(result)


card = build_card(
    name="currency_agent_aws",
    description="Currency agent on Strands Agents and Amazon Nova. Answers with A2UI 1.0.",
    url=public_url(DEFAULT_PORT),
    skill=AgentSkill(
        id="history_chart",
        name="History charts",
        description="Exchange-rate trends over time, as an A2UI line chart.",
        tags=["currency", "history", "a2ui", "aws"],
    ),
)
app = build_app(run, card, PROVENANCE)

if __name__ == "__main__":
    serve(app, DEFAULT_PORT)
