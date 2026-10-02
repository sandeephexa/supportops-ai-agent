import hashlib
import json
import re
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request

from supportops.db import Account, Case, User

PATTERNS = [
    (
        "SECRET",
        re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|(?:api[_ -]?key|password|secret)\s*[:=]\s*[^\s,;]+)", re.I),
    ),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")),
    ("PHONE", re.compile(r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)")),
]
INJECTION = re.compile(
    r"ignore (?:all |your |the |previous )*(?:instructions|rules)|"
    r"(?:reveal|print|show) (?:the |your )?(?:system prompt|api key|secrets)|"
    r"(?:export|dump) all (?:customer|tenant)|<\|(?:system|im_start)\|>",
    re.I,
)


@dataclass(frozen=True)
class Principal:
    id: str
    name: str
    tenant_id: str
    role: str
    account_ids: tuple[str, ...]


def mask(text: str) -> tuple[str, list[str]]:
    events = []
    for label, pattern in PATTERNS:
        values = {}

        def replace(match, values=values, label=label):
            value = match.group(0)
            if value not in values:
                values[value] = f"[{label}_{len(values) + 1}]"
            return values[value]

        text, count = pattern.subn(replace, text)
        if count:
            events.append(f"Masked {count} {label.lower()} value(s)")
    return text, events


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def account_snapshot_hash(account) -> str:
    return payload_hash(
        {
            "account_id": account.id,
            "plan": account.plan,
            "product_version": account.product_version,
            "diagnostics": account.diagnostics,
        }
    )


def get_principal(db, user_id: str) -> Principal:
    with db.session() as session:
        user = session.get(User, user_id)
        if not user or not user.active:
            raise HTTPException(403, "Access unavailable")
        return Principal(user.id, user.name, user.tenant_id, user.role, tuple(user.account_ids))


def authorize_account(db, principal: Principal, account_id: str) -> Account:
    # Always reload membership: approvals and checkpoints never confer current access.
    current = get_principal(db, principal.id)
    with db.session() as session:
        account = session.get(Account, account_id)
        if not account or account.tenant_id != current.tenant_id or account.id not in current.account_ids:
            raise HTTPException(404, "Account not found")
        return account


def authorize_case(db, principal: Principal, case_id: str) -> Case:
    with db.session() as session:
        case = session.get(Case, case_id)
        if not case or case.tenant_id != principal.tenant_id:
            raise HTTPException(404, "Case not found")
    authorize_account(db, principal, case.account_id)
    return case


def current_user(request: Request) -> Principal:
    settings = request.app.state.settings
    if settings.auth_mode == "demo":
        # Synthetic identities only. No user-provided tenant or role claims.
        user_id = request.headers.get("X-Demo-User", "engineer-acme")
    else:
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer token required")
        token = authorization[7:]
        try:
            key = request.app.state.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=settings.oidc_audience,
                issuer=settings.oidc_issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
            user_id = claims["sub"]
        except Exception:
            raise HTTPException(401, "Invalid access token") from None
    return get_principal(request.app.state.db, user_id)
