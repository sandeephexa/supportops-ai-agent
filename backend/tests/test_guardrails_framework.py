import importlib.util

import pytest
from conftest import investigate
from supportops.guardrails import verify_answer


@pytest.mark.skipif(
    importlib.util.find_spec("guardrails") is None, reason="Optional Guardrails AI extra not installed"
)
def test_guardrails_ai_validates_a_real_investigation(client):
    case = investigate(client)
    verified = verify_answer(case["result"], case["evidence"], use_framework=True)
    assert verified.needs_escalation
