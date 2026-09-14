"use client";

import {
  Activity,
  BadgeDollarSign,
  BarChart3,
  BrainCircuit,
  CircleDollarSign,
  CreditCard,
  FileCheck2,
  Gauge,
  Pause,
  Play,
  RefreshCw,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Wallet
} from "lucide-react";
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import { auditRows, dashboardView } from "../lib/dashboard-view.mjs";

type Signal = {
  signal: string;
  signal_source?: string;
  execution_action: string;
  confidence: number;
  symbol: string;
  interval: string;
  price: number;
  rsi: number;
  ema_fast: number;
  ema_mid: number;
  ema_slow: number;
  macd_histogram: number;
  atr: number;
  stop_loss: number | null;
  take_profit: number | null;
  bullish_score: number;
  bearish_score: number;
  reasons: string[];
  timestamp_utc: string;
  position_after_signal: string;
};

type AgentState = {
  position?: string;
  last_signal?: string;
  last_confidence?: number;
  last_reasons?: string[];
  last_snapshot?: Partial<Signal> & {
    live_price?: number;
  };
};

type AuditEvent = {
  eventId?: string;
  eventType?: string;
  createdAt?: string;
  finalAction?: string;
  status?: string;
  humanReadableReason?: string;
  payloadHash?: string;
};

type Ap2Payload = {
  ok?: boolean;
  protocol?: {
    implemented?: boolean;
    mode?: string;
    notice?: string;
  };
  usingDefaultSimulationSecret?: boolean;
  operations?: AuditEvent[];
  auditEvents?: AuditEvent[];
};

type CheckoutResult = {
  valid?: boolean;
  messages?: string[];
  registeredParticipants?: string[];
  intentMandateId?: string;
  cartMandateId?: string;
  paymentMandateId?: string;
  cartTotal?: number;
  currency?: string;
  humanApprovalRequired?: boolean;
  cartApproved?: boolean;
  humanPresent?: boolean;
  happyPathValid?: boolean;
  humanNotPresentFlowValid?: boolean;
  overBudgetRejected?: boolean;
  badCategoryRejected?: boolean;
  overBudgetMessages?: string[];
  badCategoryMessages?: string[];
};

type AutoStatus = {
  simulationOnly?: boolean;
  marketDataOnly?: boolean;
  running: boolean;
  startedAtUtc: string;
  lastTickUtc: string;
  lastError: string | null;
  pollSeconds: number;
  rules: {
    startingCash: number;
    buyCooldownSeconds: number;
    dropToBuyUsd: number;
    riseToSellUsd: number;
    feeRateBps: number;
    slippageBps: number;
    requireSignalConfirmation: boolean;
    executionMode: string;
  };
  signal: Signal | null;
  simulation: {
    cashBalance?: number;
    btcBalance?: number;
    equity?: number;
    entryPrice?: number | null;
    realizedPnl?: number;
    unrealizedPnl?: number;
    tradeCount?: number;
    lastSeenPrice?: number;
    totalFeesUsd?: number;
    totalSlippageCostUsd?: number;
  };
  messages: string[];
};

type PricePoint = {
  price: number;
  timestamp: string;
};

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2
});

function formatPrice(value: number | null | undefined) {
  return typeof value === "number" ? currency.format(value) : "-";
}

function formatNumber(value: number | undefined, digits = 2) {
  return typeof value === "number" ? value.toFixed(digits) : "-";
}

function formatTime(value: string | undefined) {
  if (!value) return "Waiting";
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(value));
}

function toneForSignal(signal: string | undefined) {
  if (signal === "BUY") return "buy";
  if (signal === "SELL") return "sell";
  return "hold";
}

function parseCheckoutItems(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name = "", category = "", quantity = "1", unitPrice = "0"] = line.split(",").map((part) => part.trim());
      return {
        name,
        category,
        quantity: Number(quantity),
        unitPrice: Number(unitPrice)
      };
    });
}

export default function Home() {
  const requestVersion = useRef(0);
  const mutationPending = useRef(false);
  const [section, setSection] = useState("simulation");
  const [connected, setConnected] = useState(false);
  const [state, setState] = useState<AgentState | null>(null);
  const [signal, setSignal] = useState<Signal | null>(null);
  const [auto, setAuto] = useState<AutoStatus | null>(null);
  const [ap2Protocol, setAp2Protocol] = useState<Ap2Payload["protocol"] | null>(null);
  const [usingDefaultAp2Secret, setUsingDefaultAp2Secret] = useState(false);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [priceHistory, setPriceHistory] = useState<PricePoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [runningSignal, setRunningSignal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState({
    startingCash: "500",
    pollSeconds: "5",
    buyCooldownSeconds: "5",
    dropToBuyUsd: "25",
    riseToSellUsd: "25",
    feeRateBps: "10",
    slippageBps: "2",
    requireSignalConfirmation: false
  });
  const [settingsTouched, setSettingsTouched] = useState(false);
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [checkoutResult, setCheckoutResult] = useState<CheckoutResult | null>(null);
  const [checkoutForm, setCheckoutForm] = useState({
    userId: "web_user",
    merchantId: "web_merchant",
    agentId: "web_agent",
    maximumSpendingAmount: "100",
    currency: "USD",
    allowedCategories: "books, software",
    items: "Python ebook, books, 1, 24.99\nEditor plugin, software, 1, 19.99",
    paymentMethod: "simulated_card",
    humanApprovalRequired: true,
    approveCart: true,
    humanPresent: true
  });

  const displayedSignal = auto?.running ? auto.signal : signal ?? auto?.signal;
  const activeSignal = displayedSignal?.signal ?? state?.last_signal ?? "—";
  const view = dashboardView(auto, displayedSignal);
  const tone = toneForSignal(activeSignal);
  const snapshot = displayedSignal ?? state?.last_snapshot;
  const reasons = displayedSignal?.reasons ?? state?.last_reasons ?? [];
  const btcPrice = displayedSignal?.price ?? state?.last_snapshot?.live_price;
  const btcPosition = (auto?.simulation?.btcBalance ?? 0) > 0 ? "Има BTC" : "Без позиция";
  const tradeMessages = auto?.messages ?? [];
  const checkoutChainValid = checkoutResult ? Boolean(checkoutResult.valid ?? checkoutResult.happyPathValid) : false;
  const apiStatus = connected ? "Свързан" : "Няма връзка";
  const modeStatus = auto?.simulationOnly === false || ap2Protocol?.implemented !== false ? "Проверете конфигурацията" : "Само симулация";

  const scoreSpread = useMemo(() => {
    const bullish = snapshot?.bullish_score ?? 0;
    const bearish = snapshot?.bearish_score ?? 0;
    return bullish - bearish;
  }, [snapshot]);

  const chartStats = useMemo(() => {
    if (!priceHistory.length) {
      return {
        min: btcPrice,
        max: btcPrice,
        change: 0
      };
    }

    const prices = priceHistory.map((point) => point.price);
    return {
      min: Math.min(...prices),
      max: Math.max(...prices),
      change: priceHistory[priceHistory.length - 1].price - priceHistory[0].price
    };
  }, [btcPrice, priceHistory]);

  useEffect(() => {
    if (typeof btcPrice !== "number") return;

    const timestamp = auto?.lastTickUtc ?? signal?.timestamp_utc ?? new Date().toISOString();
    setPriceHistory((current) => {
      const lastPoint = current[current.length - 1];
      if (lastPoint?.timestamp === timestamp && lastPoint.price === btcPrice) return current;
      return [...current, { price: btcPrice, timestamp }].slice(-180);
    });
  }, [auto?.lastTickUtc, btcPrice, signal?.timestamp_utc]);

  const loadDashboard = useCallback(async (
    action: "auto" | "state" | "signal" | "start-auto" | "stop-auto" | "configure-auto" = "auto",
    params?: URLSearchParams
  ) => {
    const mutation = !["auto", "state"].includes(action);
    if (mutationPending.current) return false;
    const version = ++requestVersion.current;
    if (mutation) mutationPending.current = true;
    if (mutation) setLoading(true);
    if (mutation) setError(null);
    if (action === "signal") setRunningSignal(true);

    try {
      const mutatingAction = ["signal", "start-auto", "stop-auto", "configure-auto"].includes(action);
      const [stateResponse, ap2Response] = await Promise.all([
        fetch(`/api/agent?action=${action}${params ? `&${params.toString()}` : ""}`, {
          method: mutatingAction ? "POST" : "GET",
          headers: mutatingAction ? { "Content-Type": "application/json" } : undefined,
          body: mutatingAction ? "{}" : undefined,
          cache: "no-store"
        }),
        fetch("/api/agent?action=ap2", { cache: "no-store" })
      ]);

      const statePayload = await stateResponse.json();
      const ap2Payload = await ap2Response.json();
      if (version !== requestVersion.current) return false;

      if (!stateResponse.ok || !statePayload.ok) {
        throw new Error(statePayload.error ?? "Could not reach the Python agent API.");
      }

      setConnected(true);
      if (action === "start-auto" || action === "configure-auto") { setPriceHistory([]); setSignal(null); }
      if (statePayload.auto) {
        setAuto(statePayload.auto);
        if (statePayload.auto.running && statePayload.auto.signal) setSignal(statePayload.auto.signal);
      } else if (action === "signal") {
        setSignal(statePayload.signal);
      } else {
        setState(statePayload.state);
      }

      if (ap2Response.ok && ap2Payload.ok) {
        const ap2Data = ap2Payload as Ap2Payload;
        setAp2Protocol(ap2Data.protocol ?? null);
        setUsingDefaultAp2Secret(Boolean(ap2Data.usingDefaultSimulationSecret));
        setAuditEvents(ap2Data.operations ?? ap2Data.auditEvents ?? []);
      }
      return true;
    } catch (caught) {
      if (version !== requestVersion.current) return false;
      if (!mutation) setConnected(false);
      if (mutation) setError(caught instanceof Error ? caught.message : "Неуспешно изпълнение на заявката.");
      return false;
    } finally {
      if (mutation) { mutationPending.current = false; setLoading(false); setRunningSignal(false); }
    }
  }, []);

  useEffect(() => {
    loadDashboard();
    const timer = window.setInterval(() => loadDashboard(), 2000);
    return () => window.clearInterval(timer);
  }, [loadDashboard]);

  useEffect(() => {
    if (!auto || settingsTouched) return;
    setSettings({
      startingCash: String(auto.rules.startingCash),
      pollSeconds: String(auto.pollSeconds),
      buyCooldownSeconds: String(auto.rules.buyCooldownSeconds),
      dropToBuyUsd: String(auto.rules.dropToBuyUsd),
      riseToSellUsd: String(auto.rules.riseToSellUsd),
      feeRateBps: String(auto.rules.feeRateBps),
      slippageBps: String(auto.rules.slippageBps),
      requireSignalConfirmation: auto.rules.requireSignalConfirmation
    });
  }, [auto, settingsTouched]);

  function updateSetting(name: keyof typeof settings, value: string | boolean) {
    setSettingsTouched(true);
    setSettings((current) => ({ ...current, [name]: value }));
  }

  async function applySettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams(
      Object.entries(settings).map(([name, value]) => [name, String(value)])
    );
    if (await loadDashboard("configure-auto", params)) setSettingsTouched(false);
  }

  function updateCheckoutField(name: keyof typeof checkoutForm, value: string | boolean) {
    setCheckoutForm((current) => ({ ...current, [name]: value }));
  }

  async function runCheckoutDemo() {
    setCheckoutLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/agent?action=checkout-demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        cache: "no-store"
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error ?? "Checkout demo failed.");
      }
      setCheckoutResult(payload.checkout);
      await loadDashboard();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Checkout demo failed.");
    } finally {
      setCheckoutLoading(false);
    }
  }

  async function runCheckout(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCheckoutLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/agent?action=checkout-run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          userId: checkoutForm.userId,
          merchantId: checkoutForm.merchantId,
          agentId: checkoutForm.agentId,
          maximumSpendingAmount: Number(checkoutForm.maximumSpendingAmount),
          currency: checkoutForm.currency,
          allowedCategories: checkoutForm.allowedCategories,
          items: parseCheckoutItems(checkoutForm.items),
          paymentMethod: checkoutForm.paymentMethod,
          humanApprovalRequired: checkoutForm.humanApprovalRequired,
          approveCart: checkoutForm.approveCart,
          humanPresent: checkoutForm.humanPresent
        })
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error ?? "Checkout validation failed.");
      }
      setCheckoutResult(payload.checkout);
      await loadDashboard();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Checkout validation failed.");
    } finally {
      setCheckoutLoading(false);
    }
  }

  return (
    <main className="shell">
      <section className="commandBar">
        <div className="brandLockup">
          <Image className="brandLogo" src="/logo.png" alt="BTC Signal Agent logo" width={64} height={64} priority />
          <div>
            <p className="eyebrow">Самостоятелна изследователска среда · BTCUSDT</p>
            <h1>TABSS — търговски симулации</h1>
          </div>
        </div>
        <div className="actions">
          <button type="button" className="button secondary" onClick={() => loadDashboard(auto?.running ? "stop-auto" : "start-auto")} disabled={loading || !auto || (!auto.running && settingsTouched)}>
            {auto?.running ? <Pause size={16} /> : <Play size={16} />}
            {auto?.running ? "Спри" : "Нова симулация"}
          </button>
          <button type="button" className="button primary" onClick={() => loadDashboard("signal")} disabled={loading || auto?.running}>
            <RefreshCw size={16} className={runningSignal ? "spin" : ""} />
            Анализирай веднъж
          </button>
        </div>
      </section>

      {error ? <div role="alert" className="alert">{error}</div> : null}

      <section className="noticePanel">
        <strong>Симулация с реални пазарни данни.</strong>
        <span>Няма реални поръчки или плащания. Настройте правилата и стартирайте ново изпълнение. Всяка нова симулация започва отначало със запазения начален капитал.</span>
      </section>

      <section className="statusStrip">
        <Stat label="Връзка със системата" value={apiStatus} tone={!connected ? "bad" : undefined} />
        <Stat label="Пазарни данни" value={view.market} />
        <Stat label="Източник на сигнала" value={view.source} />
        <Stat label="Режим" value={modeStatus} tone={modeStatus === "Само симулация" ? "good" : "bad"} />
      </section>

      <nav className="workspaceNav" aria-label="Раздели">
        <button type="button" aria-pressed={section === "simulation"} onClick={() => setSection("simulation")}>Симулация</button>
        <button type="button" aria-pressed={section === "mandates"} onClick={() => setSection("mandates")}>Експерименти с мандати</button>
        <button type="button" aria-pressed={section === "details"} onClick={() => setSection("details")}>Анализ и журнал</button>
      </nav>
      <section className="decisionPanel" aria-live="polite">
        <div><span className="mutedLabel">Състояние на симулацията</span><h2>{view.action}</h2><p>{view.explanation}</p></div>
        <div><span className="mutedLabel">Аналитичен сигнал · {view.source}</span><strong className={`signalPill ${tone}`}>{activeSignal}</strong><p>Препоръка от анализа. Сделката изисква ценови условия и валиден мандат.</p></div>
      </section>
      <section className="heroGrid" hidden={section !== "simulation"}>
        <article className={`pricePanel ${tone}`}>
          <div className="priceHeader">
            <div>
              <span className="mutedLabel">Последна цена</span>
              <strong>{formatPrice(btcPrice)}</strong>
            </div>
            <span className="mutedLabel">BTC / USDT</span>
          </div>
          <div className="priceMeta">
            <Meta label="Позиция" value={btcPosition} />
            <Meta label="Оценка на сигнала" value={displayedSignal ? `${displayedSignal.confidence}%` : "—"} />
            <Meta label="Последен цикъл" value={formatTime(auto?.lastTickUtc)} />
            <Meta label="Интервал" value={auto?.running ? `${auto.pollSeconds}s` : "Спряна"} />
          </div>
          <p className="helpText">Оценката на сигнала не е вероятност за печалба. Графиката показва наблюденията в тази сесия на браузъра.</p>
          <LivePriceChart points={priceHistory} currentPrice={btcPrice} minPrice={chartStats.min} maxPrice={chartStats.max} change={chartStats.change} />
        </article>

        <article className="portfolioPanel">
          <div className="panelHead">
            <Wallet size={17} />
            <h2>Симулиран портфейл</h2>
          </div>
          <div className="portfolioGrid">
            <Stat label="Обща стойност" value={formatPrice(auto?.simulation?.equity)} />
            <Stat label="Свободен капитал" value={formatPrice(auto?.simulation?.cashBalance)} />
            <Stat label="BTC" value={formatNumber(auto?.simulation?.btcBalance, 8)} />
            <Stat label="Реализиран резултат" value={formatPrice(auto?.simulation?.realizedPnl)} tone={(auto?.simulation?.realizedPnl ?? 0) >= 0 ? "good" : "bad"} />
            <Stat label="Такси" value={formatPrice(auto?.simulation?.totalFeesUsd)} />
            <Stat label="Ценово отклонение" value={formatPrice(auto?.simulation?.totalSlippageCostUsd)} />
          </div>
          <div className="ruleStrip">
            <span>Спад за покупка {formatPrice(auto?.rules?.dropToBuyUsd)}</span>
            <span>Покачване за продажба {formatPrice(auto?.rules?.riseToSellUsd)}</span>
            <span>{auto?.simulation?.tradeCount ?? 0} изпълнени операции</span>
            <span>{auto?.rules?.executionMode === "PRICE_AND_SIGNAL" ? "Изисква потвърждение от сигнал" : "Изпълнение по ценови правила"}</span>
          </div>
          <h3 className="settingsHeading">Правила за следващото изпълнение</h3>
          <p className="helpText">Покупка с целия наличен капитал при спад между две наблюдения. Продажба на целия BTC баланс при покачване от ефективната входна цена. Няма автоматичен stop-loss.</p>
          <form className="settingsForm" onSubmit={applySettings}>
            <label>
              <span>Начален капитал ($)</span>
              <input
                min="1"
                max="1000"
                step="1"
                required
                type="number"
                value={settings.startingCash}
                onChange={(event) => updateSetting("startingCash", event.target.value)}
              />
            </label>
            <label>
              <span>Наблюдение през (сек.)</span>
              <input
                min="1"
                max="3600"
                step="1"
                required
                type="number"
                value={settings.pollSeconds}
                onChange={(event) => updateSetting("pollSeconds", event.target.value)}
              />
            </label>
            <label>
              <span>Изчакване след продажба (сек.)</span>
              <input
                min="0"
                max="86400"
                step="1"
                required
                type="number"
                value={settings.buyCooldownSeconds}
                onChange={(event) => updateSetting("buyCooldownSeconds", event.target.value)}
              />
            </label>
            <label>
              <span>Спад между наблюденията ($)</span>
              <input
                min="0.01"
                max="100000"
                step="0.01"
                required
                type="number"
                value={settings.dropToBuyUsd}
                onChange={(event) => updateSetting("dropToBuyUsd", event.target.value)}
              />
            </label>
            <label>
              <span>Покачване от входната цена ($)</span>
              <input
                min="0.01"
                max="100000"
                step="0.01"
                required
                type="number"
                value={settings.riseToSellUsd}
                onChange={(event) => updateSetting("riseToSellUsd", event.target.value)}
              />
            </label>
            <label>
              <span>Такса (bps; 10 = 0.1%)</span>
              <input required min="0" max="1000" step="0.1" type="number" value={settings.feeRateBps} onChange={(event) => updateSetting("feeRateBps", event.target.value)} />
            </label>
            <label>
              <span>Отклонение (bps; 2 = 0.02%)</span>
              <input required min="0" max="1000" step="0.1" type="number" value={settings.slippageBps} onChange={(event) => updateSetting("slippageBps", event.target.value)} />
            </label>
            <label className="checkField">
              <input type="checkbox" checked={settings.requireSignalConfirmation} onChange={(event) => updateSetting("requireSignalConfirmation", event.target.checked)} />
              <span>Изисквай BUY/SELL потвърждение от анализа</span>
            </label>
            <p className="helpText wideField" role="status">{settingsTouched ? "Има незапазени настройки. " : "Настройките са запазени. "}{auto?.running ? "Прилагането спира текущото изпълнение и започва ново с нов баланс." : "Запазете промените, след това изберете Нова симулация."}</p>
            <button className="button primary applyButton" type="submit" disabled={loading || !settingsTouched || !auto}>
              {auto?.running ? "Приложи и започни отначало" : "Запази настройките"}
            </button>
          </form>
        </article>
      </section>

      <section className="checkoutPanel" hidden={section !== "mandates"}>
        <div className="panelHead">
          <CreditCard size={17} />
          <h2>Проверка на разрешена покупка</h2>
        </div>
        <p className="helpText">Отделен AP2-inspired експеримент с потребител, търговец и агент. Одобрението и подписите се симулират локално. Този сценарий не управлява BTC сделките.</p>
        <form className="checkoutForm" onSubmit={runCheckout}>
          <label>
            <span>Потребител</span>
            <input value={checkoutForm.userId} onChange={(event) => updateCheckoutField("userId", event.target.value)} />
          </label>
          <label>
            <span>Търговец</span>
            <input value={checkoutForm.merchantId} onChange={(event) => updateCheckoutField("merchantId", event.target.value)} />
          </label>
          <label>
            <span>Агент</span>
            <input value={checkoutForm.agentId} onChange={(event) => updateCheckoutField("agentId", event.target.value)} />
          </label>
          <label>
            <span>Бюджет</span>
            <input
              min="0.01"
              step="0.01"
              type="number"
              value={checkoutForm.maximumSpendingAmount}
              onChange={(event) => updateCheckoutField("maximumSpendingAmount", event.target.value)}
            />
          </label>
          <label>
            <span>Валута</span>
            <input value={checkoutForm.currency} onChange={(event) => updateCheckoutField("currency", event.target.value.toUpperCase())} />
          </label>
          <label>
            <span>Метод на симулирано плащане</span>
            <input value={checkoutForm.paymentMethod} onChange={(event) => updateCheckoutField("paymentMethod", event.target.value)} />
          </label>
          <label className="wideField">
            <span>Разрешени категории</span>
            <input value={checkoutForm.allowedCategories} onChange={(event) => updateCheckoutField("allowedCategories", event.target.value)} />
          </label>
          <label className="wideField">
            <span>Артикули</span>
            <small>Един артикул на ред: име, категория, цяло количество, единична цена. Например: Книга, books, 1, 20</small>
            <textarea rows={4} value={checkoutForm.items} onChange={(event) => updateCheckoutField("items", event.target.value)} />
          </label>
          <label className="checkField">
            <input
              type="checkbox"
              checked={checkoutForm.humanApprovalRequired}
              onChange={(event) => updateCheckoutField("humanApprovalRequired", event.target.checked)}
            />
            <span>Изисква одобрение</span>
          </label>
          <label className="checkField">
            <input
              type="checkbox"
              checked={checkoutForm.approveCart}
              onChange={(event) => updateCheckoutField("approveCart", event.target.checked)}
            />
            <span>Симулирай потребителско одобрение</span>
          </label>
          <label className="checkField">
            <input
              type="checkbox"
              checked={checkoutForm.humanPresent}
              onChange={(event) => updateCheckoutField("humanPresent", event.target.checked)}
            />
            <span>Потребителят присъства</span>
          </label>
          <div className="checkoutActions">
            <button className="button primary" type="submit" disabled={checkoutLoading}>
              <ShieldCheck size={16} />
              Провери покупката
            </button>
            <button className="button secondary" type="button" onClick={runCheckoutDemo} disabled={checkoutLoading}>
              <RefreshCw size={16} className={checkoutLoading ? "spin" : ""} />
              Стартирай примерните сценарии
            </button>
          </div>
        </form>
        <div className={`checkoutResult ${checkoutResult ? (checkoutChainValid ? "valid" : "invalid") : ""}`}>
          {checkoutResult ? (
            <>
              <div className="checkoutSummary">
                <Stat label="Проверка" value={checkoutChainValid ? "VALID" : "REJECTED"} tone={checkoutChainValid ? "good" : "bad"} />
                <Stat label="Обща сума" value={formatPrice(checkoutResult.cartTotal)} />
                <Stat label="Одобрение" value={checkoutResult.cartApproved ? "SIGNED" : checkoutResult.humanApprovalRequired ? "MISSING" : "NOT REQUIRED"} />
                <Stat label="Потребител" value={checkoutResult.humanPresent ? "PRESENT" : "NOT PRESENT"} />
              </div>
              <div className="checkoutMessages">
                {(checkoutResult.messages ?? []).map((message) => (
                  <FeedItem key={message} tone={message === "OK" ? "good" : "bad"} title="Validation" text={message} />
                ))}
                {checkoutResult.overBudgetRejected ? <FeedItem tone="good" title="Budget rejection" text={checkoutResult.overBudgetMessages?.join(" ") ?? "Rejected"} /> : null}
                {checkoutResult.badCategoryRejected ? <FeedItem tone="good" title="Category rejection" text={checkoutResult.badCategoryMessages?.join(" ") ?? "Rejected"} /> : null}
                {checkoutResult.humanNotPresentFlowValid ? <FeedItem tone="good" title="No-human flow" text="Validated without cart approval when approval was not required." /> : null}
              </div>
            </>
          ) : (
            <p className="empty">Задайте бюджет и артикули, след това изберете „Провери покупката“.</p>
          )}
        </div>
      </section>

      <section className="deskGrid" hidden={section !== "details"}>
        <article className="panel marketPanel">
          <div className="panelHead">
            <BarChart3 size={17} />
            <h2>Технически анализ</h2>
          </div>
          <div className="indicatorList">
            <Indicator icon={<Gauge size={16} />} label="RSI" value={formatNumber(snapshot?.rsi)} />
            <Indicator icon={<TrendingUp size={16} />} label="Bullish score" value={String(snapshot?.bullish_score ?? 0)} tone="good" />
            <Indicator icon={<TrendingDown size={16} />} label="Bearish score" value={String(snapshot?.bearish_score ?? 0)} tone="bad" />
            <Indicator icon={<BadgeDollarSign size={16} />} label="ATR" value={formatPrice(snapshot?.atr)} />
            <Indicator icon={<Activity size={16} />} label="Spread" value={String(scoreSpread)} tone={scoreSpread >= 0 ? "good" : "bad"} />
            <Indicator icon={<CircleDollarSign size={16} />} label="Входна цена" value={formatPrice(auto?.simulation?.entryPrice)} />
          </div>
          <div className="emaTable">
            <div><span>EMA fast</span><strong>{formatPrice(snapshot?.ema_fast)}</strong></div>
            <div><span>EMA mid</span><strong>{formatPrice(snapshot?.ema_mid)}</strong></div>
            <div><span>EMA slow</span><strong>{formatPrice(snapshot?.ema_slow)}</strong></div>
          </div>
        </article>

        <article className="panel feedPanel">
          <div className="panelHead">
            <BrainCircuit size={17} />
            <h2>Решения и събития</h2>
          </div>
          <div className="feedList">
            {auto?.lastError ? <FeedItem tone="bad" title="Agent error" text={auto.lastError} /> : null}
            {tradeMessages.slice(-4).reverse().map((message) => (
              <FeedItem key={message} tone={message.includes("BUY") ? "good" : message.includes("SELL") ? "warn" : "neutral"} title="Simulation event" text={message} />
            ))}
            {reasons.slice(0, 4).map((reason) => (
              <FeedItem key={reason} title="Signal reason" text={reason} />
            ))}
            {!reasons.length && !tradeMessages.length ? <FeedItem title="Waiting" text="The first automatic cycle has not completed yet." /> : null}
          </div>
        </article>

        <article className="panel auditPanel">
          <div className="panelHead">
            <ShieldCheck size={17} />
            <h2>Журнал на мандатите · AP2-inspired</h2>
          </div>
          <div className="auditNotice">
            <span>{ap2Protocol?.notice ?? "AP2-inspired local simulation only. Real payment rails are disabled."}</span>
            {usingDefaultAp2Secret ? <small>Локален ключ по подразбиране</small> : null}
          </div>
          <div className="auditList">
            {auditEvents.length ? (
              auditRows(auditEvents).reverse().slice(0, 8).map(({ event, key }) => (
                <div className="auditRow" key={key}>
                  <FileCheck2 size={16} />
                  <div>
                    <strong>{event.eventType ?? "Audit event"}</strong>
                    <span>{event.humanReadableReason ?? event.status ?? "Recorded"}</span>
                    <span>{formatTime(event.createdAt)}</span>
                  </div>
                  <small>{event.finalAction ?? "HOLD"}</small>
                </div>
              ))
            ) : (
              <p className="empty">Все още няма записани мандати. Стартирайте симулация или примерен checkout сценарий.</p>
            )}
          </div>
        </article>
      </section>
    </main>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="meta">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <div className="stat">
      <span>{label}</span>
      <strong className={tone ?? ""}>{value}</strong>
    </div>
  );
}

function Indicator({
  icon,
  label,
  value,
  tone
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="indicator">
      {icon}
      <span>{label}</span>
      <strong className={tone ?? ""}>{value}</strong>
    </div>
  );
}

function LivePriceChart({
  points,
  currentPrice,
  minPrice,
  maxPrice,
  change
}: {
  points: PricePoint[];
  currentPrice: number | undefined;
  minPrice: number | undefined;
  maxPrice: number | undefined;
  change: number;
}) {
  const width = 640;
  const height = 170;
  const padding = 12;
  const chartPoints = points.length ? points : typeof currentPrice === "number" ? [{ price: currentPrice, timestamp: "" }] : [];
  const prices = chartPoints.map((point) => point.price);
  const low = typeof minPrice === "number" ? minPrice : Math.min(...prices);
  const high = typeof maxPrice === "number" ? maxPrice : Math.max(...prices);
  const range = Math.max(high - low, 1);

  const linePath = chartPoints
    .map((point, index) => {
      const x = padding + (index / Math.max(chartPoints.length - 1, 1)) * (width - padding * 2);
      const y = height - padding - ((point.price - low) / range) * (height - padding * 2);
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");

  const areaPath = linePath ? `${linePath} L ${width - padding} ${height - padding} L ${padding} ${height - padding} Z` : "";
  const lastPoint = chartPoints[chartPoints.length - 1];
  const lastX = padding + ((chartPoints.length - 1) / Math.max(chartPoints.length - 1, 1)) * (width - padding * 2);
  const lastY = lastPoint ? height - padding - ((lastPoint.price - low) / range) * (height - padding * 2) : height - padding;
  const changeTone = change >= 0 ? "good" : "bad";

  return (
    <div className="liveChart">
      <div className="chartHead">
        <div>
          <span className="mutedLabel">Live BTC chart</span>
          <strong>{formatPrice(currentPrice)}</strong>
        </div>
        <span className={changeTone}>{change >= 0 ? "+" : ""}{formatPrice(change)}</span>
      </div>
      <svg className="priceChartSvg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Live BTC price chart">
        <line x1={padding} y1={padding} x2={padding} y2={height - padding} />
        <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} />
        <path className="chartArea" d={areaPath} />
        <path className="chartLine" d={linePath} />
        {lastPoint ? <circle className="chartDot" cx={lastX} cy={lastY} r="4.5" /> : null}
      </svg>
      <div className="chartMeta">
        <span>Min {formatPrice(minPrice)}</span>
        <span>{points.length} ticks</span>
        <span>Max {formatPrice(maxPrice)}</span>
      </div>
    </div>
  );
}

function FeedItem({
  title,
  text,
  tone = "neutral"
}: {
  title: string;
  text: string;
  tone?: "good" | "bad" | "warn" | "neutral";
}) {
  return (
    <div className={`feedItem ${tone}`}>
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}
