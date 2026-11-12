"""The client and the server, end to end over HTTP, with a fake agent."""

import asyncio
import socket
import threading
import time

import uvicorn
from a2a.types import AgentSkill

from mesh import sink
from mesh.client import ask
from mesh.server import build_app, build_card

CARD = [{"version": "1.0", "createSurface": {"surfaceId": "main", "catalogId": "x", "components": []}}]


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_roundtrip():
    async def run(prompt):
        sink.record(CARD)
        return f"echo {prompt}"

    port = _free_port()
    url = f"http://127.0.0.1:{port}/"
    card = build_card(name="fake", description="d", url="http://wrong-host/",
                      skill=AgentSkill(id="s", name="s", description="s", tags=[]))
    server = uvicorn.Server(uvicorn.Config(build_app(run, card, {"cloud": "gcp", "model": "m"}),
                                           host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    try:
        answer = asyncio.run(ask("gcp", url, "hi"))
    finally:
        server.should_exit = True
        t.join(5)
    # The card advertised a host that does not exist; the client used the configured endpoint.
    assert answer.error is None, answer.error
    assert answer.text == "echo hi"
    assert answer.a2ui == CARD
    assert answer.metadata["cloud"] == "gcp" and answer.metadata["model"] == "m"
