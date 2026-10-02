# Verification record — 2 October 2026

The delivered source is in `/Users/sandeepkumarboda/projects/supportops-ai`.

## Executed locally

- Python regression suite: **48 passed**, including a real PostgreSQL/pgvector integration test, OIDC JWT validation, cross-tenant authorization, prompt-injection and citation checks, worker recovery, stale approvals, duplicate execution, model routing and Guardrails AI validation. Six upstream Typer deprecation warnings remain.
- PostgreSQL: initial Alembic migration applied to a fresh disposable database; schema drift check passed; workflow checkpoint recovery and ticket execution passed against the migrated schema. The disposable database was removed afterward. The existing database server was left running.
- SQLite: migration upgrade/downgrade/upgrade covered by the test suite.
- Application evaluations: **12/12 curated development scenarios passed**. These use deterministic inference and synthetic data. They are not production accuracy measurements or semantic faithfulness scores.
- Ruff checks and formatting passed. React/TypeScript production build passed. npm audit reported zero vulnerabilities for the installed dependency tree.
- Browser interaction verified investigation submission, evidence inspection, trace inspection, exact payload review, approval, and persisted ticket receipts. Responsive layout was checked at 390px and 1440px widths.
- Ragas judge and faithfulness/factual-correctness metric initialization verified without provider calls.

## Verification limits

At initial delivery, no live LLM or embedding requests had been made because no provider credentials were configured. See the later live validation below. Live Ragas semantic scoring remains to be run against a held-out dataset. Operational connectors and tickets remain synthetic even in live inference mode.

The standalone Playwright runner could not launch Chromium under the desktop sandbox's macOS process restrictions; equivalent core interactions were exercised in the in-app browser. The repository includes three Playwright scenarios for CI or an ordinary local terminal. Docker is not installed in this environment, so the container build and Compose startup are provided but unverified locally. GitHub Actions jobs have been authored, not executed on a remote repository.

See `OPERATIONS.md` for production deployment requirements and `INTERVIEW_GUIDE.md` for defensible resume language and design trade-offs.

## Live-provider validation — 2 October 2026

Configured the user-supplied KodeKloud endpoint with gpt-6-luna for planning, native tool selection, synthesis and independent grounding verification. Credentials are in the ignored local `.env` file with owner-only permissions; this document contains no credentials. Live data/checkpoints use separate `var/live-*.db` files. Preview: http://127.0.0.1:8766/.

The Acme 403 workflow reached `needs_approval`: 5 successful model calls, 4 diagnostic tools, 9 evidence sources, 9,277 reported model tokens, 37.57 seconds machine time. Estimated inference cost was USD 0.0077128 using user-supplied rates (input 0.4/output 1.6 USD per million tokens), excluding the separate initial planning compatibility probe. This is one smoke test, not a quality benchmark. The approval is left pending for user testing.

Both text-embedding-3-small and text-embedding-3-large requests were denied by the provider with HTTP 403. The configured live preview explicitly uses local lexical-hash retrieval (`SUPPORTOPS_EMBEDDING_MODE=local`); it does not claim live semantic embeddings. Operational connectors remain synthetic. No alternate LLM model or provider is configured.

After adding independent embedding-mode configuration: 49 tests passed and 1 PostgreSQL test skipped; Ruff and production frontend build passed. Browser verified live labeling, cited findings, the pending approval and model usage/cost traces.

## Provider-policy error and polling repair — 2 October 2026

The user-reported Acme failure was reproduced from its saved checkpoint: the provider returned HTTP 400 with `Content blocked by Model Armor` and a sensitive-data finding. This was a provider policy rejection, not an availability failure. The original historical trace was retained and the case error reclassified with an operator audit event. The app now classifies known provider-policy responses as refusals, records only safe status/failure codes, avoids fallback and retry for those blocks, and shows a specific explanation. No provider safety setting was weakened.

The console no longer uses unconditional account/identity/case/trace intervals. Accounts and identity load on session changes; cases poll only while active; traces load only in the trace view and poll only while the selected case is active. Polling is sequential, pauses while hidden, backs off on errors, and aborts on cleanup. Failed transient cases resume polling when explicitly retried.

Verification: 51 backend tests passed, one PostgreSQL integration test skipped; 7 frontend regression tests passed; Ruff, TypeScript and production build passed; npm audit reported zero vulnerabilities. A separate live Acme support-entitlement lookup completed and rendered its cited Premium support answer in the browser. The original blocked request remains stopped. Reload existing browser tabs to load the updated frontend bundle.

## Meridian grounding and completion-budget repair — 2 October 2026

Meridian's live answer failed semantic grounding. A diagnostic reproduction identified missing context about the requested proposal and pre-execution state; a later remaining objection correctly identified that the sync-failure snapshot did not explicitly identify its service. The synthetic sync-job adapter now identifies its fixed `sync-service` scope in version `synthetic-v2`; no historical evidence was rewritten. A fresh case used the identical user request and new tool evidence.

The graph now checkpoints one correction attempt using the same evidence and redacted verifier feedback, then reruns full checks. It still stops on a second grounding rejection. Sensitive output and provider-policy refusals are never repaired through this path. Failed correction reports redacted verifier concerns as a model assessment instead of only an exception class.

Live correction also exposed the old hard-coded 1,400-token completion limit. The limit is now configurable (4,000 by default), with a matching reserved context budget and explicit truncation errors. The local live configuration uses a 45-second per-call timeout and 150-second overall deadline; it remains bounded. No model/provider safety check was disabled.

The fresh Meridian case `7da13ea5-025c-41b3-8658-e99b253d45d2` resumed its interrupted correction and passed independent verification. It is awaiting human approval; no ticket was created. Its answer qualifies incident causation and cites the service/region match. Original failed case `13f6e8b2-9434-49b6-964d-5ad3cb21b06d` remains as a historical record with a diagnostic explanation.

Validation: full backend run passed 55 tests with one PostgreSQL test skipped; two subsequently added token-budget tests passed in the focused 12-test routing/grounding suite. All 12 development evaluation scenarios passed. Ruff checks passed. The browser confirmed the new case reached approval.
