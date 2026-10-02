import pytest
from sqlalchemy import func, select
from supportops.db import Ticket
from supportops.guardrails import SafetyViolation, verify_answer
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


def test_combined_source_quotes_are_rejected_with_each_affected_field():
    # Regression: real Atlas draft joined valid tool + runbook excerpts with a semicolon.
    evidence = [
        {"id": "failures", "content": '"failure_code": "RATE_LIMIT", "http_status": 429'},
        {
            "id": "runbook",
            "content": "HTTP 429 with error code RATE_LIMIT indicates that the integration exceeded its request quota.",
        },
        {"id": "incidents", "content": '"active_incident": null, "region": "eu-west-1"'},
    ]
    result = {
        "summary": "Rate limiting may explain these failures.",
        "confirmed_facts": [],
        "hypotheses": [
            {
                "text": "Rate limiting likely explains the failures.",
                "evidence_ids": ["failures", "runbook"],
                "quote": evidence[0]["content"] + "; " + evidence[1]["content"],
            },
            {
                "text": "A regional incident is not supported as the cause.",
                "evidence_ids": ["incidents", "failures"],
                "quote": evidence[2]["content"] + "; " + evidence[0]["content"],
            },
        ],
        "recommended_steps": [],
        "unresolved_questions": [],
        "needs_escalation": False,
    }
    with pytest.raises(SafetyViolation) as error:
        verify_answer(result, evidence)
    assert error.value.code == "citation_quote"
    assert len(error.value.issues) == 2
    assert "hypotheses[0].quote" in error.value.issues[0]
    assert "hypotheses[1].quote" in error.value.issues[1]
    # A multi-source inference may quote one supporting source verbatim.
    result["hypotheses"][0]["quote"] = evidence[1]["content"]
    result["hypotheses"][1]["quote"] = evidence[2]["content"]
    assert verify_answer(result, evidence).needs_escalation is False


def test_citation_repair_gets_field_feedback_then_requires_semantic_verification(client, monkeypatch):
    workflow = client.app.state.workflow
    workflow.settings = workflow.settings.model_copy(update={"mode": "live"})
    models = client.app.state.models
    original = models.synthesize
    calls = {"revise": 0, "verify": 0}

    def synthesize(*args, **kwargs):
        draft = original(*args, **kwargs)
        draft.confirmed_facts[0].quote += "; fabricated connector text"
        draft.needs_escalation = False
        return draft

    def revise(case_id, question, result, evidence, feedback, deadline):
        calls["revise"] += 1
        assert "confirmed_facts[0].quote" in feedback[0]
        assert "ONE cited source" in feedback[0]
        draft = Investigation.model_validate(result)
        claim = draft.confirmed_facts[0]
        claim.quote = next(e["content"] for e in evidence if e["id"] == claim.evidence_ids[0])
        return draft

    def verify(case_id, result, evidence, deadline, question=""):
        calls["verify"] += 1
        verify_answer(result, evidence)
        return GroundingVerdict(supported=True, unsupported_claims=[])

    monkeypatch.setattr(models, "synthesize", synthesize)
    monkeypatch.setattr(models, "revise", revise)
    monkeypatch.setattr(models, "verify_grounding", verify)
    case = client.post(
        "/api/cases",
        json={"account_id": "atlas", "question": "Investigate HTTP 429. Do not create an escalation."},
    ).json()
    client.app.state.worker.tick()
    result = client.get(f"/api/cases/{case['id']}").json()
    assert result["status"] in {"completed", "needs_information"}
    assert result["draft"] is None
    assert result["error"] is None
    assert calls == {"revise": 1, "verify": 1}
    with client.app.state.db.session() as session:
        assert session.scalar(select(func.count()).select_from(Ticket)) == 0
