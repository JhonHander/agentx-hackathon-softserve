from __future__ import annotations

import os

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from rag_config import RagConfig


def _candidate_qdrant_urls(config: RagConfig) -> list[str]:
    configured = (config.qdrant_url or "").strip()
    extra = [
        "http://localhost:6333",
        "http://127.0.0.1:6333",
        "http://qdrant:6333",
    ]
    if configured:
        ordered = [configured] + [url for url in extra if url != configured]
    else:
        ordered = extra

    override = (os.getenv("QDRANT_URL_FALLBACKS") or "").strip()
    if override:
        extra_overrides = [item.strip() for item in override.split(",") if item.strip()]
        for url in extra_overrides:
            if url not in ordered:
                ordered.append(url)
    return ordered


def get_vector_store(config: RagConfig) -> QdrantVectorStore:
    embeddings = OpenAIEmbeddings(model=config.openai_embedding_model)
    last_error: Exception | None = None
    client: QdrantClient | None = None
    for url in _candidate_qdrant_urls(config):
        try:
            candidate = QdrantClient(url=url, timeout=2.0)
            candidate.get_collections()
            client = candidate
            break
        except Exception as exc:
            last_error = exc
            continue

    if client is None:
        raise RuntimeError(f"Could not connect to Qdrant: {last_error}")

    return QdrantVectorStore(
        client=client,
        collection_name=config.qdrant_collection,
        embedding=embeddings,
    )


def search_code_chunks(
    query: str,
    config: RagConfig,
    k: int = 8,
) -> list[dict]:
    store = get_vector_store(config)
    docs_with_scores = store.similarity_search_with_score(query=query, k=k)
    results: list[dict] = []

    for doc, score in docs_with_scores:
        metadata = doc.metadata or {}
        results.append(
            {
                "score": float(score),
                "source": metadata.get("source"),
                "filename": metadata.get("filename"),
                "extension": metadata.get("extension"),
                "chunk_index": metadata.get("chunk_index"),
                "start_index": metadata.get("start_index"),
                "content": doc.page_content,
            }
        )

    return results
