"""Google Cloud leg: the ADK + Gemini currency agent, served over A2A. Owns rate cards.

    cd agents/gcp && PYTHONPATH=../.. PORT=10110 python3 main.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from a2a.types import AgentSkill
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from currency_agent.agent import root_agent
from mesh.server import build_app, build_card, public_url, serve

logging.basicConfig(format="[%(levelname)s] %(name)s: %(message)s", level=logging.INFO)

DEFAULT_PORT = 10110
APP = "currency_gcp"
PROVENANCE = {
    "cloud": "gcp",
    "framework": "Google ADK",
    "model": os.getenv("GENAI_MODEL", "gemini-3.8-flash"),
}

runner = Runner(agent=root_agent, app_name=APP, session_service=InMemorySessionService())


async def run(prompt: str) -> str:
    session = await runner.session_service.create_session(app_name=APP, user_id="mesh")
    text = ""
    async for event in runner.run_async(
        user_id="mesh",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
    ):
        if event.partial or not event.content or not event.content.parts:
            continue
        text += "".join(
            p.text for p in event.content.parts if p.text and not getattr(p, "thought", False)
        )
    return text


card = build_card(
    name="currency_agent_gcp",
    description="Currency agent on Google ADK and Gemini. Answers with A2UI 1.0.",
    url=public_url(DEFAULT_PORT),
    skill=AgentSkill(
        id="rate_card",
        name="Rate cards",
        description="Current exchange rates and conversions, as an A2UI rate card.",
        tags=["currency", "rate", "a2ui", "gcp"],
    ),
)
app = build_app(run, card, PROVENANCE)

if __name__ == "__main__":
    serve(app, DEFAULT_PORT)
