from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from indexer import run_indexing
from rag_config import RagConfig
from retriever import search_code_chunks

app = FastAPI(title="Codebase RAG API", version="1.0.0")


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, description="Bug description or developer query.")
    k: int = Field(default=8, ge=1, le=30, description="Number of chunks to return.")


class ReindexRequest(BaseModel):
    repo_path: str = Field(
        default="/workspace/repo",
        description="Absolute path mounted in the container with repository sources.",
    )
    append: bool = Field(
        default=False, description="If true, do not recreate the collection."
    )
    batch_size: int = Field(default=64, ge=8, le=256)


@app.get("/health")
def health() -> dict[str, Any]:
    config = RagConfig.from_env()
    return {
        "ok": True,
        "collection": config.qdrant_collection,
        "qdrant_url": config.qdrant_url,
        "embedding_model": config.openai_embedding_model,
        "repo_path_default": os.getenv("RAG_REPO_PATH", "/workspace/repo"),
    }


@app.post("/search")
def search(request: SearchRequest) -> dict[str, Any]:
    config = RagConfig.from_env()
    try:
        hits = search_code_chunks(query=request.query, config=config, k=request.k)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "query": request.query,
        "k": request.k,
        "collection": config.qdrant_collection,
        "results": hits,
    }


@app.post("/reindex")
def reindex(request: ReindexRequest) -> dict[str, Any]:
    config = RagConfig.from_env()
    try:
        result = run_indexing(
            repo_path=request.repo_path,
            config=config,
            recreate_collection=not request.append,
            batch_size=request.batch_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result
