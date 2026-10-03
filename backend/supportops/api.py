import time
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from opentelemetry import trace as otel_trace
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import OperationalError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from supportops.config import ROOT, Settings
from supportops.db import Account, AuditEvent, Case, Database, TraceEvent
from supportops.guardrails import SafetyViolation, validate_input
from supportops.models import ModelGateway
from supportops.retrieval import Retriever
from supportops.schemas import ApprovalRequest, CreateCase
from supportops.security import Principal, authorize_account, authorize_case, current_user, require_engineer
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
        with ExitStack() as stack:
            db = Database(settings.database_url)
            stack.callback(db.engine.dispose)
            db.initialize(settings.auto_create_schema)
            telemetry = Telemetry(db, settings)
            stack.callback(telemetry.shutdown)
            retriever = Retriever(db, settings, telemetry)
            seed(db, retriever, demo_data=settings.seed_demo_data)
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
            stack.callback(worker.stop)
            yield

    app = FastAPI(
        title="SupportOps AI",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.middleware("http")
    async def boundaries(request, call_next):
        response = None
        if request.method in ["POST", "PUT", "PATCH"]:
            # Bound the streamed body, including requests without Content-Length.
            size = 0
            body = bytearray()
            async for chunk in request.stream():
                size += len(chunk)
                if size > 32768:
                    response = JSONResponse({"detail": "Request body too large"}, status_code=413)
                    break
                body.extend(chunk)
            request._body = bytes(body)
        with app.state.telemetry.tracer.start_as_current_span(
            "http.request", record_exception=False, set_status_on_exception=False
        ) as http_span:
            http_span.set_attribute("http.request.method", request.method)
            if response is None:
                response = await call_next(request)
            route = request.scope.get("route")
            http_span.set_attribute("http.route", getattr(route, "path", "unmatched"))
            http_span.set_attribute("http.response.status_code", response.status_code)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable"
            if request.url.path.startswith("/assets/") and response.status_code == 200
            else "no-store"
        )
        if not request.url.path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
            )
        return response

    @app.exception_handler(OperationalError)
    async def database_unavailable(request, exc):
        return JSONResponse(
            {"detail": "Storage temporarily unavailable; try again later"},
            status_code=503,
            headers={"Retry-After": "5"},
        )

    @app.get("/api/ready")
    def ready():
        with app.state.db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        worker = app.state.worker
        if settings.worker_enabled and (worker.thread is None or not worker.thread.is_alive()):
            raise HTTPException(503, "Investigation worker unavailable")
        return {"status": "ready"}

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "mode": settings.mode,
            "auth_mode": settings.auth_mode,
            "connectors": "synthetic",
            "retrieval": "local_sentence_transformers"
            if settings.embedding_mode == "sentence_transformers"
            else "provider_embeddings"
            if settings.mode == "live" and settings.embedding_mode != "local"
            else "local_lexical_hash",
            "embedding_model": settings.local_embedding_model
            if settings.embedding_mode == "sentence_transformers"
            else settings.embedding_model
            if settings.mode == "live" and settings.embedding_mode != "local"
            else "lexical-hash",
            "embedding_dimensions": 384 if settings.embedding_mode == "sentence_transformers" else 256,
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
        require_engineer(principal)
        account = authorize_account(app.state.db, principal, body.account_id)
        try:
            question, events = validate_input(body.question)
        except SafetyViolation as exc:
            raise HTTPException(422, str(exc)) from None
        with app.state.db.session() as session:
            # Transaction-scoped tenant lock makes admission quotas atomic on PostgreSQL.
            if app.state.db.is_postgres:
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:tenant))"), {"tenant": principal.tenant_id}
                )
            else:
                # Serialize admission checks and inserts on SQLite as well as PostgreSQL.
                session.execute(text("BEGIN IMMEDIATE"))
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
    def cases(
        principal: Principal = Depends(current_user),
        summary: bool = False,
        limit: int = Query(default=100, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10000),
    ):
        with app.state.db.session() as session:
            columns = (
                [
                    Case.id,
                    Case.account_id,
                    Case.question,
                    Case.status,
                    Case.phase,
                    Case.created_at,
                    Case.updated_at,
                ]
                if summary
                else [Case]
            )
            query = (
                select(*columns)
                .where(Case.tenant_id == principal.tenant_id, Case.account_id.in_(principal.account_ids))
                .order_by(Case.created_at.desc(), Case.id.desc())
                .limit(limit)
                .offset(offset)
            )
            if summary:
                return [dict(row) for row in session.execute(query).mappings()]
            records = session.scalars(query).all()
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
        require_engineer(principal)
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
        require_engineer(principal)
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
    if (frontend / "index.html").is_file() and (frontend / "assets").is_dir():
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
