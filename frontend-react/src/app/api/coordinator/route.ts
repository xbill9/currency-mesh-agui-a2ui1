// Forwards an AG-UI run to the mesh coordinator on Cloud Run.
//
// The coordinator does not allow unauthenticated calls. On Cloud Run this route
// mints a Google ID token for the coordinator's URL from the metadata server,
// as the UI service's own service account, and streams the coordinator's AG-UI
// events straight back. The browser never holds a credential.

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const METADATA =
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity";

let cached: { token: string; expires: number } | undefined;

async function idToken(audience: string): Promise<string> {
  if (cached && cached.expires > Date.now() + 60_000) return cached.token;
  const r = await fetch(`${METADATA}?audience=${encodeURIComponent(audience)}&format=full`, {
    headers: { "Metadata-Flavor": "Google" },
  });
  if (!r.ok) throw new Error(`metadata server ${r.status}: ${await r.text()}`);
  const token = (await r.text()).trim();
  const exp = JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString()).exp;
  cached = { token, expires: exp * 1000 };
  return token;
}

export async function POST(req: Request): Promise<Response> {
  const target = process.env.COORDINATOR_URL;
  if (!target) return new Response("COORDINATOR_URL is not set", { status: 500 });
  const audience = new URL(target).origin;
  const upstream = await fetch(target, {
    method: "POST",
    headers: {
      authorization: `Bearer ${await idToken(audience)}`,
      "content-type": "application/json",
      accept: "text/event-stream",
    },
    body: await req.text(),
  });
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") || "text/event-stream",
      "cache-control": "no-cache",
    },
  });
}
