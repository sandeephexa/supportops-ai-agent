import { memo } from "react";
import { Fingerprint, LockKeyhole } from "lucide-react";
import type { Trace } from "./types";
import { formatTime } from "./format";

export const TraceView = memo(function TraceView({
  trace,
  mode,
}: {
  trace: Trace;
  mode?: string;
}) {
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
    <div className="trace-view">
      <div className="trace-stats">
        <div>
          <span>Machine time</span>
          <strong>{elapsed ? (elapsed / 1000).toFixed(2) + "s" : "—"}</strong>
        </div>
        <div>
          <span>Model tokens</span>
          <strong>
            {mode === "demo" ? "Demo model" : totalTokens.toLocaleString()}
          </strong>
        </div>
        <div>
          <span>Inference cost</span>
          <strong>
            {mode === "demo"
              ? "$0.00"
              : llmSpans.length > 0 && priced.length === llmSpans.length
                ? "$" + cost.toFixed(4)
                : "Unpriced"}
          </strong>
        </div>
      </div>
      <h3>
        Execution spans <span className="muted">{trace.spans.length}</span>
      </h3>
      <div className="span-list">
        {trace.spans.map((s) => (
          <div className="span-row" key={s.id}>
            <span
              className={s.status === "ok" ? "trace-dot" : "trace-dot error"}
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
                        (s.duration_ms / Math.max(elapsed, 1)) * 100,
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
          <time>{formatTime(a.created_at)}</time>
        </div>
      ))}
      <p className="trace-note">
        <LockKeyhole size={13} />
        Trace attributes exclude raw prompts, credentials, and customer
        payloads.
      </p>
    </div>
  );
});
