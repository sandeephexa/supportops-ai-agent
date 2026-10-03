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

## Local MiniLM semantic embeddings — 2 October 2026

Enabled pinned `sentence-transformers/all-MiniLM-L6-v2` at revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, CPU inference, cached safetensors, no remote model code, 384 native dimensions, and normalized overlapping-window pooling for long input. The live deployment is configured to load cached weights offline. Its KodeKloud LLM configuration is unchanged.

Reindexed bundled runbooks with a model/revision/encoding-policy fingerprint. Partial-index recovery checks each file. Removed the keyword-overlap requirement from semantic candidates and added cosine-aware reranking. Database migration permits variable vector dimensions with exact embedding-version filtering; PostgreSQL migration, schema drift check, mixed 256/384-vector search and tenant isolation were exercised in a disposable database that was removed afterward.

Validation: 62 backend tests passed (including real offline MiniLM and PostgreSQL), 7 frontend tests passed, production frontend build and Ruff passed, and all 12 development evaluation scenarios passed with local embeddings. Three paraphrase checks retrieved the expected rate-limit, credential-remediation and incident runbooks first. These checks are development evidence, not a held-out retrieval benchmark.

Live case `6ad058e2-ba35-4891-99bc-42cd166eeb31` returned verified Atlas rate-limit findings and asked for missing operational details; it had no error. Its retrieval spans record `semantic=true`, `embedding_dimensions=384` and `st:c6c1836bed62a7f2:384:window-pool-v1`. The console shows MiniLM semantic retrieval. Existing investigation snapshots remain unchanged; SQLite backups were saved in ignored `var/` before reindexing.

The optional MiniLM Docker build configuration is provided but Docker execution remains unverified locally. Custom tenant documents must be re-ingested after changing encoder versions. Inference embeddings are local; the live LLM still receives selected evidence through its configured API.

## Production-readiness refactor — 3 October 2026

- Backend authorization now enforces read-only viewers on creation/retry as well as approvals. Whitespace-only questions, non-boolean approvals and invalid hashes are rejected. Request limits and configuration budgets are validated. Production configuration rejects demo authentication/seeding, automatic schema creation, SQLite, untrusted hosts and non-HTTPS identity/model endpoints.
- Case summaries select only list fields at the database level. The console fetches full selected-case data on selection or timestamp changes. With the current 11-case dataset, the legacy full-list response measured 55,176 bytes and the summary response 4,241 bytes, a 92.3% reduction before compression. This measures response size, not an LLM speedup or production load benchmark.
- SQLite retrieval tokenizes each document once for lexical scoring and selects the top 30 with a heap. Reingestion uses a set for chunk membership and escapes SQL prefix wildcards. Duplicate context-budget code was consolidated.
- HTTP failures are controlled, identity network outages return 503, and optional trace persistence failures no longer override execution results or original errors. Audit/checkpoint/action persistence remains mandatory. Startup resources are released even on initialization failure. Readiness checks the application DB and embedded worker; hashed assets are cacheable while API/HTML are not.
- Frontend entry point, API client, shared types, time formatting and memoized trace view are separated. HTTP calls have 15-second timeouts, session-bound cancellation, safe evidence JSON formatting and clipboard failure handling. Expired tokens return to authentication. Mutations are not automatically retried. Server roles control write buttons. TypeScript now checks unused declarations; CI checks frontend formatting and types. No application console/debug logging was found to remove.
- Environment variants are excluded from Docker context. The configured live keys were not found in tracked files or the browser bundle; `.env` remained mode 0600. This is a targeted check, not a comprehensive Git-history or secret-pattern audit.

Validation: all 73 backend tests passed with 94% statement coverage, including real offline MiniLM and PostgreSQL workflow/checkpoint integration in a newly created disposable database (removed afterward). All 13 frontend tests passed, including role restrictions, unchanged-summary fetch behavior, timeouts and stale-response cancellation. Ruff, Prettier, TypeScript, production build, YAML parsing and Git whitespace checks passed. All 12 development evaluation scenarios passed; these do not measure held-out production accuracy. An initial backend run raced a concurrent Vite rebuild; the sequential full verification above passed.

Dependency checks found no known vulnerabilities in 155 Python runtime dependencies (Guardrails and MiniLM extras included, current platform) or the npm audit. Audit results are point-in-time advisory checks, not security certification. Raw reports are in ignored `var/`.

The local live app was restarted on port 8766. HTTP smoke checks confirmed readiness 200, viewer creation 403, unknown-host rejection 400, summary field bounds and asset/API cache policy. The browser rendered an existing investigation's findings, extracted trace view and diagnostic evidence dialog. No new live LLM call or ticket creation was required for this refactor. Docker execution and an external OIDC deployment were not exercised; browser verification used the in-app browser rather than a new standalone Playwright run. The current local instance intentionally remains in development/demo-auth mode with live inference and synthetic connectors.

## Atlas citation provenance repair — 2 October 2026

The saved checkpoint for failed case `204c4eef-fe60-4c44-aa6d-d0a820356981` showed that the corrected draft joined tool and runbook excerpts with semicolons into a single quote. Those individual excerpts existed, but the combined quote was not a contiguous excerpt of any cited source. The deterministic provenance rejection was correct. Earlier semantic feedback also objected to proposal status because the verifier's trusted workflow contract did not explicitly describe proposal preparation.

The claim schema and generation instructions now require a single contiguous supporting excerpt from one cited source, including multi-source inferences. Provenance feedback identifies all affected claim field locations so the existing single correction attempt can address them. Generation and semantic verification share the explicit pre-proposal workflow contract. Invalid quotes still fail closed; the independent semantic check remains required. Citation failures are now labeled as citation validation rather than a model assessment, without implying that the user's question was at fault.

Validation: 61 backend tests passed; three optional real-model/PostgreSQL tests were skipped in this run. Two new regression tests cover joined-source quotes, precise feedback, correction, and semantic verification before completion. The focused six-test repair suite and Ruff passed after the final error-message edit.

Restarted the local app and submitted the user's exact Atlas question as fresh case `1f9baec7-39b6-485b-bf7c-3f34546b3f34`. It passed provenance, Guardrails AI and semantic verification on the first draft (`verified=true`, zero revisions), returned cited findings, and reached `needs_information` with no error. It reports 23 HTTP 429 failures, no active regional incident and standard support; it asks for missing quota/recovery and coverage details. No escalation draft or ticket was created. MiniLM retrieval remains active. The original failed case is preserved as historical evidence. This successful live run does not guarantee that every future model output will satisfy verification.
