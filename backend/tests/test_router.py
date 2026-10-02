import time
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError
from supportops.config import Settings
from supportops.models import ModelGateway, ModelRefusal, ModelUnavailable
from supportops.schemas import Plan


class FakeClient:
    attempts = []

    def __init__(self, **kwargs):
        self.model = kwargs["model"]

    def with_structured_output(self, *args, **kwargs):
        return self

    def invoke(self, messages):
        self.attempts.append(self.model)
        if self.model == "broken":
            raise APIConnectionError(request=httpx.Request("POST", "https://example.com"))
        if self.model == "refuses":
            return {
                "raw": SimpleNamespace(usage_metadata={}, additional_kwargs={"refusal": "Cannot comply"}),
                "parsed": None,
            }
        return {
            "raw": SimpleNamespace(
                usage_metadata={"input_tokens": 10, "output_tokens": 5}, additional_kwargs={}
            ),
            "parsed": Plan(intent="authentication", query="403", reason="test"),
        }


def test_transient_failure_falls_back_with_circuit_breaker(client, monkeypatch):
    monkeypatch.setattr("supportops.models.ChatOpenAI", FakeClient)
    monkeypatch.setattr("supportops.models.time.sleep", lambda _: None)
    FakeClient.attempts = []
    settings = Settings(
        _env_file=None, mode="live", api_key="test", small_model="broken", fallback_model="healthy"
    )
    gateway = ModelGateway(settings, client.app.state.telemetry)
    assert gateway.plan("test", "403", time.time() + 30).intent == "authentication"
    assert FakeClient.attempts == ["broken", "broken", "healthy"]
    FakeClient.attempts = []
    gateway.plan("test", "403", time.time() + 30)
    assert FakeClient.attempts == ["healthy"]


def test_refusal_never_triggers_fallback(client, monkeypatch):
    monkeypatch.setattr("supportops.models.ChatOpenAI", FakeClient)
    FakeClient.attempts = []
    settings = Settings(
        _env_file=None, mode="live", api_key="test", small_model="refuses", fallback_model="healthy"
    )
    gateway = ModelGateway(settings, client.app.state.telemetry)
    with pytest.raises(ModelRefusal):
        gateway.plan("test", "403", time.time() + 30)
    assert FakeClient.attempts == ["refuses"]


def test_deadline_prevents_model_call(client, monkeypatch):
    monkeypatch.setattr("supportops.models.ChatOpenAI", FakeClient)
    FakeClient.attempts = []
    settings = Settings(_env_file=None, mode="live", api_key="test")
    gateway = ModelGateway(settings, client.app.state.telemetry)
    with pytest.raises(ModelUnavailable, match="deadline"):
        gateway.plan("test", "403", time.time() - 1)
    assert not FakeClient.attempts


def test_cost_uses_the_selected_models_price(client, monkeypatch):
    from sqlalchemy import select
    from supportops.db import TraceEvent

    monkeypatch.setattr("supportops.models.ChatOpenAI", FakeClient)
    settings = Settings(
        _env_file=None,
        mode="live",
        api_key="test",
        small_model="healthy",
        model_prices={"healthy": {"input": 2.0, "output": 8.0}},
    )
    gateway = ModelGateway(settings, client.app.state.telemetry)
    gateway.plan("priced-case", "403", time.time() + 30)
    with client.app.state.db.session() as session:
        span = session.scalar(select(TraceEvent).where(TraceEvent.case_id == "priced-case"))
        assert span.attributes["estimated_cost_usd"] == pytest.approx((10 * 2 + 5 * 8) / 1e6)


def test_provider_safety_http_error_is_not_retried_or_routed(client, monkeypatch):
    from openai import BadRequestError
    from sqlalchemy import select
    from supportops.db import TraceEvent

    class BlockedClient(FakeClient):
        def invoke(self, messages):
            self.attempts.append(self.model)
            raise BadRequestError(
                "Blocked",
                response=httpx.Response(400, request=httpx.Request("POST", "https://example.com")),
                body={"message": "Content blocked by Model Armor", "sensitive_findings": "never-log-this"},
            )

    monkeypatch.setattr("supportops.models.ChatOpenAI", BlockedClient)
    FakeClient.attempts = []
    settings = Settings(_env_file=None, mode="live", api_key="test", fallback_model="healthy")
    with pytest.raises(ModelRefusal):
        ModelGateway(settings, client.app.state.telemetry).plan("blocked-case", "403", time.time() + 30)
    assert FakeClient.attempts == [settings.small_model]
    with client.app.state.db.session() as session:
        span = session.scalar(select(TraceEvent).where(TraceEvent.case_id == "blocked-case"))
        assert span.attributes["failure_code"] == "provider_policy_block"
        assert span.attributes["http_status"] == 400
        assert "never-log-this" not in str(span.attributes)


def test_worker_surfaces_safety_block_and_api_rejects_retry(client, monkeypatch):
    from supportops.models import PROVIDER_BLOCK_MESSAGE

    case = client.post("/api/cases", json={"account_id": "acme", "question": "Investigate 403 errors"}).json()

    def blocked(_):
        raise ModelRefusal("raw provider details must not appear")

    monkeypatch.setattr(client.app.state.workflow, "run", blocked)
    client.app.state.worker.tick()
    failed = client.get(f"/api/cases/{case['id']}").json()
    assert failed["error"] == PROVIDER_BLOCK_MESSAGE
    assert failed["retryable"] is False
    assert client.post(f"/api/cases/{case['id']}/retry").status_code == 409


def test_output_budget_is_configured_and_truncation_is_explicit(client, monkeypatch):
    from openai import LengthFinishReasonError

    captured = {}

    class TruncatedClient(FakeClient):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            super().__init__(**kwargs)

        def invoke(self, messages):
            raise LengthFinishReasonError(completion=SimpleNamespace(usage=None))

    monkeypatch.setattr("supportops.models.ChatOpenAI", TruncatedClient)
    settings = Settings(_env_file=None, mode="live", api_key="test", model_output_tokens=4000)
    with pytest.raises(ModelUnavailable) as error:
        ModelGateway(settings, client.app.state.telemetry).plan("length-case", "403", time.time() + 60)
    assert error.value.code == "output_token_limit"
    assert captured["max_completion_tokens"] == 4000


def test_context_reserves_the_configured_output_budget(client):
    workflow = client.app.state.workflow
    workflow.settings = workflow.settings.model_copy(
        update={"model_context_window": 12000, "model_output_tokens": 4000}
    )
    assert workflow.context_budget("test") == 2996
