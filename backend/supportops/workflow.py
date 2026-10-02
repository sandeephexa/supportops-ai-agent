import json
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from supportops.actions import execute_escalation
from supportops.db import Case
from supportops.guardrails import EvidenceVerificationFailure, SafetyViolation, verify_answer
from supportops.retrieval import pack_context
from supportops.security import account_snapshot_hash, authorize_account, get_principal, mask, payload_hash


class State(TypedDict, total=False):
    case_id: str
    plan: dict
    evidence: list
    result: dict
    verified: bool
    verification_feedback: list[str]
    revision_count: int
    approved: bool
    receipt: dict
    status: str


class Workflow:
    def __init__(self, db, settings, models, retriever, tools, telemetry, checkpointer):
        self.db, self.settings, self.models = db, settings, models
        self.retriever, self.tools, self.telemetry = retriever, tools, telemetry
        graph = StateGraph(State)
        for name in [
            "plan",
            "retrieve",
            "diagnose",
            "synthesize",
            "verify",
            "revise",
            "prepare",
            "approval",
            "execute",
        ]:
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "plan")
        for a, b in zip(
            ["plan", "retrieve", "diagnose", "synthesize"],
            ["retrieve", "diagnose", "synthesize", "verify"],
            strict=True,
        ):
            graph.add_edge(a, b)
        graph.add_conditional_edges("verify", lambda state: "prepare" if state["verified"] else "revise")
        graph.add_edge("revise", "verify")
        graph.add_conditional_edges(
            "prepare", lambda state: "approval" if state["result"]["needs_escalation"] else END
        )
        graph.add_conditional_edges("approval", lambda state: "execute" if state["approved"] else END)
        graph.add_edge("execute", END)
        self.graph = graph.compile(checkpointer=checkpointer)

    def context(self, state, config, phase):
        if time.time() >= config["configurable"]["deadline"]:
            raise TimeoutError("Investigation budget exhausted")
        with self.db.session() as session:
            case = session.get(Case, state["case_id"])
            case.phase, case.updated_at = phase, time.time()
        principal = get_principal(self.db, case.user_id)
        account = authorize_account(self.db, principal, case.account_id)
        return case, principal, account

    def plan(self, state, config):
        case, _, _ = self.context(state, config, "Understanding request")
        with self.telemetry.span(case.id, "agent.plan", model_mode=self.settings.mode):
            result = self.models.plan(case.id, case.question, config["configurable"]["deadline"])
            return {"plan": result.model_dump()}

    def context_budget(self, question):
        window = (
            min(self.settings.model_context_window, self.settings.fallback_context_window)
            if self.settings.fallback_model
            else self.settings.model_context_window
        )
        budget = min(
            self.settings.max_context_tokens,
            window - self.settings.model_output_tokens - 5000 - len(question.encode()),
        )
        if budget < 500:
            raise SafetyViolation("Configured context window cannot safely fit this request")
        return budget

    def retrieve(self, state, config):
        case, principal, _ = self.context(state, config, "Retrieving authorized evidence")
        evidence = self.retriever.search(principal, case.account_id, state["plan"]["query"], case.id)
        return {
            "evidence": pack_context(evidence, self.context_budget(case.question), state["plan"]["query"])
        }

    def diagnose(self, state, config):
        case, principal, _ = self.context(state, config, "Running read-only diagnostics")
        evidence, called = list(state["evidence"]), []
        with self.telemetry.span(case.id, "agent.diagnose") as attrs:
            for _ in range(3):
                self.context(state, config, "Running read-only diagnostics")
                calls = self.models.choose_tools(
                    case.id,
                    case.account_id,
                    state["plan"],
                    pack_context(evidence, self.context_budget(case.question), state["plan"]["query"]),
                    self.tools.definitions(principal, case.id, case.account_id),
                    config["configurable"]["deadline"],
                    called,
                )
                new_calls = [call for call in calls if call["name"] not in called]
                if not new_calls:
                    break
                for call in new_calls:
                    if len(called) >= self.settings.max_tool_calls:
                        break
                    # Never silently rewrite cross-account requests: reject them.
                    if call["args"].get("account_id") != case.account_id or set(call["args"]) != {
                        "account_id"
                    }:
                        raise SafetyViolation("Tool arguments exceeded the case scope")
                    result = self.tools.call(principal, case.id, case.account_id, call["name"])
                    evidence.append(result)
                    called.append(call["name"])
            # One bounded retrieval expansion driven by diagnostic error codes.
            failures = next((x for x in evidence if x["id"].endswith("get_sync_failures")), None)
            if failures:
                code = json.loads(failures["content"]).get("failure_code", "")
                extra = self.retriever.search(
                    principal, case.account_id, f"{code} {state['plan']['intent']}", case.id, limit=2
                )
                known = {x["id"] for x in evidence}
                evidence.extend(x for x in extra if x["id"] not in known)
            # Current facts first, then compact section windows. Never mix model-version indexes.
            evidence.sort(key=lambda x: x["source"] != "tool")
            window = (
                min(self.settings.model_context_window, self.settings.fallback_context_window)
                if self.settings.fallback_model
                else self.settings.model_context_window
            )
            # Reserve completion plus instructions, schemas, question and tool definitions.
            budget = min(
                self.settings.max_context_tokens,
                window - self.settings.model_output_tokens - 5000 - len(case.question.encode()),
            )
            if budget < 500:
                raise SafetyViolation("Configured context window cannot safely fit this request")
            packed = pack_context(evidence, budget, state["plan"]["query"])
            attrs.update(
                tool_calls=len(called), evidence_count=len(packed), retrieval_expansions=int(bool(failures))
            )
            return {"evidence": packed}

    def synthesize(self, state, config):
        case, _, _ = self.context(state, config, "Composing evidence-backed findings")
        with self.telemetry.span(case.id, "agent.synthesize"):
            result = self.models.synthesize(
                case.id, case.question, state["plan"], state["evidence"], config["configurable"]["deadline"]
            )
            return {"result": result.model_dump()}

    def verify(self, state, config):
        case, _, _ = self.context(state, config, "Verifying citations and safety")
        with self.telemetry.span(
            case.id,
            "guardrails.verify",
            framework="guardrails-ai" if self.settings.enable_guardrails else "local-validators",
        ) as attrs:
            feedback = []
            failure_code = "grounding_failed"
            try:
                verify_answer(state["result"], state["evidence"], self.settings.enable_guardrails)
            except SafetyViolation as exc:
                # Only provenance mistakes can be revised; sensitive/unsafe output stops immediately.
                if exc.code not in {"citation_missing", "citation_quote"}:
                    raise
                feedback, failure_code = [str(exc)], exc.code
            if not feedback and self.settings.mode == "live":
                verdict = self.models.verify_grounding(
                    case.id,
                    state["result"],
                    state["evidence"],
                    config["configurable"]["deadline"],
                    question=case.question,
                )
                if not verdict.supported or verdict.unsupported_claims:
                    feedback = verdict.unsupported_claims or [
                        "The draft contains claims not supported by the evidence."
                    ]
            attrs["supported"] = not feedback
            if feedback:
                attrs.update(failure_code=failure_code, unsupported_claim_count=len(feedback))
                if self.settings.mode != "live" or state.get("revision_count", 0) >= 1:
                    raise EvidenceVerificationFailure(feedback, code=failure_code)
                # Feedback is untrusted, redacted context; never presented as verified findings.
                return {"verified": False, "verification_feedback": [mask(x)[0][:1000] for x in feedback[:8]]}
        return {"verified": True, "verification_feedback": []}

    def revise(self, state, config):
        case, _, _ = self.context(state, config, "Correcting unsupported findings")
        with self.telemetry.span(case.id, "agent.revise", revision=1):
            result = self.models.revise(
                case.id,
                case.question,
                state["result"],
                state["evidence"],
                state["verification_feedback"],
                config["configurable"]["deadline"],
            )
        return {"result": result.model_dump(), "revision_count": state.get("revision_count", 0) + 1}

    def prepare(self, state, config):
        case, _, account = self.context(state, config, "Preparing review")
        draft = None
        if state["result"]["needs_escalation"]:
            # Server-owned account IDs, queue and action type cannot be supplied by the model.
            payload = {
                "type": "create_escalation",
                "case_id": case.id,
                "account_id": account.id,
                "account_snapshot_hash": account_snapshot_hash(account),
                "queue": "priority" if account.plan == "premium" else "standard",
                "summary": state["result"]["summary"],
                "evidence_ids": [e["id"] for e in state["evidence"]],
            }
            draft = {
                "payload": payload,
                "payload_hash": payload_hash(payload),
                "expires_at": time.time() + self.settings.approval_ttl_seconds,
            }
        with self.db.session() as session:
            record = session.get(Case, case.id)
            record.result, record.evidence, record.draft = state["result"], state["evidence"], draft
            record.guardrail_events = [
                *record.guardrail_events,
                "Citation provenance verified",
                "Sensitive output scan passed",
                "Tenant scope enforced",
            ]
        return {
            "status": "needs_approval"
            if draft
            else ("needs_information" if state["result"]["unresolved_questions"] else "completed")
        }

    def approval(self, state, config):
        case, _, _ = self.context(state, config, "Awaiting human approval")
        decision = interrupt({"case_id": case.id, "draft": case.draft})
        # The API persists the authenticated decision; graph input alone cannot authorize a write.
        with self.db.session() as session:
            persisted = session.get(Case, case.id).approval
        if not persisted or persisted["approved"] != bool(decision.get("approved")):
            raise SafetyViolation("No matching server-side approval exists")
        return {
            "approved": persisted["approved"],
            "status": "approved" if persisted["approved"] else "declined",
        }

    def execute(self, state, config):
        case, _, _ = self.context(state, config, "Creating approved escalation")
        with self.telemetry.span(case.id, "action.create_escalation"):
            receipt = execute_escalation(self.db, case.id)
            return {"receipt": receipt, "status": "completed"}

    def run(self, case_id):
        config = {
            "configurable": {
                "thread_id": case_id,
                "deadline": time.time() + self.settings.request_deadline_seconds,
            },
            "recursion_limit": 20,
        }
        with self.db.session() as session:
            case = session.get(Case, case_id)
            approval = case.approval
        snapshot = self.graph.get_state(config)
        if snapshot.values:
            input_value = (
                Command(resume={"approved": approval["approved"]})
                if snapshot.tasks and any(t.interrupts for t in snapshot.tasks) and approval
                else None
            )
        else:
            input_value = {"case_id": case_id}
        with self.telemetry.span(case_id, "investigation.run", graph_version="v2-grounded-revision"):
            result = self.graph.invoke(input_value, config)
        status = "needs_approval" if result.get("__interrupt__") else result.get("status", "completed")
        with self.db.session() as session:
            case = session.get(Case, case_id)
            case.status, case.lease_until, case.updated_at = status, 0, time.time()
            case.phase = {
                "completed": "Investigation complete",
                "needs_approval": "Awaiting human approval",
                "declined": "Escalation declined",
                "needs_information": "Additional information needed",
            }.get(status, status)
            if result.get("receipt"):
                case.receipt = result["receipt"]
        return result
