"""
rag.py — the slime remembers.

ChromaDB-backed semantic retrieval over everything ingested.
vault episodes handle "what happened" — RAG handles "what do I know
about X" queries. The two-layer memory: autobiographical + semantic.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Optional


class LocalHashEmbeddingFunction:
    """Deterministic local embeddings; collection use never triggers a model download."""

    def __init__(self, dimensions: int = 384):
        self.dimensions = max(32, int(dimensions))

    def __call__(self, input):
        return [self._embed(text) for text in input]

    def embed_query(self, input):
        return self(input)

    def _embed(self, text: str) -> list[float]:
        tokens = re.findall(r"[\w]+", str(text).casefold())
        features = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]
        vector = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def name(self) -> str:
        return "elora-local-hash-v1"

    def get_config(self) -> dict:
        return {"dimensions": self.dimensions}

    @staticmethod
    def build_from_config(config: dict):
        return LocalHashEmbeddingFunction(dimensions=config.get("dimensions", 384))


class RagIndex:
    """Persistent semantic vector index for ELORA."""

    def __init__(self, persist_dir: str = ".elora/rag"):
        os.makedirs(persist_dir, exist_ok=True)
        import chromadb
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            "elora_memory",
            metadata={"hnsw:space": "cosine"},
        )
        self.embedder = LocalHashEmbeddingFunction()

    def index(self, text: str, metadata: Optional[dict] = None) -> str:
        """Indexes a text document/chunk into persistent memory."""
        doc_id = hashlib.sha256(text[:200].encode("utf-8")).hexdigest()[:16]
        upsert_args = {
            "documents": [text],
            "ids": [doc_id],
            "embeddings": [self.embedder._embed(text)],
        }
        if metadata:
            upsert_args["metadatas"] = [metadata]
        self.collection.upsert(**upsert_args)
        return doc_id

    def recall(self, query: str, n: int = 5) -> list[dict]:
        """Recalls relevant document chunks matching the query."""
        if self.collection.count() == 0:
            return []
        effective_n = min(n, self.collection.count())
        results = self.collection.query(
            query_embeddings=[self.embedder._embed(query)],
            n_results=effective_n,
        )
        if not results or not results.get("documents") or not results["documents"][0]:
            return []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0] if results.get("metadatas") else [{} for _ in docs]
        dists = results.get("distances", [[]])[0] if results.get("distances") else [0.0 for _ in docs]
        return [
            {"text": doc, "metadata": meta, "distance": dist}
            for doc, meta, dist in zip(docs, metas, dists)
        ]


def main():
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="ELORA RAG Recall")
    parser.add_argument("--query", default="", help="Query string for semantic recall")
    parser.add_argument("--n", type=int, default=5, help="Max results to recall")
    parser.add_argument("--dir", default=".elora/rag", help="Directory for RAG database")
    args = parser.parse_args()

    rag = RagIndex(persist_dir=args.dir)
    query_str = args.query.strip() if args.query else "memory"
    hits = rag.recall(query_str, n=args.n)
    print(json.dumps(hits, indent=2))


if __name__ == "__main__":
    main()
