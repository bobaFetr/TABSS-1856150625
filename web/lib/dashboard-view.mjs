/** Keep duplicate legacy entries visible while assigning distinct React keys. */
export function auditRows(events) {
  const occurrences = new Map();
  return events.map((event) => {
    const identity = event.eventId ? `id:${event.eventId}` : `legacy:${JSON.stringify(event)}`;
    const occurrence = occurrences.get(identity) ?? 0;
    occurrences.set(identity, occurrence + 1);
    return { event, key: JSON.stringify([identity, occurrence]) };
  });
}

/** Presentation derived from execution messages, never from the advisory signal. */
export function dashboardView(auto, signal = auto?.signal, now = Date.now()) {
  const messages = auto?.messages ?? [];
  const stale = messages.some((message) => message.startsWith("STALE")) ||
    (auto?.running && signal?.timestamp_utc && now - Date.parse(signal.timestamp_utc) > Math.max(15, (auto.pollSeconds ?? 5) * 3) * 1000);
  const source = { rules: "Технически правила", openai: "OpenAI", cache: "Запазен сигнал" }[signal?.signal_source] ?? "Няма информация";
  let action = "Изчакване на условията";
  let explanation = (auto?.simulation?.btcBalance ?? 0) > 0
    ? "Има отворена позиция. Продажбата изисква покачване спрямо входната цена."
    : "Покупката изисква спад спрямо предишното наблюдение и изтекло изчакване.";
  const executed = messages.find((message) => message.startsWith("AUTO BUY") || message.startsWith("AUTO SELL"));
  const blocked = messages.find((message) => message.includes("| BLOCKED |"));
  const waiting = messages.find((message) => message.startsWith("TRIGGER WAIT"));
  if (executed) {
    action = executed.startsWith("AUTO BUY") ? "Изпълнена покупка" : "Изпълнена продажба";
    explanation = "Симулираната сделка е записана след проверката на мандатите. Детайлите са в журнала.";
  } else if (blocked) {
    action = "Блокирана операция";
    explanation = blocked;
  } else if (waiting) {
    action = "Изчакване на потвърждение";
    explanation = "Ценовият праг е достигнат, но аналитичният сигнал не потвърждава действието.";
  }
  if (!auto?.running) {
    action = "Симулацията е спряна";
    explanation = "Нова симулация започва с началния капитал от запазените настройки.";
  } else if (auto.lastError) {
    action = "Грешка в последния цикъл";
    explanation = auto.lastError;
  } else if (!auto.lastTickUtc) {
    action = "Първият цикъл се изпълнява";
    explanation = "Изчакват се пазарни данни и първият анализ.";
  }
  return { source, action, explanation, market: stale ? "Остарели данни" : auto?.lastError ? "Грешка при обновяване" : signal ? "Последна получена цена" : "Изчакване на данни" };
}
