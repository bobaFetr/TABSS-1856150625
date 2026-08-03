import assert from "node:assert/strict";
import test from "node:test";

import { agentRequestSpec } from "../lib/agent-route.mjs";

test("GET actions map to read-only Python endpoints", () => {
  assert.equal(agentRequestSpec("GET", null).path, "/state");
  assert.equal(agentRequestSpec("GET", "auto").path, "/auto/status");
  assert.equal(agentRequestSpec("GET", "ap2").path, "/ap2?limit=12");
  assert.equal(agentRequestSpec("GET", "health").path, "/health");
});

test("mutating actions remain POST-only", () => {
  assert.equal(agentRequestSpec("POST", "start-auto").path, "/auto/start");
  assert.equal(agentRequestSpec("POST", "stop-auto").path, "/auto/stop");
  assert.equal(agentRequestSpec("GET", "start-auto"), null);
  assert.equal(agentRequestSpec("POST", "state"), null);
});

test("validated query settings are forwarded without the action selector", () => {
  const params = new URLSearchParams({ action: "configure-auto", pollSeconds: "10", startingCash: "500" });
  assert.equal(
    agentRequestSpec("POST", "configure-auto", params).path,
    "/auto/configure?pollSeconds=10&startingCash=500"
  );
});

test("unknown actions are rejected", () => {
  assert.equal(agentRequestSpec("GET", "unknown"), null);
  assert.equal(agentRequestSpec("POST", "unknown"), null);
});
