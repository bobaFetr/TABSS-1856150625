import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const agentApiUrl = process.env.PY_AGENT_API_URL ?? "http://127.0.0.1:8765";

async function readAgent(path: string) {
  const response = await fetch(`${agentApiUrl}${path}`, {
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
    headers: {
      "Content-Type": "application/json"
    },
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
  const action = url.searchParams.get("action") ?? "state";

  if (action === "signal") {
    return readAgent(`/signal?${url.searchParams.toString()}`);
  }

  if (action === "auto") {
    return readAgent("/auto/status");
  }

  if (action === "start-auto") {
    return readAgent("/auto/start");
  }

  if (action === "stop-auto") {
    return readAgent("/auto/stop");
  }

  if (action === "configure-auto") {
    url.searchParams.delete("action");
    return readAgent(`/auto/configure?${url.searchParams.toString()}`);
  }

  if (action === "ap2") {
    return readAgent("/ap2?limit=12");
  }

  if (action === "checkout-demo") {
    return readAgent("/ap2/checkout/demo");
  }

  if (action === "health") {
    return readAgent("/health");
  }

  return readAgent("/state");
}

export async function POST(request: Request) {
  const url = new URL(request.url);
  const action = url.searchParams.get("action") ?? "";

  if (action === "checkout-run") {
    return writeAgent("/ap2/checkout/run", await request.json());
  }

  return NextResponse.json({ ok: false, error: "Not found" }, { status: 404 });
}
