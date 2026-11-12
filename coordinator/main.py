"""AG-UI endpoint for the mesh coordinator. Port 8110 locally, $PORT on Cloud Run."""

import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint
from fastapi import FastAPI

from coordinator.agent import root_agent

logging.basicConfig(format="[%(levelname)s] %(name)s: %(message)s", level=logging.INFO)

app = FastAPI(title="A2UI currency mesh coordinator")
add_adk_fastapi_endpoint(
    app,
    ADKAgent(adk_agent=root_agent, user_id="mesh_user", session_timeout_seconds=3600,
             use_in_memory_services=True),
    path="/",
)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8110")))
