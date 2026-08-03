const ACTIONS = Object.freeze({
  auto: { method: "GET", path: "/auto/status" },
  ap2: { method: "GET", path: "/ap2?limit=12" },
  health: { method: "GET", path: "/health" },
  state: { method: "GET", path: "/state" },
  signal: { method: "POST", path: "/signal", forwardQuery: true },
  "start-auto": { method: "POST", path: "/auto/start" },
  "stop-auto": { method: "POST", path: "/auto/stop" },
  "configure-auto": { method: "POST", path: "/auto/configure", forwardQuery: true },
  "checkout-demo": { method: "POST", path: "/ap2/checkout/demo" },
  "checkout-run": { method: "POST", path: "/ap2/checkout/run", forwardBody: true }
});

export function agentRequestSpec(method, action, searchParams = new URLSearchParams()) {
  const normalizedMethod = method.toUpperCase();
  const fallbackAction = normalizedMethod === "GET" && !action ? "state" : action;
  const spec = ACTIONS[fallbackAction];
  if (!spec || spec.method !== normalizedMethod) return null;

  let path = spec.path;
  if (spec.forwardQuery) {
    const forwarded = new URLSearchParams(searchParams);
    forwarded.delete("action");
    const query = forwarded.toString();
    if (query) path += `?${query}`;
  }
  return { ...spec, path };
}
