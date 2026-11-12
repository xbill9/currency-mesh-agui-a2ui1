"""Hands the A2UI an agent's UI tool validated to the A2A executor that served the request.

Each agent's ``send_a2ui_json_to_client`` tool calls ``record(wire)`` after it
has compiled, expanded and validated a payload. The executor opens a
``capture()`` around the agent run and sends what was recorded as A2UI
DataParts. A ``ContextVar`` carries the list into every task and thread the
framework starts for the run, and keeps concurrent requests apart.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

_sink: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "a2ui_sink", default=None
)


def record(wire: list[dict]) -> None:
    """Called by the UI tool with the messages it validated; a no-op outside a capture."""
    sink = _sink.get()
    if sink is not None:
        sink.extend(wire)


@contextmanager
def capture() -> Iterator[list[dict]]:
    messages: list[dict] = []
    token = _sink.set(messages)
    try:
        yield messages
    finally:
        _sink.reset(token)
