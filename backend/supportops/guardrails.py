import json

from supportops.schemas import Investigation
from supportops.security import INJECTION, mask


class SafetyViolation(ValueError):
    def __init__(self, message, code="safety_violation", issues=None):
        super().__init__(message)
        self.code = code
        self.issues = issues or [message]


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
    issues = []
    failure_code = "citation_quote"
    for field in ("confirmed_facts", "hypotheses"):
        for index, claim in enumerate(getattr(parsed, field)):
            path = f"{field}[{index}]"
            if not claim.evidence_ids or any(ref not in sources for ref in claim.evidence_ids):
                issues.append(f"{path}.evidence_ids must reference available evidence sources.")
                failure_code = "citation_missing"
            elif not claim.quote.strip() or not any(
                claim.quote in sources[ref]["content"] for ref in claim.evidence_ids
            ):
                issues.append(
                    f"{path}.quote is not present in its cited evidence. Copy one exact, contiguous "
                    "supporting excerpt from ONE cited source; do not combine or paraphrase excerpts."
                )
    if issues:
        # Send all affected field locations to the bounded correction step, not draft contents.
        message = (
            "A claim references unavailable evidence"
            if failure_code == "citation_missing"
            else "A claim's supporting excerpt is not present in its evidence"
        )
        raise SafetyViolation(message, code=failure_code, issues=issues)
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
