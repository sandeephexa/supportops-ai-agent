import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32), default="engineer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    account_ids: Mapped[list] = mapped_column(JSON, default=list)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    plan: Mapped[str] = mapped_column(String(32))
    product_version: Mapped[str] = mapped_column(String(16))
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(16))
    section: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    parent_content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list] = mapped_column(JSON)
    vector: Mapped[list | None] = mapped_column(Vector(256).with_variant(JSON(), "sqlite"), nullable=True)
    embedding_version: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(200))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(64), default="queued")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    approval: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    guardrail_events: Mapped[list] = mapped_column(JSON, default=list)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)
    trace_id: Mapped[str] = mapped_column(String(64), default=uid)


class TraceEvent(Base):
    __tablename__ = "trace_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(80))
    duration_ms: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Database:
    def __init__(self, url: str):
        self.is_postgres = url.startswith("postgresql")
        if url.startswith("sqlite"):
            path = url.split("///", 1)[-1]
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={} if self.is_postgres else {"check_same_thread": False, "timeout": 30},
        )
        if not self.is_postgres:

            @event.listens_for(self.engine, "connect")
            def sqlite_settings(connection, _):
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA busy_timeout=30000")
                connection.execute("PRAGMA foreign_keys=ON")

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self, auto_create=True):
        if not auto_create:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT version_num FROM alembic_version"))
            return
        if self.is_postgres:
            with self.engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(self.engine)
        if self.is_postgres:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS documents_fts ON documents USING gin(to_tsvector('english', content))"
                    )
                )

    @contextmanager
    def session(self):
        with self.sessions.begin() as session:
            yield session

    def audit(self, case_id, tenant_id, actor, action, details=None):
        with self.session() as session:
            session.add(
                AuditEvent(
                    case_id=case_id, tenant_id=tenant_id, actor=actor, action=action, details=details or {}
                )
            )
