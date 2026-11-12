"""The mesh coordinator: an ADK + Gemini agent that sends each question to a cloud agent over A2A.

Two tools. ``route_to_cloud(job, question)`` sends a single-answer question to
the cloud that owns that job, from a fixed table in code: the model names the
job, the table names the cloud. ``ask_all_clouds(question)`` sends one question
to all three clouds at once, for prompts that ask to compare the clouds.

Each tool returns the A2UI the remote agents validated, under
``validated_a2ui_json`` like every sibling's UI tool, plus one ``sources`` entry
per cloud with its provenance, so the UI can label each surface with the cloud,
framework and model that built it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.tools import ToolContext
from google.genai import types as genai_types

from mesh.auth import auth_mode, credentials_for
from mesh.client import Answer, ask

log = logging.getLogger("coordinator")

CLOUDS = ("gcp", "aws", "azure")
#: Which cloud owns which job. Code decides the cloud; the model only names the job.
JOB_OWNER = {"rate": "gcp", "history": "aws", "comparison": "azure"}
LOCAL_DEFAULTS = {
    "gcp": "http://127.0.0.1:10110/",
    "aws": "http://127.0.0.1:10120/",
    "azure": "http://127.0.0.1:10130/",
}


def endpoint(cloud: str) -> str:
    return os.getenv(f"{cloud.upper()}_A2A_ENDPOINT", LOCAL_DEFAULTS[cloud])


def card_path(cloud: str) -> str | None:
    return os.getenv(f"{cloud.upper()}_A2A_CARD_PATH") or None


async def _ask(cloud: str, question: str) -> tuple[Answer, str]:
    url = endpoint(cloud)
    auth = credentials_for(cloud, url)
    answer = await ask(cloud, url, question, auth=auth, card_path=card_path(cloud))
    return answer, auth_mode(auth)


def _rename_surfaces(messages: list[dict], cloud: str) -> list[dict]:
    """Give every surface a mesh-unique id, so three clouds' "main" surfaces can share one turn."""
    tag = f"{cloud}-{uuid.uuid4().hex[:6]}"
    out = []
    for m in messages:
        m = dict(m)
        for key, body in m.items():
            if isinstance(body, dict) and "surfaceId" in body:
                m[key] = {**body, "surfaceId": f"{tag}-{body['surfaceId']}"}
        out.append(m)
    return out


def _result(pairs: list[tuple[Answer, str]], tool_context: ToolContext, job: str | None) -> dict:
    sources, wire = [], []
    for answer, mode in pairs:
        messages = _rename_surfaces(answer.a2ui, answer.cloud)
        wire.extend(messages)
        sources.append(
            {
                "cloud": answer.cloud,
                "framework": answer.metadata.get("framework"),
                "model": answer.metadata.get("model"),
                "seconds": answer.seconds,
                "auth": mode,
                "text": answer.text,
                "error": answer.error,
                "validated_a2ui_json": messages,
            }
        )
    log.info(
        "job=%s answered by %s",
        job or "all",
        [(s["cloud"], len(s["validated_a2ui_json"]), s["error"]) for s in sources],
    )
    if wire:
        # The cards are the answer: end the turn, as the siblings' UI tools do.
        # A text-only answer goes back to the model to relay.
        tool_context.actions.skip_summarization = True
    return {"job": job or "all", "validated_a2ui_json": wire, "sources": sources}


async def route_to_cloud(job: str, question: str, tool_context: ToolContext) -> dict:
    """Send a currency question to the one cloud agent that owns its job, and show its answer.

    Args:
        job: "rate" for a current rate or a conversion, "history" for a trend or a
            rate history over time, "comparison" for several currencies against one.
        question: The user's question, word for word.
    """
    cloud = JOB_OWNER.get(job.strip().lower())
    if cloud is None:
        return {"error": f"unknown job {job!r}; use one of {sorted(JOB_OWNER)}"}
    return _result([await _ask(cloud, question)], tool_context, job)


async def ask_all_clouds(question: str, tool_context: ToolContext) -> dict:
    """Send one currency question to the agents on Google Cloud, AWS and Azure at once, and show all three answers.

    Args:
        question: The user's question, word for word, without the request to compare clouds.
    """
    pairs = await asyncio.gather(*(_ask(c, question) for c in CLOUDS))
    return _result(list(pairs), tool_context, None)


INSTRUCTION = """You coordinate three currency agents, one on each cloud: Google Cloud, AWS and Azure.
Every agent answers with rich UI, so you never write rates or UI yourself.

For a currency question, call exactly one tool, once:
- ask_all_clouds when the user asks to compare the clouds, to ask every cloud or all three agents,
  or to see how Google Cloud, AWS and Azure answer. Pass the currency question without that request.
- route_to_cloud otherwise. Choose the job from the question: "rate" for a current rate or a
  conversion (also when the user asks for a rate card or A2UI block), "history" for a trend or
  rate history over time (also when it asks for the current rate as well), "comparison" for
  several currencies against one. Pass the user's question word for word.

If a tool returns only text, give that text to the user in one or two sentences.
If the user asks about anything other than currency, say politely that you can only help with
currency questions, and call no tool."""

root_agent = LlmAgent(
    model=Gemini(
        model=os.getenv("COORDINATOR_MODEL", "gemini-3.8-flash"),
        retry_options=genai_types.HttpRetryOptions(
            attempts=5, initial_delay=1, max_delay=8,
            http_status_codes=[408, 429, 500, 502, 503, 504],
        ),
    ),
    name="mesh_coordinator",
    description="Routes currency questions to agents on Google Cloud, AWS and Azure over A2A.",
    instruction=INSTRUCTION,
    tools=[route_to_cloud, ask_all_clouds],
)
