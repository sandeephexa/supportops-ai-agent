import json

from supportops.schemas import Investigation
from supportops.security import INJECTION, mask


class SafetyViolation(ValueError):
    def __init__(self, message, code="safety_violation"):
        super().__init__(message)
        self.code = code


class EvidenceVerificationFailure(SafetyViolation):
    def __init__(self, issues, code="grounding_failed"):
        super().__init__("Evidence verification failed after correction; manual review required.", code=code)
        self.issues = [mask(str(issue))[0][:600] for issue in issues[:3]]


def validate_input(question):
    if INJECTION.search(question):
        raise SafetyViolation(
            "This request contains instructions to bypass access or safety controls. Describe the support issue instead."
        )
    return mask(question)


def verify_answer(result, evidence, use_framework=False):
    parsed = Investigation.model_validate(result)
    clean, redactions = mask(json.dumps(result))
    if redactions:
        raise SafetyViolation("Output contains sensitive data")
    if INJECTION.search(clean):
        raise SafetyViolation("Output contains unsafe instructions")
    sources = {x["id"]: x for x in evidence}
    for claim in [*parsed.confirmed_facts, *parsed.hypotheses]:
        if not claim.evidence_ids or any(ref not in sources for ref in claim.evidence_ids):
            raise SafetyViolation("A claim references unavailable evidence", code="citation_missing")
        if not claim.quote.strip() or not any(
            claim.quote in sources[ref]["content"] for ref in claim.evidence_ids
        ):
            raise SafetyViolation(
                "A claim's supporting excerpt is not present in its evidence", code="citation_quote"
            )
    if use_framework:
        from guardrails import Guard
        from guardrails.settings import settings as guard_settings

        guard_settings.disable_tracing = True

        guard = Guard.for_pydantic(output_class=Investigation)
        guard.configure(allow_metrics_collection=False)
        validation = guard.validate(json.dumps(result), num_reasks=0)
        if not validation.validation_passed:
            raise SafetyViolation("Guardrails AI schema validation failed")
    # Exact quotes establish provenance, not entailment; live mode adds an independent judge.
    return parsed
