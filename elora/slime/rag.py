"""
rag.py — the slime remembers.

ChromaDB-backed semantic retrieval over everything ingested.
vault episodes handle "what happened" — RAG handles "what do I know
about X" queries. The two-layer memory: autobiographical + semantic.
"""

from __future__ import annotations

import hashlib
import os
from typing import Optional


class RagIndex:
    """Persistent semantic vector index for ELORA."""

    def __init__(self, persist_dir: str = ".elora/rag"):
        os.makedirs(persist_dir, exist_ok=True)
        import chromadb
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            "elora_memory",
            metadata={"hnsw:space": "cosine"}
        )

    def index(self, text: str, metadata: Optional[dict] = None) -> str:
        """Indexes a text document/chunk into persistent memory."""
        doc_id = hashlib.sha256(text[:200].encode("utf-8")).hexdigest()[:16]
        self.collection.upsert(
            documents=[text],
            ids=[doc_id],
            metadatas=[metadata or {}]
        )
        return doc_id

    def recall(self, query: str, n: int = 5) -> list[dict]:
        """Recalls relevant document chunks matching the query."""
        if self.collection.count() == 0:
            return []
        effective_n = min(n, self.collection.count())
        results = self.collection.query(query_texts=[query], n_results=effective_n)
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
    parser.add_argument("--query", required=True, help="Query string for semantic recall")
    parser.add_argument("--n", type=int, default=5, help="Max results to recall")
    parser.add_argument("--dir", default=".elora/rag", help="Directory for RAG database")
    args = parser.parse_args()

    rag = RagIndex(persist_dir=args.dir)
    hits = rag.recall(args.query, n=args.n)
    print(json.dumps(hits, indent=2))


if __name__ == "__main__":
    main()
