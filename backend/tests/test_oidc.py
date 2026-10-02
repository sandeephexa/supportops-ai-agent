import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from supportops.api import create_app


@pytest.fixture
def oidc_client(settings):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = settings.model_copy(
        update={
            "auth_mode": "oidc",
            "oidc_issuer": "https://identity.example.test",
            "oidc_audience": "supportops",
            "oidc_jwks_url": "https://identity.example.test/keys",
        }
    )
    with TestClient(create_app(settings)) as client:
        client.app.state.jwks = SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private.public_key())
        )
        yield client, private


def make_token(private, **changes):
    claims = {
        "sub": "viewer-acme",
        "iss": "https://identity.example.test",
        "aud": "supportops",
        "exp": time.time() + 300,
        "iat": time.time(),
        "role": "engineer",
        "tenant_id": "other-tenant",
    }
    return jwt.encode({**claims, **changes}, private, algorithm="RS256")


def test_oidc_uses_server_membership_not_token_role_claims(oidc_client):
    client, private = oidc_client
    response = client.get("/api/me", headers={"Authorization": f"Bearer {make_token(private)}"})
    assert response.status_code == 200
    assert response.json()["role"] == "viewer"
    assert response.json()["tenant_id"] == "northstar"
    assert response.json()["account_ids"] == ["acme"]


def test_demo_identity_header_cannot_bypass_oidc(oidc_client):
    client, _ = oidc_client
    assert client.get("/api/me", headers={"X-Demo-User": "engineer-acme"}).status_code == 401


@pytest.mark.parametrize(
    "changes", [{"aud": "other-app"}, {"iss": "https://attacker.test"}, {"exp": time.time() - 300}]
)
def test_invalid_oidc_claims_are_rejected(oidc_client, changes):
    client, private = oidc_client
    response = client.get("/api/me", headers={"Authorization": f"Bearer {make_token(private, **changes)}"})
    assert response.status_code == 401
