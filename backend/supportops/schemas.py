from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateCase(StrictModel):
    account_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=10, max_length=6000)


class ApprovalRequest(StrictModel):
    payload_hash: str = Field(min_length=64, max_length=64)
    approved: bool


class Evidence(StrictModel):
    id: str
    source: Literal["runbook", "tool"]
    title: str
    content: str
    version: str
    observed_at: float
    score: float = 0


class Claim(StrictModel):
    text: str
    evidence_ids: list[str]
    # Exact supporting excerpt allows deterministic provenance checks.
    quote: str = Field(
        description="Copy one exact, contiguous excerpt from the content of ONE cited evidence source. "
        "It must directly support this claim. Do not combine excerpts, paraphrase, add ellipses, "
        "or alter punctuation. For multiple sources, choose one supporting excerpt or split the claim."
    )


class Investigation(StrictModel):
    summary: str
    confirmed_facts: list[Claim]
    hypotheses: list[Claim]
    recommended_steps: list[str]
    unresolved_questions: list[str]
    needs_escalation: bool = Field(
        description="Whether to prepare an escalation proposal for human review. This is a workflow decision, not a claim that escalation is mandatory or that a ticket was created."
    )


class Plan(StrictModel):
    intent: Literal["authentication", "sync", "incident", "entitlement", "unknown"]
    query: str
    reason: str


class GroundingVerdict(StrictModel):
    supported: bool
    unsupported_claims: list[str]


class ToolCall(StrictModel):
    name: Literal[
        "get_account_entitlement", "get_sync_failures", "get_credential_metadata", "get_service_incidents"
    ]
    account_id: str
    reason: str


class ToolSelection(StrictModel):
    calls: list[ToolCall]
