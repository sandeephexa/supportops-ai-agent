import math
import os
from unittest.mock import patch

import pytest
from sqlalchemy import select
from supportops.config import Settings
from supportops.db import Document
from supportops.retrieval import Retriever
from supportops.security import get_principal
from supportops.seed import seed


def test_semantic_matches_survive_without_keyword_overlap(client, tmp_path):
    class Encoder:
        version = "st:test:384:v1"

        def embed_documents(self, texts):
            return [[1.0] + [0.0] * 383 for _ in texts]

    settings = Settings(_env_file=None, embedding_mode="sentence_transformers")
    with patch("supportops.local_embeddings.LocalSentenceEmbeddings", return_value=Encoder()):
        retriever = Retriever(client.app.state.db, settings, client.app.state.telemetry)
    path = tmp_path / "payroll.md"
    path.write_text("# Payroll\n## Schedule\nEmployees receive compensation every fortnight.")
    retriever.ingest(path)
    principal = get_principal(client.app.state.db, "engineer-acme")
    found = retriever.search(principal, "acme", "staff paid biweekly", "semantic-test")
    assert found and found[0]["id"] == "public:payroll:v3:0"
    # Documents still using the hashing version are excluded before vector comparison.
    assert all(item["id"].startswith("public:payroll:") for item in found)


def test_seed_resumes_partial_embedding_reindex(client):
    db, retriever = client.app.state.db, client.app.state.retriever
    with db.session() as session:
        row = session.scalar(select(Document).where(Document.tenant_id == "public"))
        row.embedding_version = "old-index"
        target = row.id
    seed(db, retriever)
    with db.session() as session:
        assert session.get(Document, target).embedding_version == retriever.version


@pytest.mark.skipif(os.getenv("RUN_LOCAL_EMBEDDING_TESTS") != "1", reason="Opt-in cached real model test")
def test_real_minilm_offline_vectors_and_long_input():
    from supportops.local_embeddings import LocalSentenceEmbeddings

    encoder = LocalSentenceEmbeddings(Settings(_env_file=None, local_embedding_offline=True))
    query, related, unrelated = encoder.embed_documents(
        [
            "staff paid biweekly",
            "Employees receive compensation every fortnight.",
            "A telescope observes distant galaxies and stars.",
        ]
    )
    assert len(query) == 384
    assert math.sqrt(sum(x * x for x in query)) == pytest.approx(1.0, abs=1e-5)
    assert sum(a * b for a, b in zip(query, related, strict=True)) > sum(
        a * b for a, b in zip(query, unrelated, strict=True)
    )
    long_text = "Background documentation. " * 400 + "TAIL_IDENTIFIER"
    windows = encoder.windows(long_text)
    assert len(windows) > 1
    assert windows[-1].endswith("TAIL_IDENTIFIER")
    assert all(len(encoder.model.tokenizer(w)["input_ids"]) <= encoder.model.max_seq_length for w in windows)
    assert len(encoder.embed_documents([long_text])[0]) == 384


@pytest.mark.skipif(os.getenv("RUN_LOCAL_EMBEDDING_TESTS") != "1", reason="Opt-in cached real model test")
def test_real_minilm_retrieves_runbook_paraphrases(client):
    settings = client.app.state.settings.model_copy(
        update={"embedding_mode": "sentence_transformers", "local_embedding_offline": True}
    )
    retriever = Retriever(client.app.state.db, settings, client.app.state.telemetry)
    seed(client.app.state.db, retriever)
    principal = get_principal(client.app.state.db, "engineer-acme")
    queries = [
        ("Our requests are being throttled. How can we recover?", "public:synchronization:v3:0"),
        ("Access is denied after changing the integration key", "public:authentication:v3:1"),
        ("An outage in our data center is interrupting synchronization", "public:incidents:v3:0"),
    ]
    for query, expected in queries:
        assert retriever.search(principal, "acme", query, "real-minilm-query", limit=1)[0]["id"] == expected
