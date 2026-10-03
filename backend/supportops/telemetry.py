import logging
import time
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.exc import SQLAlchemyError

from supportops.db import TraceEvent

logger = logging.getLogger(__name__)


class Telemetry:
    def __init__(self, db, settings):
        self.db = db
        self.provider = TracerProvider(resource=Resource.create({"service.name": "supportops-ai"}))
        if settings.otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            self.provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint))
            )
        self.tracer = self.provider.get_tracer("supportops", "0.1.0")

    @contextmanager
    def span(self, case_id: str, name: str, **attributes):
        start = time.monotonic()
        status = "ok"
        # No prompts, tool content, credentials or exception messages in telemetry.
        with self.tracer.start_as_current_span(
            name, record_exception=False, set_status_on_exception=False
        ) as span:
            span.set_attribute("supportops.case_id", case_id)
            span.set_attribute("openinference.span.kind", "LLM" if name.startswith("model.") else "CHAIN")
            try:
                yield attributes
            except Exception as exc:
                status = "error"
                attributes["error_type"] = type(exc).__name__
                span.set_status(trace.Status(trace.StatusCode.ERROR))
                raise
            finally:
                duration = (time.monotonic() - start) * 1000
                for key, value in attributes.items():
                    if isinstance(value, (str, int, float, bool)):
                        span.set_attribute(key, value)
                try:
                    with self.db.session() as session:
                        session.add(
                            TraceEvent(
                                case_id=case_id,
                                name=name,
                                duration_ms=round(duration, 2),
                                status=status,
                                attributes=attributes,
                            )
                        )
                except SQLAlchemyError as exc:
                    # Optional trace storage must not change execution outcomes or mask errors.
                    # Action/audit persistence remains transactional and is never swallowed.
                    logger.warning("Trace persistence failed type=%s", type(exc).__name__)

    def shutdown(self):
        self.provider.shutdown()
