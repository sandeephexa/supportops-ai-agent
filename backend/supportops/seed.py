import hashlib

from sqlalchemy import select

from supportops.config import ROOT
from supportops.db import Account, Document, User
from supportops.retrieval import chunk_markdown
from supportops.security import mask

ACCOUNTS = [
    dict(
        id="acme",
        tenant_id="northstar",
        name="Acme Industries",
        plan="premium",
        product_version="3",
        diagnostics={
            "failure_code": "SCOPE_MISSING",
            "http_status": 403,
            "failed_jobs": 47,
            "credential_scopes": ["sync:read"],
            "rotated_hours_ago": 18,
            "region": "us-east-1",
            "incident": None,
        },
    ),
    dict(
        id="atlas",
        tenant_id="northstar",
        name="Atlas Logistics",
        plan="standard",
        product_version="3",
        diagnostics={
            "failure_code": "RATE_LIMIT",
            "http_status": 429,
            "failed_jobs": 23,
            "credential_scopes": ["sync:read", "sync:write"],
            "rotated_hours_ago": 240,
            "region": "eu-west-1",
            "incident": None,
        },
    ),
    dict(
        id="meridian",
        tenant_id="northstar",
        name="Meridian Labs",
        plan="premium",
        product_version="3",
        diagnostics={
            "failure_code": "UPSTREAM_UNAVAILABLE",
            "http_status": 503,
            "failed_jobs": 112,
            "credential_scopes": ["sync:read", "sync:write"],
            "rotated_hours_ago": 72,
            "region": "us-east-1",
            "incident": {
                "id": "INC-2048",
                "service": "sync-service",
                "region": "us-east-1",
                "status": "investigating",
            },
        },
    ),
    dict(
        id="rival",
        tenant_id="other-tenant",
        name="Rival Private Account",
        plan="premium",
        product_version="3",
        diagnostics={
            "failure_code": "PRIVATE_DATA",
            "http_status": 500,
            "failed_jobs": 900,
            "credential_scopes": [],
            "region": "private",
            "incident": None,
        },
    ),
]


def seed_demo_records(db):
    with db.session() as session:
        for data in ACCOUNTS:
            if not session.get(Account, data["id"]):
                session.add(Account(**data))
        for user in [
            User(
                id="engineer-acme",
                name="Alex Morgan",
                tenant_id="northstar",
                role="engineer",
                account_ids=["acme", "atlas", "meridian"],
            ),
            User(
                id="viewer-acme",
                name="Jordan Lee",
                tenant_id="northstar",
                role="viewer",
                account_ids=["acme"],
            ),
            User(
                id="engineer-rival",
                name="Rival Engineer",
                tenant_id="other-tenant",
                role="engineer",
                account_ids=["rival"],
            ),
        ]:
            if not session.get(User, user.id):
                session.add(user)


def seed(db, retriever, demo_data=True):
    if demo_data:
        seed_demo_records(db)
    # Check each file, so an interrupted reindex is resumed rather than accepted as complete.
    for path in sorted((ROOT / "data" / "runbooks").glob("*.md")):
        clean, _ = mask(path.read_text())
        expected = {
            f"public:{path.stem}:v3:{i}": hashlib.sha256(content.encode()).hexdigest()
            for i, (_, _, content, _) in enumerate(chunk_markdown(clean))
        }
        with db.session() as session:
            rows = session.scalars(
                select(Document).where(
                    Document.id.startswith(f"public:{path.stem}:v3:", autoescape=True), Document.active
                )
            ).all()
            current = {row.id: row.content_hash for row in rows if row.embedding_version == retriever.version}
        if current != expected:
            retriever.ingest(path)
