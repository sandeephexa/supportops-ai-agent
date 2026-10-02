import time

from fastapi import HTTPException

from supportops.db import Action, AuditEvent, Case, Ticket
from supportops.security import account_snapshot_hash, authorize_account, get_principal, payload_hash


def execute_escalation(db, case_id):
    with db.session() as session:
        case = session.get(Case, case_id)
        if not case or not case.draft or not case.approval:
            raise HTTPException(409, "Approved draft required")
        draft, approval = case.draft, case.approval
        principal = get_principal(db, approval["actor"])
        account = authorize_account(db, principal, case.account_id)
        if principal.role != "engineer" or not approval["approved"]:
            raise HTTPException(403, "Execution not authorized")
        digest = payload_hash(draft["payload"])
        if digest != approval["payload_hash"] or digest != draft["payload_hash"]:
            raise HTTPException(409, "Approval no longer matches the draft")
        key = "escalation:" + payload_hash({"case_id": case.id, "payload_hash": digest})
        existing = session.get(Action, key)
        if existing and existing.status == "succeeded":
            return existing.receipt
        if draft["payload"].get("account_snapshot_hash") != account_snapshot_hash(account):
            raise HTTPException(409, "Account facts changed; start a fresh investigation")
        if approval["expires_at"] < time.time():
            raise HTTPException(409, "Approval expired")
        # Simulator makes action ledger + ticket atomic. Real remote APIs need reconciliation.
        ticket_id = f"ENG-{digest[:24].upper()}"
        receipt = {
            "ticket_id": ticket_id,
            "idempotency_key": key,
            "connector": "synthetic",
            "created_at": time.time(),
            "status": "created",
        }
        session.add(
            Ticket(id=ticket_id, idempotency_key=key, tenant_id=case.tenant_id, payload=draft["payload"])
        )
        session.add(Action(id=key, case_id=case.id, payload_hash=digest, status="succeeded", receipt=receipt))
        case.receipt = receipt
        session.add(
            AuditEvent(
                tenant_id=case.tenant_id,
                case_id=case.id,
                actor=principal.id,
                action="escalation.created",
                details={"ticket_id": ticket_id, "payload_hash": digest},
            )
        )
        return receipt
