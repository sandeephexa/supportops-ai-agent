import React, { useCallback, useEffect, useState } from "react";
import { useRequestPolling } from "./useRequestPolling";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Code2,
  Copy,
  ExternalLink,
  FileText,
  Fingerprint,
  Layers3,
  LoaderCircle,
  LockKeyhole,
  MessageSquare,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Terminal,
  X,
} from "lucide-react";
import "./styles.css";

type Account = {
  id: string;
  name: string;
  plan: string;
  product_version: string;
};
type Claim = { text: string; evidence_ids: string[]; quote: string };
type Evidence = {
  id: string;
  title: string;
  content: string;
  source: string;
  version: string;
  observed_at: number;
  score: number;
};
type Result = {
  summary: string;
  confirmed_facts: Claim[];
  hypotheses: Claim[];
  recommended_steps: string[];
  unresolved_questions: string[];
  needs_escalation: boolean;
};
type Case = {
  id: string;
  account_id: string;
  question: string;
  status: string;
  phase: string;
  created_at: number;
  result: Result | null;
  evidence: Evidence[];
  guardrail_events: string[];
  error: string | null;
  retryable?: boolean;
  draft: {
    payload: Record<string, unknown>;
    payload_hash: string;
    expires_at: number;
  } | null;
  receipt: { ticket_id: string; connector: string } | null;
};
type Span = {
  id: string;
  name: string;
  duration_ms: number;
  status: string;
  attributes: Record<string, unknown>;
};
type Audit = { id: string; action: string; actor: string; created_at: number };
type Trace = { spans: Span[]; audit: Audit[] };
const labels: Record<string, string> = {
  queued: "Queued",
  running: "Investigating",
  needs_approval: "Needs approval",
  completed: "Completed",
  needs_information: "Needs information",
  declined: "Declined",
  failed: "Needs review",
};
const templates = [
  {
    title: "Credential rotation",
    account: "acme",
    description: "403 errors after a key change",
    question:
      "Acme synchronization jobs started returning 403 errors after credential rotation. Investigate the likely cause, check support entitlement, and prepare an engineering escalation.",
  },
  {
    title: "Rate-limited jobs",
    account: "atlas",
    description: "Repeated 429 synchronization failures",
    question:
      "Investigate Atlas synchronization jobs returning 429 errors. Check the support plan, explain the recommended recovery, and prepare an escalation.",
  },
  {
    title: "Regional incident",
    account: "meridian",
    description: "503 errors across sync-service",
    question:
      "Meridian has 503 failures and a possible regional service incident. Check the incident, investigate the job failures, and prepare an escalation.",
  },
];
function Badge({ status }: { status: string }) {
  return (
    <span className={`badge ${status}`}>
      <span className="status-dot" />
      {labels[status] || status}
    </span>
  );
}
function time(value: number) {
  return new Date(value * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function App() {
  const [accounts, setAccounts] = useState<Account[]>([]),
    [cases, setCases] = useState<Case[]>([]);
  const [selected, setSelected] = useState<string | null>(null),
    [trace, setTrace] = useState<Trace>({ spans: [], audit: [] });
  const [user, setUser] = useState("engineer-acme"),
    [userName, setUserName] = useState("Alex Morgan");
  const [health, setHealth] = useState<{
      mode: string;
      auth_mode: string;
      retrieval?: string;
    } | null>(null),
    [token, setToken] = useState(""),
    [tokenDraft, setTokenDraft] = useState("");
  const [modal, setModal] = useState(false),
    [architecture, setArchitecture] = useState(false),
    [question, setQuestion] = useState(""),
    [account, setAccount] = useState("acme");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [filter, setFilter] = useState("");
  const [tab, setTab] = useState("findings"),
    [source, setSource] = useState<Evidence | null>(null),
    [copied, setCopied] = useState(false);
  const current = cases.find((c) => c.id === selected),
    active = cases.filter((c) =>
      ["queued", "running"].includes(c.status),
    ).length;
  const pending = cases.filter((c) => c.status === "needs_approval").length,
    completed = cases.filter((c) => c.status === "completed").length;
  const api = useCallback(
    async <T,>(path: string, options: RequestInit = {}): Promise<T> => {
      const headers: Record<string, string> =
        health?.auth_mode === "oidc"
          ? { Authorization: `Bearer ${token}` }
          : { "X-Demo-User": user };
      const res = await fetch(`/api${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...headers,
          ...options.headers,
        },
      });
      if (!res.ok) {
        const body = await res
          .json()
          .catch(() => ({ detail: "Request failed" }));
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : "The request could not be validated.",
        );
      }
      return res.json();
    },
    [health?.auth_mode, token, user],
  );
  const ready = !!health && (health.auth_mode !== "oidc" || !!token);
  const reportError = useCallback(
    (e: unknown) => setError((e as Error).message),
    [],
  );
  const refreshCases = useCallback(
    async (signal: AbortSignal) => {
      const items = await api<Case[]>("/cases", { signal });
      if (!signal.aborted) {
        setCases(items);
        setSelected((s) =>
          s && items.some((c) => c.id === s) ? s : items[0]?.id || null,
        );
      }
    },
    [api],
  );
  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() =>
        setError("Cannot connect to the API. Start the backend and refresh."),
      );
  }, []);
  useEffect(() => {
    setCases([]);
    setAccounts([]);
    setSelected(null);
    setError("");
    if (!ready) return;
    const controller = new AbortController();
    const signal = controller.signal;
    Promise.all([
      refreshCases(signal),
      api<Account[]>("/accounts", { signal }),
      api<{ name: string }>("/me", { signal }),
    ])
      .then(([, acc, me]) => {
        if (!signal.aborted) {
          setAccounts(acc);
          setUserName(me.name);
        }
      })
      .catch((e) => {
        if (!signal.aborted) reportError(e);
      });
    return () => controller.abort();
  }, [ready, api, refreshCases, reportError]);
  useRequestPolling(refreshCases, ready && active > 0, true, reportError);
  useEffect(() => {
    setTrace({ spans: [], audit: [] });
    setSource(null);
    setTab("findings");
  }, [selected, user, token]);
  const refreshTrace = useCallback(
    async (signal: AbortSignal) => {
      if (!selected) return;
      const result = await api<Trace>(`/cases/${selected}/trace`, { signal });
      if (!signal.aborted) setTrace(result);
    },
    [api, selected],
  );
  useRequestPolling(
    refreshTrace,
    ready && !!selected && tab === "trace",
    !!current && ["queued", "running"].includes(current.status),
    reportError,
  );
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setModal(false);
        setArchitecture(false);
        setSource(null);
      }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  function startTemplate(index: number) {
    const template = templates[index];
    setQuestion(template.question);
    setAccount(template.account);
    setModal(true);
    setError("");
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await api<Case>("/cases", {
        method: "POST",
        body: JSON.stringify({ question, account_id: account }),
      });
      setCases((items) => [created, ...items]);
      setSelected(created.id);
      setModal(false);
      setQuestion("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function approve(approved: boolean) {
    if (!current?.draft) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Case>(`/cases/${current.id}/approval`, {
        method: "POST",
        body: JSON.stringify({
          approved,
          payload_hash: current.draft.payload_hash,
        }),
      });
      setCases((items) => items.map((c) => (c.id === result.id ? result : c)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function retry() {
    if (!current) return;
    setBusy(true);
    try {
      await api(`/cases/${current.id}/retry`, { method: "POST" });
      setCases((items) =>
        items.map((c) =>
          c.id === current.id ? { ...c, status: "queued", error: null } : c,
        ),
      );
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const accountName = (id: string) =>
    accounts.find((a) => a.id === id)?.name || id;
  const visible = cases.filter((c) =>
    (c.question + " " + accountName(c.account_id))
      .toLowerCase()
      .includes(filter.toLowerCase()),
  );
  const totalTokens = trace.spans.reduce(
    (n, s) =>
      n +
      Number(s.attributes.input_tokens || 0) +
      Number(s.attributes.output_tokens || 0),
    0,
  );
  const priced = trace.spans.filter(
      (s) => s.attributes.estimated_cost_usd !== undefined,
    ),
    cost = priced.reduce(
      (n, s) => n + Number(s.attributes.estimated_cost_usd),
      0,
    );
  const llmSpans = trace.spans.filter((s) => s.name.startsWith("model."));
  const elapsed = trace.spans
    .filter((s) => s.name === "investigation.run")
    .reduce((n, s) => n + s.duration_ms, 0);
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="SupportOps home">
          <span className="brand-icon">
            <Layers3 size={23} />
          </span>
          <span>
            supportops<span className="brand-ai"> / ai</span>
          </span>
        </a>
        <div className="workspace-select">
          <span className="workspace-avatar">N</span>
          <div>
            <strong>Northstar Cloud</strong>
            <small>Support workspace</small>
          </div>
          <ChevronDown size={14} />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <button
          className="nav-item active"
          onClick={() => setArchitecture(false)}
        >
          <MessageSquare size={18} />
          Investigations<span className="nav-count">{cases.length}</span>
        </button>
        <button className="nav-item" onClick={() => setArchitecture(true)}>
          <Code2 size={18} />
          System architecture
          <ArrowDownRight size={15} />
        </button>
        <a
          className="nav-item"
          href="/api/docs"
          target="_blank"
          rel="noreferrer"
        >
          <Terminal size={18} />
          API reference
          <ExternalLink size={13} />
        </a>
        <div className="sidebar-note">
          <div className="note-icon">
            <ShieldCheck size={19} />
          </div>
          <strong>Evidence before action.</strong>
          <p>
            Every investigation is scoped, traced, and reviewed before it
            changes anything.
          </p>
          <div className="note-status">
            <span />
            Approval controls enabled
          </div>
        </div>
        <div className="sidebar-bottom">
          <span className="avatar">
            {userName
              .split(" ")
              .map((x) => x[0])
              .slice(0, 2)
              .join("")}
          </span>
          <div>
            <strong>{userName}</strong>
            <small>
              {user === "viewer-acme"
                ? "Read-only reviewer"
                : "Support engineer"}
            </small>
          </div>
          <button
            className="icon-button"
            aria-label="Switch demo role"
            title="Switch demo role"
            onClick={() => {
              if (health?.auth_mode === "demo") {
                setUser(
                  user === "engineer-acme" ? "viewer-acme" : "engineer-acme",
                );
                setSelected(null);
                setCases([]);
                setError("");
              }
            }}
          >
            <ChevronDown size={16} />
          </button>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} />
            <strong>Investigations</strong>
          </div>
          <div className="environment">
            <span className="environment-dot" />
            {health?.mode === "live"
              ? `Live model · ${health.retrieval === "local_lexical_hash" ? "local retrieval · " : ""}synthetic connectors`
              : "Demo environment"}
            <span className="topbar-divider" />
            <LockKeyhole size={13} />
            Tenant isolated
          </div>
        </header>
        <div className="page-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">SUPPORT INTELLIGENCE</div>
              <h1>From issue to insight.</h1>
              <p>Investigate with evidence. Escalate with confidence.</p>
            </div>
            <button
              className="button primary"
              onClick={() => {
                setAccount(accounts[0]?.id || "acme");
                setQuestion("");
                setModal(true);
                setError("");
              }}
            >
              <Plus size={17} />
              New investigation
            </button>
          </div>
          {error && !modal && (
            <div className="error-banner" role="alert">
              {error}
              <button
                className="icon-button"
                aria-label="Dismiss error"
                onClick={() => setError("")}
              >
                <X size={15} />
              </button>
            </div>
          )}
          <div className="overview">
            <div>
              <span className="stat-icon blue">
                <Activity size={20} />
              </span>
              <div>
                <span className="stat-label">In progress</span>
                <strong>{active.toString().padStart(2, "0")}</strong>
              </div>
              <span className="stat-caption">Gathering evidence</span>
            </div>
            <div>
              <span className="stat-icon amber">
                <Clock3 size={20} />
              </span>
              <div>
                <span className="stat-label">Awaiting approval</span>
                <strong>{pending.toString().padStart(2, "0")}</strong>
              </div>
              <span className="stat-caption">Your review matters</span>
            </div>
            <div>
              <span className="stat-icon green">
                <CheckCircle2 size={20} />
              </span>
              <div>
                <span className="stat-label">Completed</span>
                <strong>{completed.toString().padStart(2, "0")}</strong>
              </div>
              <span className="stat-caption">Verified outcomes</span>
            </div>
          </div>
          <div className="investigation-workspace">
            <section className="case-list">
              <div className="list-title">
                <h2>Investigations</h2>
                <span>{cases.length}</span>
              </div>
              <label className="search">
                <Search size={15} />
                <input
                  aria-label="Search investigations"
                  placeholder="Search investigations…"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
                <span>⌕</span>
              </label>
              <div className="case-items">
                {visible.map((c) => (
                  <button
                    key={c.id}
                    className={`case-item ${selected === c.id ? "selected" : ""}`}
                    onClick={() => setSelected(c.id)}
                  >
                    <div className="case-item-top">
                      <span className="company-mark">
                        {accountName(c.account_id)[0]}
                      </span>
                      <strong>{accountName(c.account_id)}</strong>
                      <span>{time(c.created_at)}</span>
                    </div>
                    <p>{c.question}</p>
                    <div className="case-item-bottom">
                      <Badge status={c.status} />
                      <span className="case-number">{c.id.slice(0, 6)}</span>
                    </div>
                  </button>
                ))}
                {!visible.length && (
                  <div className="list-empty">
                    <MessageSquare size={25} />
                    <strong>
                      {filter
                        ? "No matching investigations"
                        : "Your workspace is ready"}
                    </strong>
                    <p>
                      {filter
                        ? "Try another search."
                        : "Start with an issue below or create a new investigation."}
                    </p>
                  </div>
                )}
              </div>
              <div className="list-footer">
                <span className="live-dot" />
                Updates automatically
              </div>
            </section>
            <section className="detail" aria-live="polite">
              {!current ? (
                <div className="welcome">
                  <span className="welcome-icon">
                    <Sparkles size={27} />
                  </span>
                  <span className="eyebrow">LET’S FIND THE CAUSE</span>
                  <h2>A clearer path to resolution.</h2>
                  <p>
                    Bring the question. Your agent connects the runbooks,
                    <br className="desktop-only" /> account data, and
                    diagnostics to investigate it.
                  </p>
                  <div className="templates">
                    {templates
                      .filter((t) => accounts.some((a) => a.id === t.account))
                      .map((t) => (
                        <button
                          key={t.title}
                          onClick={() => startTemplate(templates.indexOf(t))}
                        >
                          <span className="template-icon">
                            <FileText size={19} />
                          </span>
                          <span>
                            <strong>{t.title}</strong>
                            <small>{t.description}</small>
                          </span>
                          <ArrowRight size={17} />
                        </button>
                      ))}
                  </div>
                  <div className="welcome-foot">
                    <ShieldCheck size={15} />
                    Synthetic enterprise data. No API key needed in demo mode.
                  </div>
                </div>
              ) : (
                <>
                  <div className="detail-heading">
                    <div className="detail-meta">
                      <span className="company-mark">
                        {accountName(current.account_id)[0]}
                      </span>
                      <strong>{accountName(current.account_id)}</strong>
                      <span className="case-number">
                        CASE / {current.id.slice(0, 8).toUpperCase()}
                      </span>
                    </div>
                    <Badge status={current.status} />
                  </div>
                  <div className="request">
                    <span className="section-label">INVESTIGATION REQUEST</span>
                    <h2>{current.question}</h2>
                    <div className="request-meta">
                      <Clock3 size={13} />
                      {time(current.created_at)}
                      <span>·</span>Product v
                      {
                        accounts.find((a) => a.id === current.account_id)
                          ?.product_version
                      }
                      <span>·</span>
                      <ShieldCheck size={13} />
                      Access checked
                    </div>
                  </div>
                  <div
                    className="tabs"
                    role="tablist"
                    aria-label="Investigation detail"
                  >
                    {[
                      ["findings", "Findings", Sparkles],
                      [
                        "evidence",
                        `Evidence ${current.evidence.length || ""}`,
                        BookOpen,
                      ],
                      ["trace", "Execution trace", Activity],
                    ].map(([key, label, Icon]) => {
                      const I = Icon as typeof Sparkles;
                      return (
                        <button
                          role="tab"
                          aria-selected={tab === key}
                          key={key as string}
                          className={tab === key ? "active" : ""}
                          onClick={() => setTab(key as string)}
                        >
                          <I size={15} />
                          {label as string}
                        </button>
                      );
                    })}
                  </div>
                  <div className="detail-body">
                    {["queued", "running"].includes(current.status) && (
                      <div className="running">
                        <LoaderCircle className="spin" size={21} />
                        <div>
                          <strong>{current.phase}</strong>
                          <p>The investigation is saved as it progresses.</p>
                        </div>
                      </div>
                    )}
                    {current.error && (
                      <div className="failed">
                        <strong>Investigation stopped safely</strong>
                        <p>{current.error}</p>
                        {current.retryable !== false && (
                          <button
                            className="button secondary"
                            onClick={retry}
                            disabled={busy}
                          >
                            Retry investigation
                          </button>
                        )}
                      </div>
                    )}
                    {tab === "findings" && current.result && (
                      <>
                        <div className="finding-summary">
                          <div className="summary-icon">
                            <Sparkles size={20} />
                          </div>
                          <div>
                            <span className="section-label">
                              INVESTIGATION FINDING
                            </span>
                            <h3>{current.result.summary}</h3>
                            <div className="summary-foot">
                              <CheckCircle2 size={13} />
                              Citation provenance checked<span>·</span>
                              {current.evidence.length} evidence sources
                            </div>
                          </div>
                        </div>
                        <section className="facts">
                          <h3>
                            What we know <span>VERIFIED SOURCES</span>
                          </h3>
                          {current.result.confirmed_facts.map((f, i) => (
                            <div className="fact" key={i}>
                              <CheckCircle2 size={16} />
                              <div>
                                <p>{f.text}</p>
                                <div className="citation-row">
                                  {f.evidence_ids.map((id) => (
                                    <button
                                      key={id}
                                      className="citation"
                                      onClick={() =>
                                        setSource(
                                          current.evidence.find(
                                            (e) => e.id === id,
                                          ) || null,
                                        )
                                      }
                                    >
                                      <FileText size={11} />
                                      {current.evidence.find((e) => e.id === id)
                                        ?.title || id}
                                      <ExternalLink size={10} />
                                    </button>
                                  ))}
                                </div>
                              </div>
                            </div>
                          ))}
                        </section>
                        {!!current.result.hypotheses.length && (
                          <section className="hypotheses">
                            <span className="section-label">
                              WORKING HYPOTHESIS
                            </span>
                            {current.result.hypotheses.map((h, i) => (
                              <div key={i}>
                                <p>{h.text}</p>
                                <small>
                                  Inference from the cited evidence; validate
                                  with a controlled test.
                                </small>
                                <div className="citation-row">
                                  {h.evidence_ids.map((id) => (
                                    <button
                                      className="citation"
                                      key={id}
                                      onClick={() =>
                                        setSource(
                                          current.evidence.find(
                                            (e) => e.id === id,
                                          ) || null,
                                        )
                                      }
                                    >
                                      <FileText size={11} />
                                      {current.evidence.find((e) => e.id === id)
                                        ?.title || id}
                                    </button>
                                  ))}
                                </div>
                              </div>
                            ))}
                          </section>
                        )}
                        {!!current.result.recommended_steps.length && (
                          <section className="next-steps">
                            <h3>Recommended next steps</h3>
                            {current.result.recommended_steps.map((s, i) => (
                              <div key={i}>
                                <span>{i + 1}</span>
                                <p>{s}</p>
                              </div>
                            ))}
                          </section>
                        )}
                        {!!current.result.unresolved_questions.length && (
                          <section className="unresolved">
                            <h3>Still to establish</h3>
                            {current.result.unresolved_questions.map((q) => (
                              <p key={q}>{q}</p>
                            ))}
                          </section>
                        )}
                        {!!current.guardrail_events.length && (
                          <div className="guardrail-strip">
                            <ShieldCheck size={16} />
                            <span>{current.guardrail_events.join(" · ")}</span>
                          </div>
                        )}
                      </>
                    )}
                    {tab === "evidence" && (
                      <div className="evidence-list">
                        <div className="section-intro">
                          <h3>Evidence collected for this case</h3>
                          <p>
                            Authorized runbook sections and point-in-time
                            diagnostic snapshots.
                          </p>
                        </div>
                        {current.evidence.map((e) => (
                          <button
                            key={e.id}
                            className="evidence-item"
                            onClick={() => setSource(e)}
                          >
                            <span className="evidence-icon">
                              {e.source === "tool" ? (
                                <Terminal size={19} />
                              ) : (
                                <BookOpen size={19} />
                              )}
                            </span>
                            <div>
                              <strong>{e.title}</strong>
                              <p>
                                {e.content.slice(0, 150)}
                                {e.content.length > 150 ? "…" : ""}
                              </p>
                              <small>
                                {e.source === "tool"
                                  ? "Synthetic diagnostic"
                                  : "Runbook"}{" "}
                                · {e.version} · {time(e.observed_at)}
                              </small>
                            </div>
                            <ChevronRight size={17} />
                          </button>
                        ))}
                        {!current.evidence.length && (
                          <p className="muted">
                            Evidence will appear after the investigation
                            completes validation.
                          </p>
                        )}
                      </div>
                    )}
                    {tab === "trace" && (
                      <div className="trace-view">
                        <div className="trace-stats">
                          <div>
                            <span>Machine time</span>
                            <strong>
                              {elapsed
                                ? (elapsed / 1000).toFixed(2) + "s"
                                : "—"}
                            </strong>
                          </div>
                          <div>
                            <span>Model tokens</span>
                            <strong>
                              {health?.mode === "demo"
                                ? "Demo model"
                                : totalTokens.toLocaleString()}
                            </strong>
                          </div>
                          <div>
                            <span>Inference cost</span>
                            <strong>
                              {health?.mode === "demo"
                                ? "$0.00"
                                : llmSpans.length > 0 &&
                                    priced.length === llmSpans.length
                                  ? "$" + cost.toFixed(4)
                                  : "Unpriced"}
                            </strong>
                          </div>
                        </div>
                        <h3>
                          Execution spans{" "}
                          <span className="muted">{trace.spans.length}</span>
                        </h3>
                        <div className="span-list">
                          {trace.spans.map((s) => (
                            <div className="span-row" key={s.id}>
                              <span
                                className={
                                  s.status === "ok"
                                    ? "trace-dot"
                                    : "trace-dot error"
                                }
                              />
                              <div>
                                <strong>{s.name}</strong>
                                <small>
                                  {String(
                                    s.attributes.model ||
                                      s.attributes.tool ||
                                      s.attributes.framework ||
                                      s.attributes.embedding_version ||
                                      s.attributes.graph_version ||
                                      "",
                                  )}
                                </small>
                              </div>
                              <div className="span-bar">
                                <span
                                  style={{
                                    width:
                                      Math.max(
                                        3,
                                        Math.min(
                                          100,
                                          (s.duration_ms /
                                            Math.max(elapsed, 1)) *
                                            100,
                                        ),
                                      ) + "%",
                                  }}
                                />
                              </div>
                              <span>{s.duration_ms.toFixed(1)} ms</span>
                            </div>
                          ))}
                        </div>
                        <h3 className="audit-title">Audit trail</h3>
                        {trace.audit.map((a) => (
                          <div className="audit-row" key={a.id}>
                            <Fingerprint size={14} />
                            <strong>{a.action}</strong>
                            <span>{a.actor}</span>
                            <time>{time(a.created_at)}</time>
                          </div>
                        ))}
                        <p className="trace-note">
                          <LockKeyhole size={13} />
                          Trace attributes exclude raw prompts, credentials, and
                          customer payloads.
                        </p>
                      </div>
                    )}
                  </div>
                  {current.status === "needs_approval" && current.draft && (
                    <div className="approval-bar">
                      <div className="approval-top">
                        <div className="approval-icon">
                          <ShieldCheck size={21} />
                        </div>
                        <div>
                          <strong>Engineering escalation is ready</strong>
                          <p>
                            {String(current.draft.payload.queue)} queue ·{" "}
                            {accountName(current.account_id)} ·{" "}
                            {current.evidence.length} evidence references
                          </p>
                        </div>
                      </div>
                      <details className="draft-details">
                        <summary>Review exact ticket payload</summary>
                        <pre>
                          {JSON.stringify(current.draft.payload, null, 2)}
                        </pre>
                        <small>
                          Approval fingerprint:{" "}
                          {current.draft.payload_hash.slice(0, 24)}… · Expires{" "}
                          {time(current.draft.expires_at)}
                        </small>
                      </details>
                      <div className="approval-actions">
                        <span>
                          <LockKeyhole size={12} />
                          Your approval is required
                        </span>
                        <button
                          className="button secondary"
                          onClick={() => approve(false)}
                          disabled={busy || user === "viewer-acme"}
                        >
                          Decline
                        </button>
                        <button
                          className="button primary"
                          onClick={() => approve(true)}
                          disabled={busy || user === "viewer-acme"}
                        >
                          {busy ? (
                            <LoaderCircle className="spin" size={15} />
                          ) : (
                            <Check size={15} />
                          )}
                          Approve & create ticket
                        </button>
                      </div>
                    </div>
                  )}
                  {current.receipt && (
                    <div className="receipt">
                      <CheckCircle2 size={23} />
                      <div>
                        <strong>
                          Escalation {current.receipt.ticket_id} created
                        </strong>
                        <p>
                          Confirmed execution receipt ·{" "}
                          {current.receipt.connector} ticket service
                        </p>
                      </div>
                      <button
                        className="icon-button"
                        aria-label="Copy ticket ID"
                        onClick={() => {
                          navigator.clipboard
                            .writeText(current.receipt!.ticket_id)
                            .then(() => {
                              setCopied(true);
                              setTimeout(() => setCopied(false), 1800);
                            });
                        }}
                      >
                        {copied ? <Check size={17} /> : <Copy size={17} />}
                      </button>
                    </div>
                  )}
                </>
              )}
            </section>
          </div>
          <footer className="page-footer">
            <span>
              SUPPORTOPS AI <span className="footer-dot">/</span>Built for
              accountable automation.
            </span>
            <span>
              <ShieldCheck size={12} />
              Read-only diagnostics · Human-approved actions
            </span>
          </footer>
        </div>
      </main>
      {modal && (
        <div className="overlay" onClick={() => !busy && setModal(false)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <span className="modal-icon">
                <Sparkles size={23} />
              </span>
              <button
                className="icon-button"
                onClick={() => setModal(false)}
                aria-label="Close dialog"
              >
                <X size={20} />
              </button>
            </div>
            <h2 id="new-title">Start an investigation</h2>
            <p>
              Describe the issue. We’ll gather evidence and prepare a clear next
              step.
            </p>
            <form onSubmit={submit}>
              <label>
                Customer account
                <select
                  value={account}
                  onChange={(e) => setAccount(e.target.value)}
                >
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} · {a.plan}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                What needs investigating?
                <textarea
                  autoFocus
                  required
                  minLength={10}
                  maxLength={6000}
                  rows={5}
                  placeholder="Include error codes, symptoms, and recent changes…"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                />
              </label>
              <div className="form-note">
                <LockKeyhole size={13} />
                Sensitive data is masked before processing. Never include
                credentials.
              </div>
              {error && (
                <div role="alert" className="form-error">
                  {error}
                </div>
              )}
              <button
                type="submit"
                className="button primary full"
                disabled={busy || !accounts.length}
              >
                {busy ? (
                  <LoaderCircle className="spin" size={16} />
                ) : (
                  <Sparkles size={16} />
                )}
                Investigate issue
                <ArrowRight size={16} />
              </button>
            </form>
          </section>
        </div>
      )}
      {source && (
        <div className="overlay" onClick={() => setSource(null)}>
          <section
            className="modal source-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="source-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <BookOpen size={23} />
              <button
                className="icon-button"
                aria-label="Close evidence"
                onClick={() => setSource(null)}
              >
                <X size={20} />
              </button>
            </div>
            <span className="eyebrow">
              {source.source === "tool"
                ? "DIAGNOSTIC SNAPSHOT"
                : "RUNBOOK SECTION"}
            </span>
            <h2 id="source-title">{source.title}</h2>
            <div className="source-meta">
              Version {source.version} · Retrieved {time(source.observed_at)}
            </div>
            <pre className="source-content">
              {source.content.startsWith("{")
                ? JSON.stringify(JSON.parse(source.content), null, 2)
                : source.content}
            </pre>
            <div className="source-id">
              <Fingerprint size={14} />
              {source.id}
            </div>
          </section>
        </div>
      )}
      {architecture && (
        <div className="overlay" onClick={() => setArchitecture(false)}>
          <section
            className="modal architecture-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="architecture-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <Layers3 size={24} />
              <button
                className="icon-button"
                aria-label="Close architecture"
                onClick={() => setArchitecture(false)}
              >
                <X size={20} />
              </button>
            </div>
            <span className="eyebrow">SYSTEM DESIGN</span>
            <h2 id="architecture-title">An auditable path to action.</h2>
            <p>
              The workflow checkpoints each stage. Authorization stays outside
              the model.
            </p>
            <ol className="architecture-steps">
              {[
                [
                  "01",
                  "Authenticate & scope",
                  "Server-side tenant and account permissions.",
                ],
                [
                  "02",
                  "Retrieve & diagnose",
                  "Version-filtered hybrid retrieval and bounded read-only tool calls.",
                ],
                [
                  "03",
                  "Synthesize & verify",
                  "Structured findings, exact source excerpts, and sensitive-output validation.",
                ],
                [
                  "04",
                  "Pause for approval",
                  "Durable LangGraph interrupt bound to the exact payload hash.",
                ],
                [
                  "05",
                  "Reauthorize & execute",
                  "Idempotent ticket creation and a recorded execution receipt.",
                ],
              ].map(([n, t, d]) => (
                <li key={n}>
                  <span>{n}</span>
                  <div>
                    <strong>{t}</strong>
                    <p>{d}</p>
                  </div>
                </li>
              ))}
            </ol>
            <p className="architecture-note">
              Demo mode uses a deterministic model and lexical hashing vectors.
              Live mode enables configured LLMs and embedding APIs. Operational
              connectors remain synthetic.
            </p>
            <a
              className="button secondary"
              href="/api/docs"
              target="_blank"
              rel="noreferrer"
            >
              Explore the API
              <ExternalLink size={14} />
            </a>
          </section>
        </div>
      )}
      {health?.auth_mode === "oidc" && !token && (
        <div className="overlay">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Authenticate"
          >
            <LockKeyhole size={25} />
            <h2>Connect your identity</h2>
            <p>
              Provide an access token from your configured identity provider.
              The token stays in memory.
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                setToken(tokenDraft);
                setTokenDraft("");
              }}
            >
              <label>
                Access token
                <input
                  type="password"
                  autoComplete="off"
                  required
                  value={tokenDraft}
                  onChange={(e) => setTokenDraft(e.target.value)}
                />
              </label>
              <button className="button primary full">Connect</button>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
const rootElement = document.getElementById("root");
if (rootElement)
  createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
