"""Run against a fresh, disposable PostgreSQL database. CI provisions pgvector."""

import os

import pytest
from conftest import investigate
from fastapi.testclient import TestClient
from supportops.api import create_app
from supportops.config import Settings


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"), reason="Disposable PostgreSQL service not configured"
)
def test_postgres_vector_retrieval_checkpoint_and_execution():
    url = os.environ["TEST_POSTGRES_URL"]
    settings = Settings(
        _env_file=None,
        database_url=url,
        checkpoint_url=url.replace("postgresql+psycopg", "postgresql"),
        worker_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        case = investigate(client)
        assert case["status"] == "needs_approval"
        assert any(e["source"] == "runbook" for e in case["evidence"])
    with TestClient(create_app(settings)) as restarted:
        response = restarted.post(
            f"/api/cases/{case['id']}/approval",
            json={"payload_hash": case["draft"]["payload_hash"], "approved": True},
        )
        assert response.status_code == 202
        restarted.app.state.workflow.run(case["id"])
        assert restarted.get(f"/api/cases/{case['id']}").json()["receipt"]["ticket_id"]
