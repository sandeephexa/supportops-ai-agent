import time

from conftest import investigate
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from supportops.api import create_app
from supportops.db import Case, Ticket, User


def decide(client, case, approved=True):
    return client.post(
        f"/api/cases/{case['id']}/approval",
        json={"payload_hash": case["draft"]["payload_hash"], "approved": approved},
    )


def test_full_investigation_and_approval(client):
    case = investigate(client)
    assert case["status"] == "needs_approval"
    assert "Missing write permission" in case["result"]["summary"]
    assert case["receipt"] is None
    with client.app.state.db.session() as session:
        assert session.scalar(select(func.count()).select_from(Ticket)) == 0
    assert decide(client, case).status_code == 202
    client.app.state.workflow.run(case["id"])
    result = client.get(f"/api/cases/{case['id']}").json()
    assert result["status"] == "completed"
    assert result["receipt"]["ticket_id"].startswith("ENG-")
    trace = client.get(f"/api/cases/{case['id']}/trace").json()
    assert any(s["name"] == "guardrails.verify" for s in trace["spans"])
    assert any(a["action"] == "escalation.created" for a in trace["audit"])


def test_duplicate_approval_and_replay_creates_one_ticket(client):
    case = investigate(client)
    assert decide(client, case).status_code == 202
    assert decide(client, case).status_code == 202
    client.app.state.workflow.run(case["id"])
    client.app.state.workflow.run(case["id"])
    from supportops.actions import execute_escalation

    execute_escalation(client.app.state.db, case["id"])
    with client.app.state.db.session() as session:
        assert session.scalar(select(func.count()).select_from(Ticket)) == 1


def test_decline_never_creates_ticket(client):
    case = investigate(client)
    assert decide(client, case, False).status_code == 202
    client.app.state.workflow.run(case["id"])
    assert client.get(f"/api/cases/{case['id']}").json()["status"] == "declined"
    with client.app.state.db.session() as session:
        assert session.scalar(select(func.count()).select_from(Ticket)) == 0


def test_resume_approval_after_process_restart(settings):
    with TestClient(create_app(settings)) as first:
        case = investigate(first)
    with TestClient(create_app(settings)) as restarted:
        assert decide(restarted, case).status_code == 202
        restarted.app.state.workflow.run(case["id"])
        result = restarted.get(f"/api/cases/{case['id']}").json()
        assert result["receipt"] and result["status"] == "completed"


def test_expired_draft_requires_fresh_investigation(client):
    case = investigate(client)
    with client.app.state.db.session() as session:
        row = session.get(Case, case["id"])
        row.draft = {**row.draft, "expires_at": time.time() - 1}
    assert decide(client, case).status_code == 409


def test_mismatched_approval_is_rejected(client):
    case = investigate(client)
    response = client.post(
        f"/api/cases/{case['id']}/approval", json={"payload_hash": "a" * 64, "approved": True}
    )
    assert response.status_code == 409


def test_revoked_permissions_block_approved_execution(client):
    case = investigate(client)
    assert decide(client, case).status_code == 202
    with client.app.state.db.session() as session:
        session.get(User, "engineer-acme").account_ids = []
    assert client.app.state.worker.tick()
    with client.app.state.db.session() as session:
        assert session.get(Case, case["id"]).status == "failed"
        assert session.scalar(select(func.count()).select_from(Ticket)) == 0


def test_entitlement_uses_short_path_without_approval(client):
    case = investigate(client, question="What is the current support plan and entitlement for Acme?")
    assert case["status"] == "completed"
    assert case["draft"] is None
    assert "premium" in case["result"]["confirmed_facts"][0]["text"]


def test_unknown_request_abstains(client):
    case = investigate(client, question="Please explain the weather near the ocean tomorrow.")
    assert case["status"] == "needs_information"
    assert case["result"]["unresolved_questions"]
    assert case["draft"] is None


def test_rate_limit_and_incident_cases(client):
    atlas = investigate(client, "atlas", "Investigate 429 synchronization failures and prepare escalation.")
    meridian = investigate(client, "meridian", "Investigate 503 incident failures and prepare escalation.")
    assert "rate limited" in atlas["result"]["summary"]
    assert atlas["draft"]["payload"]["queue"] == "standard"
    assert "regional" in meridian["result"]["summary"]
    assert any("INC-2048" in f["text"] for f in meridian["result"]["confirmed_facts"])


def test_worker_recovers_expired_lease(client):
    response = client.post(
        "/api/cases", json={"account_id": "acme", "question": "Investigate 403 errors after rotation."}
    )
    case_id = response.json()["id"]
    with client.app.state.db.session() as session:
        record = session.get(Case, case_id)
        record.status, record.lease_until = "running", time.time() - 1
    assert client.app.state.worker.tick()
    assert client.get(f"/api/cases/{case_id}").json()["status"] == "needs_approval"


def test_worker_does_not_steal_active_lease(client):
    response = client.post(
        "/api/cases", json={"account_id": "acme", "question": "Investigate 403 errors after rotation."}
    )
    with client.app.state.db.session() as session:
        record = session.get(Case, response.json()["id"])
        record.status, record.lease_until = "running", time.time() + 300
    assert client.app.state.worker.claim() is None


def test_exhausted_crash_is_not_stuck_running_forever(client):
    response = client.post(
        "/api/cases", json={"account_id": "acme", "question": "Investigate credential failures."}
    )
    case_id = response.json()["id"]
    with client.app.state.db.session() as session:
        row = session.get(Case, case_id)
        row.status, row.lease_until, row.attempts = "running", time.time() - 1, 4
    assert client.app.state.worker.claim() is None
    assert client.get(f"/api/cases/{case_id}").json()["status"] == "failed"


def test_conflicting_scope_metadata_does_not_invent_missing_permission(client):
    from supportops.db import Account

    with client.app.state.db.session() as session:
        account = session.get(Account, "acme")
        account.diagnostics = {**account.diagnostics, "credential_scopes": ["sync:read", "sync:write"]}
    case = investigate(client)
    assert case["result"]["unresolved_questions"]
    assert "Missing write permission is the likely cause" not in case["result"]["summary"]


def test_missing_runbook_does_not_generate_unsupported_remediation(client):
    from supportops.db import Document

    with client.app.state.db.session() as session:
        for doc in session.scalars(select(Document)).all():
            doc.active = False
    case = investigate(client)
    assert case["result"]["recommended_steps"] == []
    assert case["result"]["unresolved_questions"]
    assert "no applicable runbook" in case["result"]["summary"]


def test_changed_account_facts_invalidate_approved_action(client):
    from supportops.db import Account

    case = investigate(client)
    assert decide(client, case).status_code == 202
    with client.app.state.db.session() as session:
        session.get(Account, "acme").plan = "standard"
    assert client.app.state.worker.tick()
    with client.app.state.db.session() as session:
        assert session.get(Case, case["id"]).status == "failed"
        assert session.scalar(select(func.count()).select_from(Ticket)) == 0
