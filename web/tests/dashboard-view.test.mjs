import assert from "node:assert/strict";
import test from "node:test";
import { auditRows, dashboardView } from "../lib/dashboard-view.mjs";

const running = { running: true, lastTickUtc: "2026-09-14T00:00:00Z", messages: [], signal: { signal_source: "rules" } };
test("audit rows distinguish the same hash and timestamp, including exact legacy duplicates", () => {
  const first = { payloadHash: "310993ca", createdAt: "2026-09-14T19:37:12+00:00", eventType: "PAYMENT_MANDATE_CREATED" };
  const events = [first, { ...first, eventType: "SIMULATED_TRADE_EXECUTED" }, { ...first }];
  const rows = auditRows(events);
  assert.equal(new Set(rows.map((row) => row.key)).size, 3);
  assert.deepEqual(rows.map((row) => row.event), events);
  assert.deepEqual(auditRows([...events, { eventId: "new" }]).slice(0, 3), rows);
  assert.equal(auditRows([{ eventId: "persisted", status: "OK" }])[0].key,
    auditRows([{ eventId: "persisted", status: "UPDATED" }])[0].key);
});
test("a BUY recommendation does not imply an executed purchase", () => {
  const view = dashboardView({ ...running, signal: { signal: "BUY", signal_source: "rules" } });
  assert.equal(view.action, "Изчакване на условията");
  assert.equal(view.source, "Технически правила");
});
test("execution, blocked mandate and signal confirmation have distinct states", () => {
  for (const [message, action] of [
    ["AUTO BUY | Spent $100", "Изпълнена покупка"],
    ["AUTO SELL | Net $101", "Изпълнена продажба"],
    ["AP2 SIM | BLOCKED | expired", "Блокирана операция"],
    ["TRIGGER WAIT | HOLD", "Изчакване на потвърждение"]
  ]) assert.equal(dashboardView({ ...running, messages: [message] }).action, action);
});
test("stopping does not display the preceding trade as an active action", () => {
  assert.equal(dashboardView({ ...running, running: false, messages: ["AUTO BUY"] }).action, "Симулацията е спряна");
});
test("stale data and absent source are not presented as healthy OpenAI", () => {
  assert.equal(dashboardView({ ...running, messages: ["STALE | timeout"] }).market, "Остарели данни");
  assert.equal(dashboardView(null).source, "Няма информация");
  assert.equal(dashboardView(running, { signal_source: "cache" }).source, "Запазен сигнал");
});
