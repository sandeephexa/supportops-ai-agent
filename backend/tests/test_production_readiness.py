from types import SimpleNamespace

import jwt
import pytest
from conftest import investigate
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from supportops.api import create_app
from supportops.config import Settings
from supportops.db import Case, User
from supportops.schemas import ApprovalRequest, CreateCase
from supportops.telemetry import Telemetry


def test_read_only_user_cannot_create_or_retry_cases(client):
    headers = {"X-Demo-User": "viewer-acme"}
    assert (
        client.post(
            "/api/cases",
            headers=headers,
            json={"account_id": "acme", "question": "Investigate HTTP 403 errors"},
        ).status_code
        == 403
    )
    case = investigate(client)
    with client.app.state.db.session() as session:
        record = session.get(Case, case["id"])
        record.status, record.error = "failed", "Temporary issue"
    assert client.post(f"/api/cases/{case['id']}/retry", headers=headers).status_code == 403
    assert client.get(f"/api/cases/{case['id']}", headers=headers).json()["status"] == "failed"


def test_summary_pagination_is_scoped_and_excludes_heavy_or_private_fields(client):
    first = investigate(client)
    second = investigate(client)
    response = client.get("/api/cases?summary=true&limit=1")
    row = response.json()[0]
    assert row["id"] == second["id"]
    assert set(row) == {"id", "account_id", "question", "status", "phase", "created_at", "updated_at"}
    assert client.get("/api/cases?summary=true&limit=1&offset=1").json()[0]["id"] == first["id"]
    assert client.get("/api/cases?summary=true", headers={"X-Demo-User": "engineer-rival"}).json() == []
    assert client.get("/api/cases?limit=101").status_code == 422
    assert client.get("/api/cases?offset=-1").status_code == 422
    assert len(response.content) < len(client.get(f"/api/cases/{second['id']}").content) / 2


def test_request_validation_rejects_blank_questions_and_coerced_approvals():
    with pytest.raises(ValidationError):
        CreateCase(account_id="acme", question=" " * 20)
    with pytest.raises(ValidationError):
        ApprovalRequest(payload_hash="a" * 64, approved="true")
    with pytest.raises(ValidationError):
        ApprovalRequest(payload_hash="x" * 64, approved=True)


def test_production_configuration_fails_closed():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production")
    config = dict(
        environment="production",
        allowed_hosts=["support.example.test"],
        auth_mode="oidc",
        oidc_issuer="https://identity.example.test",
        oidc_audience="support",
        oidc_jwks_url="https://identity.example.test/keys",
        seed_demo_data=False,
        auto_create_schema=False,
        database_url="postgresql+psycopg://localhost/support",
        checkpoint_url="postgresql://localhost/checkpoints",
    )
    Settings(_env_file=None, **config)
    for field, value in [
        ("auth_mode", "demo"),
        ("seed_demo_data", True),
        ("allowed_hosts", ["*"]),
        ("oidc_jwks_url", "http://identity.example.test/keys"),
        ("database_url", "sqlite:///local.db"),
    ]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{**config, field: value})
    assert "private-credential" not in repr(Settings(_env_file=None, api_key="private-credential"))


def test_demo_records_can_be_disabled(settings):
    with TestClient(create_app(settings.model_copy(update={"seed_demo_data": False}))) as client:
        with client.app.state.db.session() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 0
        assert client.get("/api/me").status_code == 403


def test_untrusted_host_rejected_and_errors_have_security_headers(client):
    response = client.get("/api/health", headers={"Host": "attacker.example"})
    assert response.status_code == 400
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    response = client.post("/api/cases", content="a" * 40000)
    assert response.status_code == 413
    assert response.headers["Cache-Control"] == "no-store"


def test_readiness_reports_storage_failure_without_exposing_details(client, monkeypatch):
    assert client.get("/api/ready").status_code == 200

    def unavailable():
        raise OperationalError("secret SQL", {}, Exception("private database address"))

    monkeypatch.setattr(client.app.state.db.engine, "connect", unavailable)
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert "private" not in response.text and "secret" not in response.text
    assert response.headers["Retry-After"] == "5"


def test_identity_outage_is_retryable_not_invalid_token(client, monkeypatch):
    client.app.state.settings = client.app.state.settings.model_copy(update={"auth_mode": "oidc"})

    def unavailable(token):
        raise jwt.PyJWKClientConnectionError("private identity address")

    client.app.state.jwks = SimpleNamespace(get_signing_key_from_jwt=unavailable)
    response = client.get("/api/me", headers={"Authorization": "Bearer test"})
    assert response.status_code == 503
    assert "private" not in response.text


def test_trace_storage_failure_does_not_mask_execution_result_or_original_error(settings, caplog):
    def unavailable():
        raise OperationalError("secret SQL", {}, Exception("private credential"))

    telemetry = Telemetry(SimpleNamespace(session=unavailable), settings)
    try:
        with telemetry.span("case", "test"):
            pass
        with pytest.raises(ValueError, match="original failure"), telemetry.span("case", "test"):
            raise ValueError("original failure")
        assert "Trace persistence failed" in caplog.text
        assert "private credential" not in caplog.text and "secret SQL" not in caplog.text
    finally:
        telemetry.shutdown()
