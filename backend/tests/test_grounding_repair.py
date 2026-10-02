from sqlalchemy import func, select
from supportops.db import Ticket
from supportops.schemas import GroundingVerdict, Investigation


def setup_rejected_draft(client, monkeypatch, always_reject=False):
    workflow = client.app.state.workflow
    workflow.settings = workflow.settings.model_copy(update={"mode": "live"})
    models = client.app.state.models
    original = models.synthesize
    calls = {"verify": 0, "revise": 0}

    def synthesize(*args, **kwargs):
        result = original(*args, **kwargs)
        result.summary += " All jobs have recovered."
        return result

    def verify(case_id, result, evidence, deadline, question=""):
        calls["verify"] += 1
        assert question == "Investigate 503 errors and prepare escalation."
        unsupported = always_reject or "All jobs have recovered." in result["summary"]
        return GroundingVerdict(
            supported=not unsupported,
            unsupported_claims=["Recovery is not established by any source."] if unsupported else [],
        )

    def revise(case_id, question, result, evidence, feedback, deadline):
        calls["revise"] += 1
        assert feedback == ["Recovery is not established by any source."]
        return Investigation.model_validate(
            {**result, "summary": result["summary"].replace(" All jobs have recovered.", "")}
        )

    monkeypatch.setattr(models, "synthesize", synthesize)
    monkeypatch.setattr(models, "verify_grounding", verify)
    monkeypatch.setattr(models, "revise", revise)
    case = client.post(
        "/api/cases",
        json={"account_id": "meridian", "question": "Investigate 503 errors and prepare escalation."},
    ).json()
    return case, calls


def test_unsupported_claim_is_corrected_then_verified_before_approval(client, monkeypatch):
    case, calls = setup_rejected_draft(client, monkeypatch)
    client.app.state.worker.tick()
    result = client.get(f"/api/cases/{case['id']}").json()
    assert result["status"] == "needs_approval"
    assert "recovered" not in result["result"]["summary"]
    assert calls == {"verify": 2, "revise": 1}
    snapshot = client.app.state.workflow.graph.get_state({"configurable": {"thread_id": case["id"]}})
    assert snapshot.values["revision_count"] == 1
    assert snapshot.values["verified"] is True
    with client.app.state.db.session() as session:
        assert session.scalar(select(func.count()).select_from(Ticket)) == 0


def test_repeat_grounding_failure_stops_after_one_revision(client, monkeypatch):
    case, calls = setup_rejected_draft(client, monkeypatch, always_reject=True)
    client.app.state.worker.tick()
    result = client.get(f"/api/cases/{case['id']}").json()
    assert result["status"] == "failed"
    assert result["error"].startswith("Evidence verification failed:")
    assert result["draft"] is None
    assert result["retryable"] is False
    assert calls == {"verify": 2, "revise": 1}
    assert client.post(f"/api/cases/{case['id']}/retry").status_code == 409
    snapshot = client.app.state.workflow.graph.get_state({"configurable": {"thread_id": case["id"]}})
    assert snapshot.values["revision_count"] == 1


def test_sensitive_output_is_not_sent_for_revision(client, monkeypatch):
    case, calls = setup_rejected_draft(client, monkeypatch)
    original = client.app.state.models.synthesize

    def sensitive(*args, **kwargs):
        result = original(*args, **kwargs)
        result.summary = "Email alice@example.com for the answer"
        return result

    monkeypatch.setattr(client.app.state.models, "synthesize", sensitive)
    client.app.state.worker.tick()
    assert client.get(f"/api/cases/{case['id']}").json()["status"] == "failed"
    assert calls == {"verify": 0, "revise": 0}


def test_failure_records_identify_the_synthetic_connectors_service(client):
    import json

    from supportops.security import get_principal

    principal = get_principal(client.app.state.db, "engineer-acme")
    evidence = client.app.state.tools.call(principal, "service-test", "meridian", "get_sync_failures")
    facts = json.loads(evidence["content"])
    assert facts["service"] == "sync-service"
    assert facts["region"] == "us-east-1"
    assert facts["failed_jobs"] == 112
    assert evidence["version"] == "synthetic-v2"
