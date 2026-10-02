import time
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from opentelemetry import trace as otel_trace
from sqlalchemy import func, inspect, select, update

from supportops.config import ROOT, Settings
from supportops.db import Account, AuditEvent, Case, Database, TraceEvent
from supportops.guardrails import SafetyViolation, validate_input
from supportops.models import ModelGateway
from supportops.retrieval import Retriever
from supportops.schemas import ApprovalRequest, CreateCase
from supportops.security import Principal, authorize_account, authorize_case, current_user
from supportops.seed import seed
from supportops.telemetry import Telemetry
from supportops.tools import ToolGateway
from supportops.worker import Worker
from supportops.workflow import Workflow


def serialize(record):
    data = {column.key: getattr(record, column.key) for column in inspect(record).mapper.column_attrs}
    if isinstance(record, Case):
        data["retryable"] = (
            record.status == "failed"
            and record.attempts < 4
            and not (record.error or "").startswith(
                ("Provider safety block:", "Provider request rejected:", "Evidence verification failed:")
            )
        )
    return data


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        db = Database(settings.database_url)
        db.initialize(settings.auto_create_schema)
        telemetry = Telemetry(db, settings)
        retriever = Retriever(db, settings, telemetry)
        # Seeded operational connectors remain synthetic in both model modes.
        seed(db, retriever)
        with ExitStack() as stack:
            if settings.checkpoint_url.startswith("sqlite"):
                path = settings.checkpoint_url.split("///", 1)[-1]
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                checkpointer = stack.enter_context(SqliteSaver.from_conn_string(path))
            else:
                checkpointer = stack.enter_context(PostgresSaver.from_conn_string(settings.checkpoint_url))
            checkpointer.setup()
            models, tools = ModelGateway(settings, telemetry), ToolGateway(db, telemetry)
            workflow = Workflow(db, settings, models, retriever, tools, telemetry, checkpointer)
            worker = Worker(db, workflow, settings)
            for name, value in {
                "settings": settings,
                "db": db,
                "telemetry": telemetry,
                "retriever": retriever,
                "models": models,
                "tools": tools,
                "workflow": workflow,
                "worker": worker,
            }.items():
                setattr(app.state, name, value)
            if settings.auth_mode == "oidc":
                app.state.jwks = jwt.PyJWKClient(settings.oidc_jwks_url, cache_keys=True, lifespan=300)
            if settings.worker_enabled:
                worker.start()
            yield
            worker.stop()
            telemetry.shutdown()
        db.engine.dispose()

    app = FastAPI(
        title="SupportOps AI",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def boundaries(request, call_next):
        if request.method in ["POST", "PUT", "PATCH"]:
            # Bound the streamed body, including requests without Content-Length.
            size = 0
            body = bytearray()
            async for chunk in request.stream():
                size += len(chunk)
                if size > 32768:
                    return JSONResponse({"detail": "Request body too large"}, status_code=413)
                body.extend(chunk)
            request._body = bytes(body)
        with app.state.telemetry.tracer.start_as_current_span(
            "http.request", record_exception=False, set_status_on_exception=False
        ) as http_span:
            http_span.set_attribute("http.request.method", request.method)
            response = await call_next(request)
            route = request.scope.get("route")
            http_span.set_attribute("http.route", getattr(route, "path", "unmatched"))
            http_span.set_attribute("http.response.status_code", response.status_code)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        if not request.url.path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
            )
        return response

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "mode": settings.mode,
            "auth_mode": settings.auth_mode,
            "connectors": "synthetic",
            "retrieval": "provider_embeddings"
            if settings.mode == "live" and settings.embedding_mode != "local"
            else "local_lexical_hash",
            "version": "0.1.0",
        }

    @app.get("/api/me")
    def me(principal: Principal = Depends(current_user)):
        return {**principal.__dict__, "mode": settings.mode, "auth_mode": settings.auth_mode}

    @app.get("/api/accounts")
    def accounts(principal: Principal = Depends(current_user)):
        with app.state.db.session() as session:
            records = session.scalars(
                select(Account).where(
                    Account.tenant_id == principal.tenant_id, Account.id.in_(principal.account_ids)
                )
            ).all()
            return [
                {"id": a.id, "name": a.name, "plan": a.plan, "product_version": a.product_version}
                for a in records
            ]

    @app.post("/api/cases", status_code=202)
    def create_case(body: CreateCase, principal: Principal = Depends(current_user)):
        account = authorize_account(app.state.db, principal, body.account_id)
        try:
            question, events = validate_input(body.question)
        except SafetyViolation as exc:
            raise HTTPException(422, str(exc)) from None
        with app.state.db.session() as session:
            # Transaction-scoped tenant lock makes admission quotas atomic on PostgreSQL.
            if app.state.db.is_postgres:
                from sqlalchemy import text

                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:tenant))"), {"tenant": principal.tenant_id}
                )
            recent = session.scalar(
                select(func.count())
                .select_from(Case)
                .where(Case.tenant_id == principal.tenant_id, Case.created_at > time.time() - 60)
            )
            if recent >= 20:
                raise HTTPException(429, "Tenant admission limit reached; try again shortly")
            case = Case(
                tenant_id=principal.tenant_id,
                account_id=account.id,
                user_id=principal.id,
                question=question,
                guardrail_events=events,
            )
            session.add(case)
            session.flush()
            otel_trace.get_current_span().set_attribute("supportops.case_id", case.id)
            result = serialize(case)
            session.add(
                AuditEvent(
                    tenant_id=principal.tenant_id,
                    case_id=case.id,
                    actor=principal.id,
                    action="case.created",
                    details={"redaction_count": len(events)},
                )
            )
        return result

    @app.get("/api/cases")
    def cases(principal: Principal = Depends(current_user)):
        with app.state.db.session() as session:
            records = session.scalars(
                select(Case)
                .where(Case.tenant_id == principal.tenant_id, Case.account_id.in_(principal.account_ids))
                .order_by(Case.created_at.desc())
                .limit(100)
            ).all()
            return [serialize(c) for c in records]

    @app.get("/api/cases/{case_id}")
    def case_detail(case_id: str, principal: Principal = Depends(current_user)):
        return serialize(authorize_case(app.state.db, principal, case_id))

    @app.get("/api/cases/{case_id}/trace")
    def trace(case_id: str, principal: Principal = Depends(current_user)):
        authorize_case(app.state.db, principal, case_id)
        with app.state.db.session() as session:
            spans = session.scalars(
                select(TraceEvent).where(TraceEvent.case_id == case_id).order_by(TraceEvent.created_at)
            ).all()
            audits = session.scalars(
                select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.created_at)
            ).all()
            return {"spans": [serialize(s) for s in spans], "audit": [serialize(a) for a in audits]}

    @app.post("/api/cases/{case_id}/approval", status_code=202)
    def approve(case_id: str, body: ApprovalRequest, principal: Principal = Depends(current_user)):
        case = authorize_case(app.state.db, principal, case_id)
        if principal.role != "engineer":
            raise HTTPException(403, "An engineer must approve escalations")
        if not case.draft or case.draft["payload_hash"] != body.payload_hash:
            raise HTTPException(409, "Draft changed; review it again")
        if case.draft["expires_at"] < time.time():
            raise HTTPException(409, "Draft expired; start a fresh investigation")
        if case.approval:
            if (
                case.approval["approved"] == body.approved
                and case.approval["payload_hash"] == body.payload_hash
            ):
                return serialize(case)
            raise HTTPException(409, "A different decision is already recorded")
        decision = {
            "actor": principal.id,
            "approved": body.approved,
            "payload_hash": body.payload_hash,
            "approved_at": time.time(),
            "expires_at": case.draft["expires_at"],
        }
        with app.state.db.session() as session:
            result = session.execute(
                update(Case)
                .where(Case.id == case_id, Case.status == "needs_approval")
                .values(approval=decision, status="queued", updated_at=time.time())
            )
            if result.rowcount != 1:
                raise HTTPException(409, "Case is not awaiting approval")
            session.add(
                AuditEvent(
                    tenant_id=principal.tenant_id,
                    case_id=case_id,
                    actor=principal.id,
                    action="escalation.approved" if body.approved else "escalation.declined",
                    details={"payload_hash": body.payload_hash},
                )
            )
        return serialize(authorize_case(app.state.db, principal, case_id))

    @app.post("/api/cases/{case_id}/retry", status_code=202)
    def retry(case_id: str, principal: Principal = Depends(current_user)):
        case = authorize_case(app.state.db, principal, case_id)
        if not serialize(case)["retryable"]:
            raise HTTPException(409, "Case cannot be retried; start a fresh investigation")
        if case.approval and case.approval["expires_at"] < time.time():
            raise HTTPException(409, "Approval expired; start a fresh investigation")
        with app.state.db.session() as session:
            updated = session.execute(
                update(Case)
                .where(Case.id == case_id, Case.status == "failed")
                .values(status="queued", error=None, updated_at=time.time())
            )
            if updated.rowcount != 1:
                raise HTTPException(409, "Case state changed")
        return {"id": case_id, "status": "queued"}

    frontend = ROOT / "frontend" / "dist"
    if frontend.exists():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(frontend / "index.html")
    else:

        @app.get("/")
        def index():
            return {
                "message": "Run the frontend on http://127.0.0.1:5173 or build it with npm run build",
                "docs": "/api/docs",
            }

    return app


app = create_app()
