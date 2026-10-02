from unittest.mock import patch

from supportops.config import Settings
from supportops.retrieval import Retriever


def test_live_llm_with_explicit_local_retrieval():
    settings = Settings(_env_file=None, mode="live", api_key="test", embedding_mode="local")
    with patch("supportops.retrieval.OpenAIEmbeddings") as provider:
        retriever = Retriever(None, settings, None)
        assert retriever.embedder is None
        assert len(retriever.embed(["scope missing"])[0]) == 256
        assert retriever.version == "demo-hash:256:v1"
        provider.assert_not_called()


def test_live_retrieval_defaults_to_provider_embeddings():
    settings = Settings(_env_file=None, mode="live", api_key="test")
    with patch("supportops.retrieval.OpenAIEmbeddings") as provider:
        retriever = Retriever(None, settings, None)
        provider.assert_called_once()
        assert retriever.embedder is provider.return_value
        assert retriever.version == "text-embedding-3-small:256"
