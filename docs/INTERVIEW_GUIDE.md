# Interview walkthrough

## Five-minute demonstration

1. Show an Acme 403 case and distinguish observed facts from the root-cause hypothesis.
2. Open a citation: the scopes came from the account-scoped diagnostic tool; required scopes came from the versioned runbook.
3. Open the trace: explain planning, bounded tool selection, retrieval expansion, synthesis, and verification.
4. Inspect the exact escalation payload, then approve it. Show the persisted ticket receipt.
5. Explain and demonstrate a restart while an approval is pending. Repeat approval and show there is still one ticket.

## Decisions to defend

**Why use an agent?** The next diagnostic depends on previous observations. The graph still owns execution limits and state transitions. Entitlement-only questions take a shorter path.

**Why is the model not the authorization layer?** Untrusted documents and tool results can influence generation. All tool requests cross a schema and permission barrier; the model cannot change the principal, role or tenant. Requesting a forbidden action does not execute it.

**How is state durable?** The case queue and LangGraph checkpoints serve different purposes: claim/retry state versus workflow continuation. A stable server-generated case ID ties them together. Approval state lives in the database and is checked independently of graph input.

**Exactly once?** Local ticket creation is atomic with the ledger. Distributed external writes require idempotency and reconciliation. Never generalize the simulator's transaction guarantees to a remote provider.

**What does faithfulness measure?** Citation existence and an exact quote prove provenance, not semantic entailment or current truth. Ragas faithfulness compares claims with evidence; factual correctness compares against a reference. An outdated source can yield a faithful but incorrect answer.

**How does retrieval evolve?** Start with a measurable lexical/vector baseline. Measure recall for error codes, paraphrases, product versions and restrictive permissions. Add a cross-encoder or approximate index only after an ablation establishes value.

**How do you route models?** Use task complexity and observed failures. Compare a routed policy with a strong-model baseline on the same evaluation set. Count all attempts, judge calls and failures when estimating costs.

**What is the failure boundary?** Explain a provider timeout, a schema failure, a missing source, a revoked approval and a worker crash. Show the matching tests rather than presenting a list of libraries.

**What remains before enterprise adoption?** Real integrations, OIDC PKCE UX, deeper PII/content coverage, reviewed egress policies, immutable audit storage, retention, backup restoration, distributed worker fencing and a held-out live evaluation dataset.

## Experiments to extend this project

- Compare lexical-only, dense-only, fused retrieval and cross-encoder reranking under the same authorized corpus.
- Compare one strong model with low-cost routing; report quality, abstention, p95 latency and cost per successful case.
- Add corpus poisoning and tool-result injection examples that pass the heuristic detector; demonstrate backend tool denial.
- Introduce a ticket API simulator that commits then times out; implement reconciliation against its idempotency lookup endpoint.
- Test permission revocation between approval and execution, including the effect on cached evidence.
- Add scenario-family-separated hold-out cases and human judge calibration. Do not call paraphrases of development fixtures a production benchmark.

## Resume language

“Built an evidence-backed support investigation application using FastAPI, React, LangGraph and hybrid retrieval, with tenant-scoped tools, durable human approval, idempotent simulated ticket execution, automated security/recovery tests, evaluation reports and OpenTelemetry tracing.”

Only add numerical quality, latency, cost or time-savings claims after measuring them in a named environment. Describe synthetic integrations and prototype status honestly.
