"""Azure leg: the Agent Framework + Azure OpenAI currency agent, served over A2A. Owns comparisons.

    cd agents/azure && PYTHONPATH=../.. AZURE_OPENAI_ENDPOINT=... PORT=10130 python3 main.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from a2a.types import AgentSkill

from currency_agent.agent import DEFAULT_MODEL, build_agent, mcp_tool
from mesh.server import build_app, build_card, public_url, serve

logging.basicConfig(format="[%(levelname)s] %(name)s: %(message)s", level=logging.INFO)

DEFAULT_PORT = 10130
PROVENANCE = {
    "cloud": "azure",
    "framework": "Microsoft Agent Framework",
    "model": os.getenv("AZURE_OPENAI_DEPLOYMENT", DEFAULT_MODEL),
}

agent = build_agent([mcp_tool()])


async def run(prompt: str) -> str:
    # Streamed, as the AG-UI endpoint runs it: A2uiRescueMiddleware rewrites
    # streamed responses only, so A2UI written as reply text needs this path.
    text = ""
    async for update in agent.run(prompt, stream=True):
        text += update.text or ""
    return text


card = build_card(
    name="currency_agent_azure",
    description="Currency agent on Microsoft Agent Framework and Azure OpenAI. Answers with A2UI 1.0.",
    url=public_url(DEFAULT_PORT),
    skill=AgentSkill(
        id="comparison",
        name="Comparisons",
        description="Several currencies against one, as an A2UI rate list and bar chart.",
        tags=["currency", "comparison", "a2ui", "azure"],
    ),
)
app = build_app(run, card, PROVENANCE)

if __name__ == "__main__":
    serve(app, DEFAULT_PORT)
