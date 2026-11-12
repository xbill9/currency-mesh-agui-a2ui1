import { Hono } from "hono";
import { handle } from "hono/vercel";
import {
  CopilotRuntime,
  createCopilotRuntimeHandler,
  InMemoryAgentRunner,
} from "@copilotkit/runtime/v2";
import { HttpAgent } from "@ag-ui/client";

// With COORDINATOR_URL set (Cloud Run), runs go through /api/coordinator,
// which adds a Google ID token. Otherwise AGENT_URL points at the coordinator
// running locally (python3 coordinator/main.py, PORT=8110).
const agentUrl = process.env.COORDINATOR_URL
  ? `http://127.0.0.1:${process.env.PORT || "3000"}/api/coordinator`
  : process.env.AGENT_URL || "http://127.0.0.1:8110/";

const runtime = new CopilotRuntime({
  agents: {
    currency_agent: new HttpAgent({ url: agentUrl }),
  },
  runner: new InMemoryAgentRunner(),
  // A2UI 1.0 is rendered client-side by @a2ui/react (see A2uiMessages.tsx);
  // CopilotKit's built-in A2UI middleware speaks v0.9, so it is not enabled.
});

const multiRouteHandler = createCopilotRuntimeHandler({
  runtime,
  basePath: "/api/copilotkit",
  mode: "multi-route",
  cors: true,
});

const singleRouteHandler = createCopilotRuntimeHandler({
  runtime,
  basePath: "/api/copilotkit",
  mode: "single-route",
  cors: true,
});

const app = new Hono().basePath("/api/copilotkit");

// Root path handler - resolves single-route requests (like POST /api/copilotkit with {method: "info"})
app.all("/", async (c) => singleRouteHandler(c.req.raw));

// Subpath handler - resolves multi-route requests (like GET /info and POST /agent/:agentId/run)
app.all("*", async (c) => {
  const path = c.req.path;
  if (path === "/api/copilotkit" || path === "/api/copilotkit/") {
    return singleRouteHandler(c.req.raw);
  }
  return multiRouteHandler(c.req.raw);
});

export const GET = handle(app);
export const POST = handle(app);
