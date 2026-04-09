from __future__ import annotations

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from rag_config import RagConfig


def get_vector_store(config: RagConfig) -> QdrantVectorStore:
    embeddings = OpenAIEmbeddings(model=config.openai_embedding_model)
    client = QdrantClient(url=config.qdrant_url)
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
