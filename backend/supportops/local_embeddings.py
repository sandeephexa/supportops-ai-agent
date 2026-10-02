"""Pinned local sentence encoder; text is never sent to an embedding API."""

import hashlib
import math
import os
import threading
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2)
def load_model(name, revision, cache, offline):
    # Library downloads/cache stay in the project, and no remote model code is executed.
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HOME", str(Path(cache) / "huggingface"))
    os.environ.setdefault("TORCH_HOME", str(Path(cache) / "torch"))
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        name,
        revision=revision,
        cache_folder=cache,
        device="cpu",
        trust_remote_code=False,
        token=False,
        local_files_only=offline,
        model_kwargs={"use_safetensors": True},
    )


class LocalSentenceEmbeddings:
    def __init__(self, settings):
        self.model = load_model(
            settings.local_embedding_model,
            settings.local_embedding_revision,
            settings.local_embedding_cache,
            settings.local_embedding_offline,
        )
        self.dimensions = (
            self.model.get_embedding_dimension()
            if hasattr(self.model, "get_embedding_dimension")
            else self.model.get_sentence_embedding_dimension()
        )
        if self.dimensions != 384:
            raise ValueError("The configured local encoder must return 384-dimensional MiniLM vectors")
        fingerprint = hashlib.sha256(
            f"{settings.local_embedding_model}@{settings.local_embedding_revision}".encode()
        ).hexdigest()[:16]
        self.version = f"st:{fingerprint}:384:window-pool-v1"
        self.lock = threading.Lock()

    def windows(self, value):
        tokenizer = self.model.tokenizer
        spans = tokenizer(value, add_special_tokens=False, return_offsets_mapping=True, verbose=False)[
            "offset_mapping"
        ]
        limit = self.model.max_seq_length - tokenizer.num_special_tokens_to_add(pair=False)
        if limit <= 32:
            raise ValueError("Encoder token window is too small")
        if len(spans) <= limit:
            return [value]
        chunks = []
        for start in range(0, len(spans), limit - 32):
            end = min(start + limit, len(spans))
            chunks.append(value[spans[start][0] : spans[end - 1][1]])
            if end == len(spans):
                break
        return chunks

    def embed_documents(self, texts):
        if not texts:
            return []
        # Encode all input, including text beyond MiniLM's 256-token window.
        # Pool normalized overlapping-window vectors; do not silently truncate long runbooks.
        with self.lock:
            groups = [self.windows(text) for text in texts]
            vectors = self.model.encode(
                [part for group in groups for part in group],
                batch_size=32,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        result, cursor = [], 0
        for group in groups:
            parts = vectors[cursor : cursor + len(group)]
            vector = [sum(float(p[i]) for p in parts) / len(parts) for i in range(self.dimensions)]
            norm = math.sqrt(sum(x * x for x in vector))
            if not norm or not all(math.isfinite(x) for x in vector):
                raise ValueError("Local encoder returned an invalid vector")
            result.append([x / norm for x in vector])
            cursor += len(group)
        return result
