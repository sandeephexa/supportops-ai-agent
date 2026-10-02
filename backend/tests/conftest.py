import pytest
from fastapi.testclient import TestClient
from supportops.api import create_app
from supportops.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path}/app.db",
        checkpoint_url=f"sqlite:///{tmp_path}/checkpoints.db",
        worker_enabled=False,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def investigate(
    client,
    account="acme",
    question="Investigate 403 errors after credential rotation and prepare escalation.",
):
    response = client.post("/api/cases", json={"account_id": account, "question": question})
    assert response.status_code == 202, response.text
    case_id = response.json()["id"]
    client.app.state.workflow.run(case_id)
    return client.get(f"/api/cases/{case_id}").json()
