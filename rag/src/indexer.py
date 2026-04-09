from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from code_splitter import build_splitter
from rag_config import RagConfig


@dataclass
class IndexStats:
    files_seen: int = 0
    files_indexed: int = 0
    chunks_indexed: int = 0


def _is_binary_file(file_path: Path) -> bool:
    try:
        with file_path.open("rb") as source:
            sample = source.read(4096)
            return b"\x00" in sample
    except OSError:
        return True


def _iter_code_files(repo_path: Path, config: RagConfig) -> Iterable[Path]:
    include_extensions = {ext.lower() for ext in config.include_extensions}
    include_filenames = {name for name in config.include_filenames}
    excluded_dirs = {name.lower() for name in config.exclude_dirs}

    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue

        try:
            relative_parts = path.relative_to(repo_path).parts
        except ValueError:
            continue

        if any(part.lower() in excluded_dirs for part in relative_parts):
            continue

        if path.name in include_filenames or path.suffix.lower() in include_extensions:
            yield path


def _load_documents(repo_path: Path, config: RagConfig) -> tuple[list[Document], IndexStats]:
    stats = IndexStats()
    docs: list[Document] = []

    for file_path in _iter_code_files(repo_path, config):
        stats.files_seen += 1

        try:
            if file_path.stat().st_size > config.max_file_bytes:
                continue
        except OSError:
            continue

        if _is_binary_file(file_path):
            continue

        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        if not text.strip():
            continue

        relative = file_path.relative_to(repo_path).as_posix()
        splitter = build_splitter(
            extension=file_path.suffix,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
        )
        chunks = splitter.create_documents([text])
        if not chunks:
            continue

        for chunk_idx, chunk_doc in enumerate(chunks):
            chunk_id = hashlib.sha1(
                f"{relative}:{chunk_idx}:{chunk_doc.page_content}".encode("utf-8")
            ).hexdigest()
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
            raw_start_index = chunk_doc.metadata.get("start_index", 0)
            try:
                start_index = int(raw_start_index)
            except (TypeError, ValueError):
                start_index = 0

            metadata = {
                "source": relative,
                "filename": file_path.name,
                "extension": file_path.suffix.lower(),
                "chunk_index": chunk_idx,
                "start_index": int(start_index),
                "chunk_id": chunk_id,
                "point_id": point_id,
            }
            docs.append(Document(page_content=chunk_doc.page_content, metadata=metadata))

        stats.files_indexed += 1
        stats.chunks_indexed += len(chunks)

    return docs, stats


def _ensure_collection(
    client: QdrantClient,
    config: RagConfig,
    embeddings: OpenAIEmbeddings,
    recreate: bool,
) -> None:
    vector_size = len(embeddings.embed_query("vector-size-probe"))

    if recreate:
        try:
            client.delete_collection(collection_name=config.qdrant_collection)
        except Exception:
            pass
        client.create_collection(
            collection_name=config.qdrant_collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        return

    try:
        client.get_collection(collection_name=config.qdrant_collection)
    except Exception:
        client.create_collection(
            collection_name=config.qdrant_collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


def run_indexing(
    repo_path: str,
    config: RagConfig,
    recreate_collection: bool = True,
    batch_size: int = 64,
) -> dict:
    repository = Path(repo_path).resolve()
    if not repository.exists():
        raise FileNotFoundError(f"Repository path not found: {repository}")

    docs, stats = _load_documents(repository, config)
    if not docs:
        return {
            "repo_path": str(repository),
            "collection": config.qdrant_collection,
            "files_seen": stats.files_seen,
            "files_indexed": stats.files_indexed,
            "chunks_indexed": 0,
            "message": "No indexable documents found.",
        }

    embeddings = OpenAIEmbeddings(model=config.openai_embedding_model)
    client = QdrantClient(url=config.qdrant_url)
    _ensure_collection(client, config, embeddings, recreate_collection)

    vector_store = QdrantVectorStore(
        client=client,
        collection_name=config.qdrant_collection,
        embedding=embeddings,
    )

    for offset in range(0, len(docs), batch_size):
        batch = docs[offset : offset + batch_size]
        ids = [doc.metadata["point_id"] for doc in batch]
        vector_store.add_documents(batch, ids=ids)

    return {
        "repo_path": str(repository),
        "collection": config.qdrant_collection,
        "files_seen": stats.files_seen,
        "files_indexed": stats.files_indexed,
        "chunks_indexed": stats.chunks_indexed,
        "message": "Indexing finished.",
    }
