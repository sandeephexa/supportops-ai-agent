import hashlib
import math
import re
import time
from collections import Counter
from heapq import nlargest

from langchain_openai import OpenAIEmbeddings
from sqlalchemy import select, text

from supportops.db import Document
from supportops.schemas import Evidence
from supportops.security import INJECTION, authorize_account, mask

STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "is",
    "to",
    "of",
    "for",
    "in",
    "on",
    "with",
    "this",
    "that",
    "their",
    "our",
    "please",
    "why",
    "what",
    "since",
}


def tokens(value):
    return [x for x in re.findall(r"[a-z0-9_:]+", value.lower()) if x not in STOP and len(x) > 1]


def demo_embedding(value, dimensions=256):
    # Deliberately a lexical hashing baseline, never presented as semantic embeddings.
    vector = [0.0] * dimensions
    for token, count in Counter(tokens(value)).items():
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += count * (1 if digest[4] % 2 else -1)
    norm = math.sqrt(sum(x * x for x in vector)) or 1
    return [x / norm for x in vector]


def chunk_markdown(markdown, max_words=350):
    if max_words <= 40:
        raise ValueError("Chunk size must exceed the 40-word overlap")
    title = "Runbook"
    section, paragraphs = "Overview", []
    sections = []
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            if paragraphs:
                sections.append((section, "\n".join(paragraphs).strip()))
            section, paragraphs = line[3:].strip(), []
        else:
            paragraphs.append(line)
    if paragraphs:
        sections.append((section, "\n".join(paragraphs).strip()))
    for section, parent in sections:
        if not parent:
            continue
        # Keep paragraphs/procedures together; split very large paragraphs with small overlap.
        words = parent.split()
        for start in range(0, len(words), max_words - 40):
            chunk = " ".join(words[start : start + max_words])
            yield title, section, chunk, parent
            if start + max_words >= len(words):
                break


class Retriever:
    def __init__(self, db, settings, telemetry):
        self.db, self.settings, self.telemetry = db, settings, telemetry
        self.embedder = None
        if settings.embedding_mode == "sentence_transformers":
            from supportops.local_embeddings import LocalSentenceEmbeddings

            self.embedder = LocalSentenceEmbeddings(settings)
        elif settings.mode == "live" and settings.embedding_mode != "local":
            self.embedder = OpenAIEmbeddings(
                model=settings.embedding_model,
                dimensions=256,
                api_key=settings.api_key,
                base_url=settings.base_url,
                request_timeout=15,
                max_retries=1,
            )
        self.version = (
            self.embedder.version
            if settings.embedding_mode == "sentence_transformers"
            else f"{settings.embedding_model}:256"
            if self.embedder
            else "demo-hash:256:v1"
        )
        self.dimensions = 384 if settings.embedding_mode == "sentence_transformers" else 256
        self.semantic = self.embedder is not None
        if db is not None and db.is_postgres:
            with db.session() as session:
                dimension = session.scalar(
                    text(
                        "SELECT atttypmod FROM pg_attribute WHERE attrelid='documents'::regclass AND attname='vector'"
                    )
                )
            if dimension not in (-1, self.dimensions):
                raise ValueError("PostgreSQL vector dimensions require migration: run alembic upgrade head")

    def embed(self, texts):
        return self.embedder.embed_documents(texts) if self.embedder else [demo_embedding(x) for x in texts]

    def ingest(self, path, tenant_id="public", version="3"):
        raw, _ = mask(path.read_text())
        if INJECTION.search(raw):
            raise ValueError("Document quarantined: suspected instructions directed at the agent")
        chunks = list(chunk_markdown(raw))
        vectors = self.embed([f"{title} {section} {content}" for title, section, content, _ in chunks])
        ids = set()
        with self.db.session() as session:
            for index, ((title, section, content, parent), embedding) in enumerate(
                zip(chunks, vectors, strict=True)
            ):
                doc_id = f"{tenant_id}:{path.stem}:v{version}:{index}"
                ids.add(doc_id)
                doc = session.get(Document, doc_id) or Document(id=doc_id)
                doc.tenant_id, doc.title, doc.version, doc.section = tenant_id, title, version, section
                doc.content, doc.parent_content = content, parent
                doc.content_hash = hashlib.sha256(content.encode()).hexdigest()
                doc.embedding, doc.vector, doc.embedding_version = embedding, embedding, self.version
                doc.active, doc.updated_at = True, time.time()
                session.add(doc)
            # Retire removed chunks on re-ingestion, so obsolete evidence cannot linger.
            old = session.scalars(
                select(Document).where(
                    Document.id.startswith(f"{tenant_id}:{path.stem}:v{version}:", autoescape=True)
                )
            ).all()
            for doc in old:
                if doc.id not in ids:
                    doc.active = False
        return sorted(ids)

    def search(self, principal, account_id, query, case_id, limit=5):
        account = authorize_account(self.db, principal, account_id)
        with self.telemetry.span(case_id, "retrieval.hybrid", embedding_version=self.version) as attrs:
            vector = self.embed([query])[0]
            with self.db.session() as session:
                filters = [
                    Document.active.is_(True),
                    Document.tenant_id.in_(["public", principal.tenant_id]),
                    Document.version.in_([account.product_version, "all"]),
                    Document.embedding_version == self.version,
                ]
                if self.db.is_postgres:
                    # Both rankers apply authorization and version constraints before ranking.
                    dense = session.scalars(
                        select(Document)
                        .where(*filters)
                        .order_by(Document.vector.cosine_distance(vector))
                        .limit(30)
                    ).all()
                    lexical = session.scalars(
                        select(Document)
                        .where(*filters)
                        .where(text("to_tsvector('english', content) @@ plainto_tsquery('english', :query)"))
                        .order_by(
                            text(
                                "ts_rank_cd(to_tsvector('english', content), plainto_tsquery('english', :query)) DESC"
                            )
                        )
                        .params(query=query)
                        .limit(30)
                    ).all()
                else:
                    docs = session.scalars(select(Document).where(*filters)).all()
                    dense = nlargest(
                        30,
                        docs,
                        key=lambda d: sum(a * b for a, b in zip(d.embedding, vector, strict=True)),
                    )
                    q = Counter(tokens(query))
                    # Tokenize each document once, not once per query term during sorting.
                    counts = {doc.id: Counter(tokens(doc.content)) for doc in docs}
                    lexical_scores = {
                        doc.id: sum(min(n, counts[doc.id][t]) for t, n in q.items()) for doc in docs
                    }
                    lexical = nlargest(
                        30,
                        (doc for doc in docs if lexical_scores[doc.id]),
                        key=lambda d: lexical_scores[d.id],
                    )
                scores, by_id = {}, {}
                for ranked in [dense, lexical]:
                    for rank, doc in enumerate(ranked):
                        scores[doc.id] = scores.get(doc.id, 0) + 1 / (60 + rank + 1)
                        by_id[doc.id] = doc
                query_terms = set(tokens(query))
                candidates = []
                for doc_id, score in scores.items():
                    doc = by_id[doc_id]
                    if INJECTION.search(doc.content):
                        continue
                    # Deterministic cosine/keyword reranking; no trained cross-encoder.
                    overlap = len(query_terms & set(tokens(doc.content + " " + doc.section)))
                    if overlap == 0 and not self.semantic:
                        continue
                    semantic_score = (
                        sum(a * b for a, b in zip(doc.embedding, vector, strict=True)) if self.semantic else 0
                    )
                    candidates.append(
                        (
                            score
                            + max(0, semantic_score) * 0.1
                            + overlap * (0.0003 if self.semantic else 0.003),
                            doc,
                        )
                    )
                candidates.sort(key=lambda pair: pair[0], reverse=True)
                evidence, seen = [], set()
                for score, doc in candidates:
                    group = (doc.title, doc.section)
                    if group in seen:
                        continue
                    seen.add(group)
                    content, _ = mask(doc.parent_content)
                    evidence.append(
                        Evidence(
                            id=doc.id,
                            source="runbook",
                            title=f"{doc.title} · {doc.section}",
                            content=content,
                            version=doc.version,
                            observed_at=doc.updated_at,
                            score=round(score, 4),
                        ).model_dump()
                    )
                    if len(evidence) >= limit:
                        break
            attrs.update(
                candidate_count=len(by_id),
                selected_count=len(evidence),
                index_version="runbooks-v2",
                embedding_dimensions=self.dimensions,
                semantic=self.semantic,
            )
            return evidence


def pack_context(evidence, max_tokens, query=""):
    # Conservative UTF-8 byte bound avoids tokenizer downloads in offline demo mode.
    # Extractive compression preserves exact source text for quote verification.
    remaining = max_tokens
    selected = []
    query_terms = set(tokens(query))
    for item in evidence:
        content = item["content"]
        cost = len(content.encode("utf-8")) + 200
        if cost > remaining and item["source"] == "runbook" and remaining > 500:
            sentences = re.split(r"(?<=[.!?])\s+|\n", content)
            ranked = sorted(
                enumerate(sentences),
                key=lambda pair: (
                    bool(re.search(r"never|warning|must|do not|only|unless", pair[1], re.I)),
                    len(query_terms & set(tokens(pair[1]))),
                ),
                reverse=True,
            )
            chosen, available = [], remaining - 200
            for index, sentence in ranked:
                size = len(sentence.encode("utf-8")) + 1
                if size <= available:
                    chosen.append((index, sentence))
                    available -= size
            if chosen:
                content = "\n".join(sentence for _, sentence in sorted(chosen))
                cost = len(content.encode("utf-8")) + 200
        if cost <= remaining:
            selected.append({**item, "content": content})
            remaining -= cost
    return selected
