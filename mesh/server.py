"""One A2A server for all three cloud agents (a2a-sdk 0.3).

Each agent supplies ``run(prompt) -> reply text``. The executor runs it inside
``sink.capture()``, then answers with one A2A message: the reply text as a
TextPart, and every A2UI message the agent's UI tool validated as an A2UI
DataPart (``application/a2ui+json``). The message metadata names the cloud,
framework and model, so the coordinator reads provenance from the agent itself.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Awaitable, Callable

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, Part, TextPart
from a2a.utils import new_agent_parts_message, new_agent_text_message
from a2ui.a2a import create_a2ui_parts, get_a2ui_agent_extension
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from mesh.sink import capture

log = logging.getLogger("mesh.server")

Runner = Callable[[str], Awaitable[str]]

CATALOG_IDS = [
    "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json",
    "https://a2ui.org/catalog/currency-charts/v1/catalog.json",
]


class A2uiExecutor(AgentExecutor):
    def __init__(self, run: Runner, provenance: dict[str, str]) -> None:
        self._run = run
        self._provenance = provenance

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        prompt = context.get_user_input()
        t0 = time.monotonic()
        with capture() as wire:
            try:
                text = await self._run(prompt)
            except Exception as exc:  # noqa: BLE001 - the caller gets the error as text
                log.exception("agent run failed")
                text = f"The {self._provenance['cloud']} agent failed: {type(exc).__name__}: {exc}"
        parts: list[Part] = []
        if text and text.strip():
            parts.append(Part(root=TextPart(text=text.strip())))
        parts.extend(create_a2ui_parts(wire))
        if not parts:
            parts.append(Part(root=TextPart(text="")))
        message = new_agent_parts_message(
            parts, context_id=context.context_id, task_id=context.task_id
        )
        message.metadata = {
            **self._provenance,
            "seconds": round(time.monotonic() - t0, 2),
            "a2ui_messages": len(wire),
        }
        log.info("answered %r: %d A2UI message(s)", prompt[:60], len(wire))
        await event_queue.enqueue_event(message)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(new_agent_text_message("not cancellable"))


def build_card(*, name: str, description: str, url: str, skill: AgentSkill) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        url=url,  # configuration, never the bind address
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "application/a2ui+json"],
        capabilities=AgentCapabilities(
            streaming=False,
            extensions=[get_a2ui_agent_extension("1.0", supported_catalog_ids=CATALOG_IDS)],
        ),
        skills=[skill],
    )


def build_app(run: Runner, card: AgentCard, provenance: dict[str, str]) -> Starlette:
    handler = DefaultRequestHandler(
        agent_executor=A2uiExecutor(run, provenance), task_store=InMemoryTaskStore()
    )
    app = A2AStarletteApplication(agent_card=card, http_handler=handler).build()

    async def health(request):
        return JSONResponse({"status": "ok", **provenance})

    async def ping(request):
        # AgentCore Runtime's health contract.
        return JSONResponse({"status": "Healthy"})

    app.router.routes.append(Route("/health", health, methods=["GET"]))
    app.router.routes.append(Route("/ping", ping, methods=["GET"]))
    return app


def serve(app: Starlette, default_port: int) -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", str(default_port))),
    )


def public_url(default_port: int) -> str:
    return os.getenv("PUBLIC_URL", f"http://127.0.0.1:{os.getenv('PORT', default_port)}/")
