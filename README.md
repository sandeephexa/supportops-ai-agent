# SupportOps AI

An enterprise support investigation system with evidence-backed findings, scoped diagnostic tools, durable LangGraph workflows, and human-approved escalation tickets.

**Run it without an API key.** The default environment uses a deterministic demo model, lexical hashing vectors, and synthetic enterprise records. Live mode enables configured LLM and embedding APIs. Operational data and ticket creation remain explicitly simulated in both modes.

## Quick start

Prerequisites: Python 3.12, `uv`, Node.js 22+, and npm. Docker is optional.

```bash
cd /Users/sandeepkumarboda/projects/supportops-ai
./scripts/run-local.sh
```

Open http://127.0.0.1:8000. API documentation: http://127.0.0.1:8000/api/docs.

Use `PORT=8765 ./scripts/run-local.sh` if 8000 is occupied. Dependencies and download caches stay inside this project. Dependency versions are locked in `uv.lock` and `frontend/package-lock.json`.

The UI is served by FastAPI after building. For frontend development, run `make dev` and, in a second terminal, `cd frontend && npm run dev`; Vite proxies `/api` to port 8000.

## Demonstration

1. Click **New investigation** or select one of the suggested cases on an empty workspace.
2. Ask: “Acme sync jobs return 403 after credential rotation. Investigate, verify support entitlement, and prepare escalation.”
3. Inspect confirmed facts, working hypotheses, and the exact cited runbook/tool snapshots.
4. Open **Execution trace** to inspect node timing, routing, guardrails, and audit events.
5. Review the exact ticket payload, then approve it. The application resumes the persisted graph, rechecks permission, and creates one synthetic ticket.
6. Refresh or restart the application: investigations, pending approvals, and receipts persist.

Other accounts: **Atlas Logistics** demonstrates HTTP 429 / rate limiting; **Meridian Labs** demonstrates HTTP 503 / a regional incident. A fourth account belongs to a different tenant and is deliberately inaccessible to the default identity.

The desktop profile control switches between an engineer and a restricted reviewer. This is a demo-only identity switch, not production authentication.

## What is implemented

- **LLM routing:** typed planning and synthesis, native tool calling through LangChain, separate low-cost/complexity routes, transient retries, a 30-second provider circuit breaker, bounded schema repair, and an independently configured compatible fallback endpoint. Refusals never trigger fallback.
- **Agent orchestration:** an explicit LangGraph state machine, SQLite/PostgreSQL checkpoints, durable approval interrupts, bounded diagnostic/retrieval loops, worker leases, and restart recovery.
- **Tool execution:** four schema-constrained diagnostic tools. The gateway reauthorizes every account lookup and rejects unexpected arguments or tools. Tenant and role data never come from model output.
- **Context engineering:** heading-based child chunks, parent-section expansion, metadata/version filters, lexical/vector reciprocal-rank fusion, deterministic reranking, error-code query expansion, context-window budgets, and extractive compression that prioritizes constraints/warnings.
- **Safety:** input/output schemas, secret/email/phone masking, direct-injection screening, poisoned-document quarantine, exact citation provenance checks, optional Guardrails AI validation, and an independent semantic verifier in live mode.
- **Action security:** the approval references an exact server-generated payload hash and expiry. Approval and execution both recheck authorization. Ticket creation and the action ledger are atomic in the local simulator and protected by a unique idempotency key.
- **Evaluation:** twelve curated application scenarios, security/recovery tests, machine-readable reports, and an optional Ragas faithfulness/factual-correctness judge. Reports distinguish citation provenance from semantic faithfulness.
- **Observability:** redacted local spans in the UI and OpenTelemetry export to Phoenix-compatible OTLP/HTTP endpoints. Model usage, attempts, route, schema/prompt/graph versions, tools, timing, and security audit events are recorded. Raw prompts and credentials are excluded from application telemetry.
- **Deployment:** a multi-stage, non-root Docker image; PostgreSQL + pgvector Compose setup; optional Phoenix; Alembic migrations; and CI jobs for backend, PostgreSQL, browser, and container smoke tests.

## Tests and evaluation

```bash
make setup
make lint
make test
make eval
```

Semantic evaluation is explicitly opt-in and incurs API charges:

```bash
UV_CACHE_DIR=./var/uv-cache uv sync --all-extras
.venv/bin/python scripts/evaluate.py --live --ragas
```

The suite in `evals/cases.jsonl` is a development smoke suite, not a held-out benchmark. Its results do not establish production accuracy. Add independently labeled cases, separate scenario families between tuning and hold-out datasets, and calibrate judges before making quality claims.

Browser tests require a running built application:

```bash
cd frontend
PLAYWRIGHT_BROWSERS_PATH=../var/playwright npx playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=../var/playwright E2E_BASE_URL=http://127.0.0.1:8000 npm run test:e2e
```

A bounded load probe creates synthetic cases without approving them:

```bash
.venv/bin/python scripts/load_test.py --url http://127.0.0.1:8000 --concurrency 5
```

## Live-model configuration

Copy `.env.example` to `.env`, then configure:

```dotenv
SUPPORTOPS_MODE=live
SUPPORTOPS_API_KEY=your-key
SUPPORTOPS_BASE_URL=https://api.openai.com/v1
SUPPORTOPS_SMALL_MODEL=gpt-4.1-mini
SUPPORTOPS_REASONING_MODEL=gpt-4.1
SUPPORTOPS_EMBEDDING_MODEL=text-embedding-3-small
SUPPORTOPS_ENABLE_GUARDRAILS=true
```

Model names are configurable reference choices, not a claim that they are the latest or available to every account. The provider must support the JSON-schema and native tool-calling APIs used by `langchain-openai`. The embedding endpoint must support 256-dimensional embeddings. No credentials are bundled, and no live inference is invoked by default.

A fallback uses `SUPPORTOPS_FALLBACK_MODEL`, `SUPPORTOPS_FALLBACK_BASE_URL`, and `SUPPORTOPS_FALLBACK_API_KEY`. Configure only approved endpoints with equivalent data-handling permissions. The application cannot verify a provider's contractual data residency. `SUPPORTOPS_MODEL_CONTEXT_WINDOW` and `SUPPORTOPS_FALLBACK_CONTEXT_WINDOW` must reflect the deployed models' limits; the context packer uses the smaller configured window.

Index embeddings are versioned. Changing demo/live mode or the embedding model requires re-embedding; startup seeds the sample corpus for the new embedding version. Never compare vectors from different embedding models.

By default live costs are **unpriced**, not zero. Set `SUPPORTOPS_MODEL_PRICES` to a JSON object keyed by model name, with `input` and `output` USD-per-million-token rates from your contract. Each primary and fallback model is priced independently. Missing model prices or missing usage remain explicitly unknown; the UI does not present a partial cost as a complete total.

## PostgreSQL and Phoenix

```bash
docker compose up --build
```

This binds the app only to `127.0.0.1:8000`. PostgreSQL is internal to the Compose network. Demo credentials are for local use only.

For Phoenix:

```bash
SUPPORTOPS_OTLP_ENDPOINT=http://phoenix:6006/v1/traces \
  docker compose --profile observability up --build
```

Open http://127.0.0.1:6006. Guardrails' own metrics collection and raw-content tracing are explicitly disabled; application-owned sanitized spans are used instead. The development Compose tags are intentionally convenient; pin image digests in a controlled deployment.

The container runs `alembic upgrade head` before startup. Local demo mode can auto-create the initial schema. For a new manually managed database, run `make migrate` and set `SUPPORTOPS_AUTO_CREATE_SCHEMA=false`. If you already created a local demo database before enabling Alembic, back it up and verify its schema before `alembic stamp head`; do not stamp an arbitrary production database.

## Authentication and boundaries

`SUPPORTOPS_AUTH_MODE=demo` accepts `X-Demo-User` from a fixed synthetic user store. **Keep demo authentication on loopback/private development environments.**

For externally accessible deployments, use `SUPPORTOPS_AUTH_MODE=oidc` with `SUPPORTOPS_OIDC_ISSUER`, `SUPPORTOPS_OIDC_AUDIENCE`, and `SUPPORTOPS_OIDC_JWKS_URL`. JWTs are restricted to RS256 and checked for expiry, issuer, audience, issued-at and subject. Subjects map to server-side users; token-supplied tenant/role claims are ignored. The frontend has an in-memory access-token entry flow; it does not yet implement a complete OIDC authorization-code/PKCE login UX.

Provision authorized subjects via `scripts/admin.py provision-user`. This is an operator CLI, never an API endpoint. Restrict access to its database credentials.

## Repository map

- `backend/supportops/api.py`: HTTP/auth boundaries and approval API.
- `workflow.py`, `worker.py`: durable orchestration, queue claiming, resume and failure handling.
- `models.py`: structured output, tool selection, routing and fallbacks.
- `retrieval.py`: indexing, hybrid retrieval and context packing.
- `security.py`, `guardrails.py`, `actions.py`: authorization, masking, verification and action execution.
- `db.py`, `migrations/`: persistence and schema changes.
- `frontend/src/`: responsive investigation console.
- `data/runbooks/`, `seed.py`: explicitly synthetic corpus and diagnostics.
- `evals/`, `backend/tests/`, `frontend/e2e/`: evaluation and regression coverage.
- `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/INTERVIEW_GUIDE.md`: system decisions, operations, and interview walkthrough.

## Scope and honest limits

This is a working production-oriented portfolio implementation, not a certified production service. The data connectors and tickets are simulated. The demo model is deterministic; its speed/quality says nothing about a live LLM. SQLite is a local convenience and uses in-process search; PostgreSQL uses database full-text and vector queries. Reranking is deterministic lexical overlap, not a trained cross-encoder. PII detection covers known patterns, not every name or identifier. Prompt-injection detection is heuristic; authorization and restricted tools provide the enforceable boundary.

The workflow handles one investigation per case; it does not implement an unlimited multi-turn conversation memory. The application has no arbitrary SQL, shell execution, autonomous credential changes, or generic URL-fetch tools. Before real enterprise adoption, integrate real connectors, implement the external-write reconciliation contract, strengthen content/PII coverage, validate live model behavior, and complete the operational controls described in the operations guide.

## Delivery verification

See [the verification record](docs/VERIFICATION.md) for executed checks and their limits: 48 tests passed, PostgreSQL migrations and workflow recovery verified, 12/12 development evaluation scenarios passed, and the frontend production build passed.

### LLM-only provider access

If your provider allows chat models but denies embedding requests, set `SUPPORTOPS_EMBEDDING_MODE=local` alongside `SUPPORTOPS_MODE=live`. Planning, native tool selection, synthesis and grounding verification still call the live model. Retrieval uses the local lexical-hashing baseline, not semantic API embeddings; the UI and health endpoint label this explicitly. The default `auto` mode requires live embeddings when live inference is enabled and does not silently fall back.

### Investigation refresh and provider blocks

The console loads account and identity data once per session/identity change. It polls cases only while a case is queued or running, and fetches traces only when the Execution trace tab is open. Trace polling stops at a terminal or approval state. Requests do not overlap, hidden tabs pause, and network errors use bounded backoff. Refresh the page to discover changes made in a different session when this session is idle.

A provider-side policy rejection (including Model Armor) is shown as a provider safety block, not a model outage. The app does not retry or route these requests to a fallback model. Review the submitted data and provider policy; configuring a different route is not a remedy for a safety block. Provider response bodies and sensitive findings are excluded from stored traces; controlled failure codes and HTTP status are retained.

Frontend polling regressions: `cd frontend && npm test`.

### Grounding correction

Live investigations can revise an unsupported answer once using the original evidence and verifier feedback, then must pass citation, safety and semantic checks again. The verifier receives the original request and the trusted pre-execution workflow context, so a request to prepare a ticket is distinguished from claiming one was created. Failed correction stops with a specific evidence-verification message and no escalation draft. Safety/provider refusals are not routed through this repair path.

Live completion budget is configurable through `SUPPORTOPS_MODEL_OUTPUT_TOKENS` (default 4000). The context packer reserves that budget before including evidence. `SUPPORTOPS_MODEL_CALL_TIMEOUT_SECONDS` defaults to 45; each call also respects the investigation's remaining deadline. A truncated response is not accepted as a valid answer. The local KodeKloud profile uses `SUPPORTOPS_REQUEST_DEADLINE_SECONDS=150` to accommodate verification and one correction.
