import { NextResponse } from "next/server";
import { agentRequestSpec } from "../../../lib/agent-route.mjs";

export const dynamic = "force-dynamic";

const agentApiUrl = process.env.PY_AGENT_API_URL ?? "http://127.0.0.1:8765";
const agentApiToken = process.env.AGENT_API_TOKEN;

function agentHeaders(includeContentType = false) {
  return {
    ...(includeContentType ? { "Content-Type": "application/json" } : {}),
    ...(agentApiToken ? { Authorization: `Bearer ${agentApiToken}` } : {})
  };
}

async function readAgent(path: string) {
  const response = await fetch(`${agentApiUrl}${path}`, {
    headers: agentHeaders(),
    cache: "no-store"
  });
  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    return NextResponse.json(
      {
        ok: false,
        error: payload?.error ?? `Agent API returned HTTP ${response.status}`
      },
      { status: response.status }
    );
  }

  return NextResponse.json(payload);
}

async function writeAgent(path: string, body: unknown) {
  const response = await fetch(`${agentApiUrl}${path}`, {
    method: "POST",
    headers: agentHeaders(true),
    body: JSON.stringify(body),
    cache: "no-store"
  });
  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    return NextResponse.json(
      {
        ok: false,
        error: payload?.error ?? `Agent API returned HTTP ${response.status}`
      },
      { status: response.status }
    );
  }

  return NextResponse.json(payload);
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const spec = agentRequestSpec("GET", url.searchParams.get("action"), url.searchParams);
  return spec ? readAgent(spec.path) : NextResponse.json({ ok: false, error: "Not found" }, { status: 404 });
}

export async function POST(request: Request) {
  const url = new URL(request.url);
  const action = url.searchParams.get("action") ?? "";
  const spec = agentRequestSpec("POST", action, url.searchParams);
  if (!spec) return NextResponse.json({ ok: false, error: "Not found" }, { status: 404 });
  return writeAgent(spec.path, spec.forwardBody ? await request.json() : {});
}
