export type Account = {
  id: string;
  name: string;
  plan: string;
  product_version: string;
};
export type Claim = { text: string; evidence_ids: string[]; quote: string };
export type Evidence = {
  id: string;
  title: string;
  content: string;
  source: string;
  version: string;
  observed_at: number;
  score: number;
};
export type Result = {
  summary: string;
  confirmed_facts: Claim[];
  hypotheses: Claim[];
  recommended_steps: string[];
  unresolved_questions: string[];
  needs_escalation: boolean;
};
export type Case = {
  id: string;
  account_id: string;
  question: string;
  status: string;
  phase: string;
  created_at: number;
  updated_at: number;
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
export type Span = {
  id: string;
  name: string;
  duration_ms: number;
  status: string;
  attributes: Record<string, unknown>;
};
export type Audit = {
  id: string;
  action: string;
  actor: string;
  created_at: number;
};
export type Trace = { spans: Span[]; audit: Audit[] };

export type CaseSummary = Pick<
  Case,
  | "id"
  | "account_id"
  | "question"
  | "status"
  | "phase"
  | "created_at"
  | "updated_at"
>;
