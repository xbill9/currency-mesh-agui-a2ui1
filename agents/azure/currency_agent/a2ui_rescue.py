"""Turns an A2UI block that the model writes as reply text into the UI tool call.

The model is told to pass A2UI to the ``send_a2ui_json_to_client`` tool. When it
writes the ``<a2ui>`` block into its reply instead, this chat middleware

* holds back streamed text from the point ``<a2ui`` starts, so the raw block
  never reaches the chat, and
* ends the response with one function call per A2UI block, so Agent Framework's
  function-invocation loop runs the tool, which compiles, expands and validates
  it like any other A2UI.

Chat middleware runs inside the function-invocation loop, once per model call,
so the rewritten response is what the loop sees.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from agent_framework import (
    ChatContext,
    ChatMiddleware,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    ResponseStream,
)

TOOL_NAME = "send_a2ui_json_to_client"
PAYLOAD_ARG = "a2ui_payload"
MARKER = "<a2ui"
CLOSE = "</a2ui>"

logger = logging.getLogger(__name__)
_BLOCK = re.compile(r"<a2ui>.*?(?:</a2ui>|\Z)", re.DOTALL)


def _held_back(text: str) -> int:
    """Length of the tail of ``text`` that could be the start of ``<a2ui``."""
    for n in range(min(len(MARKER) - 1, len(text)), 0, -1):
        if MARKER.startswith(text[-n:]):
            return n
    return 0


def function_call(block: str) -> Content:
    """One call of the UI tool carrying ``block``."""
    payload = block if block.rstrip().endswith(CLOSE) else block.rstrip() + "\n" + CLOSE
    return Content.from_function_call(
        call_id=f"call_a2ui_{uuid.uuid4().hex[:20]}",
        name=TOOL_NAME,
        arguments=json.dumps({PAYLOAD_ARG: payload}),
    )


async def rescue_updates(
    updates: AsyncIterator[ChatResponseUpdate],
) -> AsyncIterator[ChatResponseUpdate]:
    """Pass updates through, rewriting reply-text A2UI into UI tool calls."""
    text = ""  # all assistant text seen so far
    sent = 0  # how much of ``text`` has been passed on
    holding = False  # ``<a2ui`` seen: nothing more is passed on
    last: ChatResponseUpdate | None = None
    async for update in updates:
        last = update
        kept = []
        for content in update.contents or []:
            if content.type != "text":
                kept.append(content)
                continue
            text += content.text or ""
            if not holding and MARKER in text[sent:]:
                holding = True
                cut = text.index(MARKER, sent)
            elif holding:
                continue
            else:
                cut = len(text) - _held_back(text)
            if cut > sent:
                kept.append(Content.from_text(text[sent:cut]))
                sent = cut
        if kept or not update.contents:
            update.contents = kept
            yield update
    blocks = _BLOCK.findall(text[sent:]) if holding else []
    if not holding and sent < len(text):
        yield ChatResponseUpdate(
            role="assistant", contents=[Content.from_text(text[sent:])]
        )
    if blocks:
        logger.info(
            "A2UI written as reply text: sent %d block(s) through %s",
            len(blocks),
            TOOL_NAME,
        )
        yield ChatResponseUpdate(
            role="assistant",
            contents=[function_call(b) for b in blocks],
            finish_reason="tool_calls",
            response_id=last.response_id if last else None,
            message_id=last.message_id if last else None,
        )


class A2uiRescueMiddleware(ChatMiddleware):
    """Chat middleware whose responses never carry a raw ``<a2ui>`` block."""

    async def process(
        self, context: ChatContext, call_next: Callable[[], Awaitable[None]]
    ) -> None:
        await call_next()
        if not context.stream or context.result is None:
            return
        inner = context.result
        context.result = ResponseStream(
            rescue_updates(inner.__aiter__()),
            finalizer=ChatResponse.from_updates,
        )
