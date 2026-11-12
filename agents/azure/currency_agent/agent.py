"""Currency agent on Microsoft Agent Framework and an Azure OpenAI model, answering in A2UI 1.0.

The A2UI pipeline is the one the ADK and Strands builds use: the model writes
A2UI Express, the ``send_a2ui_json_to_client`` tool compiles it, validates it
against the inference catalogs (Basic 1.0 + charts + the macro sidecar), runs
the server-side macros, and validates the expanded messages again against the
catalogs the renderer implements.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Annotated

from a2ui.core.basic_catalog import BasicCatalog
from a2ui.core.schema import AgentToRendererMessage
from a2ui.inference_formats import to_message_dicts
from a2ui.parser import RawA2uiPart
from a2ui.processor import A2uiRequestProcessor
from a2ui.transformers.macros import MacroExpander
from a2ui.utils import validate_payload
from agent_framework import (
    Agent,
    FunctionInvocationContext,
    FunctionMiddleware,
    MCPStdioTool,
    MiddlewareTermination,
    tool,
)
from agent_framework.openai import OpenAIChatCompletionClient
from azure.identity.aio import DefaultAzureCredential
from pydantic import Field, TypeAdapter

from currency_agent.a2ui_rescue import A2uiRescueMiddleware
from currency_agent.macros import CHARTS_CATALOG, MACROS
from mesh.sink import record

logger = logging.getLogger(__name__)

TOOL_NAME = "send_a2ui_json_to_client"
VALIDATED_KEY = "validated_a2ui_json"
ERROR_KEY = "error"
DEFAULT_MODEL = "gpt-5.4-mini"

# Transport catalogs: what the renderer implements (Basic 1.0 + currency charts).
BASE_CATALOGS = [BasicCatalog("1.0"), CHARTS_CATALOG]
macro_expander = MacroExpander(MACROS, on_error="raise")
INFERENCE_CATALOGS = macro_expander.transform_catalogs(BASE_CATALOGS)
# A2uiRequestProcessor uses the A2UI Express inference format by default.
a2ui_processor = A2uiRequestProcessor(catalogs=INFERENCE_CATALOGS)
_message_adapter: TypeAdapter[AgentToRendererMessage] = TypeAdapter(
    AgentToRendererMessage
)

ROLE_INSTRUCTION = (
    "You are a specialized assistant for currency conversions. "
    "If the user asks about anything other than currency conversion or exchange rates, "
    "politely state that you cannot help with that topic and can only assist with "
    "currency-related queries. Do not attempt to answer unrelated questions or use "
    "tools for other purposes.\n\n"
    "Show results as A2UI. Prefer the server-side macros: RateCard for a rate or a "
    "conversion, RateHistoryChart for trends or history over time, RateComparison for "
    "comparing several currencies against one. These macros look up the figures on the "
    "server, so pass only currency codes and the amount or day count; do not call "
    "get_exchange_rate first. Use Basic catalog components (Card, Column, Row, Text) "
    "or the charts only for layouts the macros do not cover. Use get_exchange_rate "
    "only to answer in plain text when no UI is wanted."
)
TOOL_INSTRUCTION = (
    f"To show A2UI to the user, call the `{TOOL_NAME}` tool and pass the A2UI block"
    " in its `a2ui_payload` argument instead of writing the block in your reply."
    " When the user asks for A2UI, a card or a chart in any form, including as reply"
    " text or without tools, show it by calling the tool; never answer such a request"
    " with only an explanation of how A2UI is sent."
)


def system_prompt() -> str:
    """The role, then the A2UI format's rules, catalog, examples and tool rule."""
    gen = a2ui_processor.format.prompt_generator
    sections = [
        ROLE_INSTRUCTION,
        "## Workflow Description:\n" + gen.generate_base_rules(),
        gen.generate_catalog_instructions(include_schema=True),
        "### Examples:\n" + gen.generate_examples(),
        TOOL_INSTRUCTION,
    ]
    return "\n\n".join(s for s in sections if s and s.strip())


def compile_a2ui(payload: str) -> list[dict]:
    """Compiles an Express block, expands the macros, validates both sides."""
    parser = a2ui_processor.parser
    blocks = (
        [
            raw.part.a2ui_raw
            for raw in parser.unwrap(payload)
            if isinstance(raw.part, RawA2uiPart)
        ]
        if parser.has_format_content(payload)
        else [payload]
    )
    compiled = []
    for block in blocks:
        compiled.extend(parser.compile(block))
    messages = to_message_dicts(compiled)
    if not messages:
        raise ValueError("The payload holds no A2UI messages.")
    validate_payload(a2ui_processor.active_catalogs, messages)
    typed = [_message_adapter.validate_python(m) for m in messages]
    expanded = macro_expander.transform_to_transport(typed)
    wire = [m.model_dump(by_alias=True, exclude_none=True) for m in expanded]
    validate_payload(BASE_CATALOGS, wire)
    return wire


@tool(name=TOOL_NAME)
def send_a2ui_json_to_client(
    a2ui_payload: Annotated[
        str,
        Field(
            description="The A2UI block to send to the client, in the A2UI format "
            "that the system instructions describe."
        ),
    ],
) -> str:
    """Sends A2UI to the client to render rich UI for the user.

    This tool can be called multiple times in the same turn to render multiple
    UI surfaces.
    """
    try:
        wire = compile_a2ui(a2ui_payload)
    except Exception as e:  # noqa: BLE001 - every failure goes back to the model as a tool error
        logger.warning("A2UI tool rejected a payload: %s", type(e).__name__)
        return json.dumps({ERROR_KEY: f"Failed to call A2UI tool {TOOL_NAME}: {e}"})
    logger.info("Validated call to tool %s", TOOL_NAME)
    record(wire)  # mesh: hand the validated A2UI to the A2A executor
    return json.dumps({VALIDATED_KEY: wire})


class EndTurnAfterUi(FunctionMiddleware):
    """The UI is the answer: end the run after a successful send.

    A rejected payload goes back to the model instead, which can fix it or
    answer in text.
    """

    async def process(
        self,
        context: FunctionInvocationContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        await call_next()
        if context.function.name == TOOL_NAME and VALIDATED_KEY in _result_text(
            context.result
        ):
            raise MiddlewareTermination("A2UI sent", result=context.result)


def _result_text(result: object) -> str:
    """The text of a tool result: a ``str``, or the text items of a ``list[Content]``."""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "".join(getattr(c, "text", None) or "" for c in result)
    return ""


def mcp_tool() -> MCPStdioTool:
    """The Frankfurter MCP server, started as a stdio child of the agent."""
    server = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_server.py")
    return MCPStdioTool(
        name="currency",
        command=sys.executable,
        args=[server],
        env={**os.environ, "MCP_TRANSPORT": "stdio"},
        load_prompts=False,
    )


def client() -> OpenAIChatCompletionClient:
    """Azure OpenAI through Entra ID: the Azure CLI login locally, the managed identity on Azure."""
    return OpenAIChatCompletionClient(
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT", DEFAULT_MODEL),
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        credential=DefaultAzureCredential(),
    )


def build_agent(tools_extra: list | None = None) -> Agent:
    return Agent(
        client(),
        system_prompt(),
        name="currency_agent",
        description="An agent that can help with currency conversions",
        tools=[send_a2ui_json_to_client, *(tools_extra or [])],
        # One tool call per model turn: two parallel UI sends would both create
        # the same surface, and the renderer rejects the second createSurface.
        default_options={"allow_multiple_tool_calls": False},
        middleware=[EndTurnAfterUi(), A2uiRescueMiddleware()],
    )
