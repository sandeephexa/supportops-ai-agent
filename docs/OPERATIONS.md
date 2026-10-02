# Operations and deployment

## Deployment profiles

Local development: SQLite, a background worker, built React assets, loopback-only bind, synthetic users and data. Start using `scripts/run-local.sh`.

Container deployment: PostgreSQL/pgvector, Alembic startup migration, a non-root application container, optional Phoenix. Use `docker compose up --build`. Docker must be installed separately. The project does not install Docker or modify system services.

Controlled enterprise deployment requires: approved model/embedding endpoints, a managed secret store, TLS ingress, OIDC, provisioned memberships, network egress restrictions, non-demo connectors, database backups/PITR, encrypted storage, retention/deletion policies, and explicit incident ownership. These controls are deployment responsibilities, not claims made by the local demo.

## Startup and migration

Do not run multiple application instances racing to perform schema migrations in production. Run Alembic as a release job, then start API/worker replicas. The provided single-instance Compose command runs migrations before Uvicorn.

Back up before migration. Test upgrades against a restored copy. Initial migration downgrade drops tables and is only exercised on a disposable test database. Do not use downgrade as a production data-recovery strategy.

Local backup: stop the app and copy both `var/supportops.db` and `var/checkpoints.db` using SQLite's backup API, or include their WAL state correctly. PostgreSQL: back up the application and checkpoint tables in the same database snapshot. Restore into an isolated environment and verify pending approval recovery before changing traffic.

## Failure procedures

- **Provider outage:** inspect model route spans and circuit states; bounded fallback is automatic when configured. If all approved routes fail, the case stops safely. Retry after recovery. No alternate provider is used after a refusal.
- **Malformed output or failed grounding:** case moves to manual review; inspect redacted evidence and validate the schema/model configuration before retrying. Retry limit is four processing attempts per case.
- **Worker crash:** wait for lease expiry; a surviving worker resumes the checkpoint. A crash at an approval pause preserves the pending draft. Never manually mark a proposal as executed.
- **Expired approval:** start a fresh investigation to refresh evidence and issue a new payload hash. An expired approval cannot authorize a new ticket.
- **Revoked access:** reads and execution deny access even if a prior checkpoint or approval exists. Re-provision only through authorized identity administration.
- **Duplicate approval:** an identical decision is idempotent. A conflicting decision is rejected. The ticket action uses a deterministic idempotency key.
- **Database unavailable:** admission and writes fail; do not bypass audit persistence. Restore database service and then inspect interrupted cases.
- **Real remote write timeout:** before integrating a remote ticket provider, implement lookup by idempotency key and reconciliation. The synthetic transaction currently avoids this distributed ambiguity.

## Observability

Set `SUPPORTOPS_OTLP_ENDPOINT` to a trusted OTLP/HTTP `/v1/traces` endpoint. For local Phoenix in Compose use `http://phoenix:6006/v1/traces`. Application telemetry deliberately excludes prompt bodies, tool content, exception messages and keys. Do not enable third-party automatic prompt logging without a reviewed redaction/retention configuration.

Track queue age, machine processing time, error rate, model fallback rate, tool failures, approval wait time, duplicate attempts, and total cost including failures. Nested span durations must not be summed as request latency. The UI uses investigation root spans for machine time and counts tokens from model spans.

The initial admission limit is 20 cases per tenant per minute. PostgreSQL admission takes an advisory transaction lock; SQLite's demo path is not a distributed rate limiter. Add authenticated edge quotas and concurrent-job limits for a public deployment.

No SLO is claimed from demo measurements. Establish workload, concurrency, dataset, providers, model versions, and region before measuring p50/p95 and setting targets. The synchronous polling worker favors determinism over high throughput.

## Data lifecycle

The reference system retains local cases/checkpoints/audit records until an operator removes the development database. A production retention job must expire approved case/evidence data and checkpoints together while preserving the legally required audit subset. PII patterns currently cover email addresses, phone-like strings and common secret formats; names and arbitrary identifiers are not comprehensively detected. Redaction is irreversible in this reference implementation; no reidentification map is stored.

Protect the database and its backups because redacted operational data may still be sensitive. Application-level tenant filtering is not a replacement for a separate tenant-database or PostgreSQL RLS design where stronger isolation is required.

## CI

GitHub Actions defines three jobs: backend/security/evals plus PostgreSQL integration; browser workflows on Chromium; and container startup. Credentials used by these jobs are ephemeral test values. No live provider credentials are required. Add paid-provider evaluation as a protected workflow with explicit budgets, not on arbitrary pull requests.

Run `pytest`, `scripts/evaluate.py`, and `npm run build` locally. Browser and PostgreSQL tests require OS process privileges; some desktop sandboxes prohibit Chromium's Mach ports and PostgreSQL shared memory. In that case use the app browser for manual UI verification and execute the full test suite in CI or a normal local terminal. Do not interpret a sandbox launch failure as a passing test.
