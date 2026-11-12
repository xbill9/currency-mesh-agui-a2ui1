"""Asks one cloud agent a question over A2A and returns its text and A2UI messages."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, TextPart
from a2ui.a2a import get_a2ui_messages

log = logging.getLogger("mesh.client")


@dataclass
class Answer:
    cloud: str
    text: str = ""
    a2ui: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    seconds: float = 0.0
    error: str | None = None


async def ask(
    cloud: str,
    endpoint: str,
    question: str,
    *,
    auth: httpx.Auth | None = None,
    card_path: str | None = None,
    timeout_s: float = 180.0,
) -> Answer:
    t0 = time.monotonic()
    answer = Answer(cloud=cloud)
    try:
        async with httpx.AsyncClient(auth=auth, timeout=timeout_s) as http:
            resolver = A2ACardResolver(http, endpoint, **({"agent_card_path": card_path} if card_path else {}))
            card = await resolver.get_agent_card()
            # The card's URL is the agent's own claim; the configured endpoint is
            # where this caller actually reached it.
            card.url = endpoint
            client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)
            request = Message(
                role=Role.user,
                message_id=uuid.uuid4().hex,
                parts=[Part(root=TextPart(text=question))],
            )
            async for event in client.send_message(request):
                message = event if isinstance(event, Message) else _task_message(event)
                if message is None:
                    continue
                answer.text += "".join(
                    p.root.text for p in message.parts if isinstance(p.root, TextPart)
                )
                answer.a2ui.extend(get_a2ui_messages(message))
                answer.metadata.update(message.metadata or {})
    except Exception as exc:  # noqa: BLE001 - one cloud failing must not sink the others
        log.exception("ask %s failed", cloud)
        answer.error = f"{type(exc).__name__}: {exc}"
    answer.seconds = round(time.monotonic() - t0, 2)
    return answer


def _task_message(event) -> Message | None:
    task, _update = event
    status = getattr(task, "status", None)
    return getattr(status, "message", None)
