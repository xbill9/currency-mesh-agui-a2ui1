"""Offline tests for the mesh layer: sink, A2A executor, client, coordinator routing."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from a2a.types import Message, Part, Role, TextPart
from a2ui.a2a import A2UI_MIME_TYPE, get_a2ui_messages

from mesh import sink
from mesh.server import A2uiExecutor

CARD = [{"version": "1.0", "createSurface": {"surfaceId": "main", "catalogId": "x", "components": []}}]


def test_record_outside_capture_is_a_noop():
    sink.record(CARD)


def test_capture_collects_from_child_tasks():
    async def tool():
        sink.record(CARD)

    async def main():
        with sink.capture() as wire:
            await asyncio.gather(tool(), asyncio.to_thread(sink.record, CARD))
        return wire

    assert len(asyncio.run(main())) == 2


class _Queue:
    def __init__(self):
        self.events = []

    async def enqueue_event(self, event):
        self.events.append(event)


def _context(prompt):
    return SimpleNamespace(get_user_input=lambda: prompt, context_id="c1", task_id="t1")


def test_executor_sends_text_and_a2ui_parts_with_provenance():
    async def run(prompt):
        sink.record(CARD)
        return "done"

    q = _Queue()
    asyncio.run(A2uiExecutor(run, {"cloud": "gcp"}).execute(_context("hi"), q))
    (msg,) = q.events
    assert msg.parts[0].root.text == "done"
    assert msg.parts[1].root.metadata["mimeType"] == A2UI_MIME_TYPE
    assert get_a2ui_messages(msg) == CARD
    assert msg.metadata["cloud"] == "gcp" and msg.metadata["a2ui_messages"] == 1


def test_executor_turns_an_agent_failure_into_text():
    async def run(prompt):
        raise RuntimeError("boom")

    q = _Queue()
    asyncio.run(A2uiExecutor(run, {"cloud": "aws"}).execute(_context("hi"), q))
    assert "boom" in q.events[0].parts[0].root.text


@pytest.fixture
def coordinator(monkeypatch):
    from coordinator import agent as coord
    from mesh.client import Answer

    calls = []

    async def fake_ask(cloud, question):
        calls.append(cloud)
        return Answer(cloud=cloud, a2ui=json.loads(json.dumps(CARD)),
                      metadata={"model": f"m-{cloud}", "framework": "f"}), "none"

    monkeypatch.setattr(coord, "_ask", fake_ask)
    return coord, calls


def _ctx():
    return SimpleNamespace(actions=SimpleNamespace(skip_summarization=False))


@pytest.mark.parametrize("job,cloud", [("rate", "gcp"), ("history", "aws"), ("comparison", "azure"), (" Rate ", "gcp")])
def test_route_to_cloud_uses_the_job_table(coordinator, job, cloud):
    coord, calls = coordinator
    ctx = _ctx()
    out = asyncio.run(coord.route_to_cloud(job, "q", ctx))
    assert calls == [cloud]
    assert [s["cloud"] for s in out["sources"]] == [cloud]
    assert ctx.actions.skip_summarization is True


def test_unknown_job_calls_no_cloud(coordinator):
    coord, calls = coordinator
    out = asyncio.run(coord.route_to_cloud("weather", "q", _ctx()))
    assert calls == [] and "error" in out


def test_ask_all_clouds_gives_every_surface_a_unique_id(coordinator):
    coord, calls = coordinator
    out = asyncio.run(coord.ask_all_clouds("q", _ctx()))
    assert sorted(calls) == ["aws", "azure", "gcp"]
    ids = [m["createSurface"]["surfaceId"] for m in out["validated_a2ui_json"]]
    assert len(set(ids)) == 3
    assert all(i.split("-")[0] in ("gcp", "aws", "azure") and i.endswith("-main") for i in ids)


def test_text_only_answer_goes_back_to_the_model(coordinator, monkeypatch):
    coord, _ = coordinator
    from mesh.client import Answer

    async def text_only(cloud, question):
        return Answer(cloud=cloud, text="XYZ is not a currency"), "none"

    monkeypatch.setattr(coord, "_ask", text_only)
    ctx = _ctx()
    out = asyncio.run(coord.route_to_cloud("rate", "q", ctx))
    assert out["validated_a2ui_json"] == [] and ctx.actions.skip_summarization is False
