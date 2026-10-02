import logging
import threading
import time

from sqlalchemy import and_, or_, select, update

from supportops.db import AuditEvent, Case
from supportops.guardrails import EvidenceVerificationFailure, SafetyViolation
from supportops.models import PROVIDER_BLOCK_MESSAGE, ModelRefusal, ModelUnavailable

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, db, workflow, settings):
        self.db, self.workflow, self.settings = db, workflow, settings
        self.stop_event = threading.Event()
        self.thread = None

    def claim(self):
        now = time.time()
        eligible = or_(Case.status == "queued", and_(Case.status == "running", Case.lease_until < now))
        with self.db.session() as session:
            exhausted = session.scalars(select(Case).where(eligible, Case.attempts >= 4)).all()
            for case in exhausted:
                case.status, case.phase, case.lease_until = "failed", "Manual review required", 0
                case.error = "Retry budget exhausted; start a fresh investigation."
                session.add(
                    AuditEvent(
                        case_id=case.id,
                        tenant_id=case.tenant_id,
                        actor="worker",
                        action="investigation.exhausted",
                        details={},
                    )
                )
            candidate = session.scalar(
                select(Case.id).where(eligible, Case.attempts < 4).order_by(Case.created_at).limit(1)
            )
            if not candidate:
                return None
            result = session.execute(
                update(Case)
                .where(Case.id == candidate, eligible)
                .values(
                    status="running",
                    lease_until=now + max(300, self.settings.request_deadline_seconds * 3),
                    attempts=Case.attempts + 1,
                )
            )
            return candidate if result.rowcount == 1 else None

    def tick(self):
        case_id = self.claim()
        if not case_id:
            return False
        try:
            self.workflow.run(case_id)
        except Exception as exc:
            logger.warning("Investigation failed case=%s type=%s", case_id, type(exc).__name__)
            with self.db.session() as session:
                case = session.get(Case, case_id)
                case.status, case.phase, case.lease_until = "failed", "Manual review required", 0
                # Only controlled type names are exposed; provider payloads may contain secrets.
                if isinstance(exc, ModelRefusal):
                    case.error = PROVIDER_BLOCK_MESSAGE
                elif isinstance(exc, SafetyViolation) and exc.code in {
                    "grounding_failed",
                    "citation_missing",
                    "citation_quote",
                }:
                    case.error = "Evidence verification failed: the generated answer could not be supported by its sources after one correction. No escalation was created. Start a new investigation with more specific evidence or request manual review."
                    if isinstance(exc, EvidenceVerificationFailure):
                        case.error += " Verifier concerns (model assessment): " + " ".join(exc.issues)
                elif isinstance(exc, ModelUnavailable) and exc.code == "output_token_limit":
                    case.error = "Model output limit reached: the structured answer was cut off. Increase SUPPORTOPS_MODEL_OUTPUT_TOKENS within the model context limit before retrying."
                elif isinstance(exc, ModelUnavailable) and exc.code == "provider_request_rejected":
                    case.error = "Provider request rejected: check the configured model, API access and request compatibility."
                else:
                    case.error = (
                        f"{type(exc).__name__}: investigation stopped safely. Review the trace or retry."
                    )
                case.updated_at = time.time()
            with self.db.session() as session:
                case = session.get(Case, case_id)
                tenant_id = case.tenant_id
            self.db.audit(
                case_id, tenant_id, "worker", "investigation.failed", {"error_type": type(exc).__name__}
            )
        return True

    def start(self):
        def loop():
            while not self.stop_event.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    logger.warning("Worker tick failed type=%s", type(exc).__name__)
                self.stop_event.wait(self.settings.worker_poll_seconds)

        self.thread = threading.Thread(target=loop, name="supportops-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=self.settings.request_deadline_seconds + 30)
