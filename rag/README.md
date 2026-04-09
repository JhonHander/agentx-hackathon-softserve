# Codebase RAG with Qdrant + LangChain

This module indexes the full EverShop codebase into Qdrant so an agent can retrieve relevant code chunks for bug triage.

## What is included

- `src/index_codebase.py`: CLI to index repository files.
- `src/search_codebase.py`: CLI semantic search over indexed chunks.
- `src/api.py`: FastAPI service with:
  - `POST /search`
  - `POST /reindex`
  - `GET /health`
- `../docker-compose.rag.yml`: Compose overlay with `qdrant`, `rag-api`, and `rag-indexer`.

## 1) Environment variables

Create a `.env` in the `evershop` root (or export variables in shell):

```bash
OPENAI_API_KEY=your_openai_api_key
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
RAG_CHUNK_SIZE=1200
RAG_CHUNK_OVERLAP=200
RAG_MAX_FILE_BYTES=800000
```

## 2) Start services

From `evershop/`:

```bash
docker compose -f docker-compose.yml -f docker-compose.rag.yml up -d qdrant rag-api
```

This exposes:

- Qdrant REST: `http://localhost:6333`
- RAG API: `http://localhost:8008`

## 3) Index the codebase

One-time full reindex (recreates collection):

```bash
docker compose -f docker-compose.yml -f docker-compose.rag.yml --profile manual run --rm rag-indexer
```

If you want to append instead of recreate:

```bash
docker compose -f docker-compose.yml -f docker-compose.rag.yml --profile manual run --rm rag-indexer python /app/src/index_codebase.py --repo-path /workspace/repo --append
```

## 4) Query from an agent

Example:

```bash
curl -X POST http://localhost:8008/search \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"checkout fails when applying coupon\", \"k\": 8}"
```

The response returns chunk content and metadata (`source`, `chunk_index`, `start_index`) so your agent can cite candidate files to inspect.

## 5) Suggested bug-triage flow

1. Agent receives bug report text.
2. Agent calls `/search` with the bug description and error traces.
3. Agent groups top chunks by `source`.
4. Agent recommends likely root-cause files and exact sections to review first.

## 6) Ship pre-indexed data (no waiting on first run)

If you want other users to run the system without waiting for indexing, distribute a backup of the Qdrant volume.

### On the build machine (index once + export)

```powershell
docker compose -f docker-compose.yml -f docker-compose.rag.yml up -d qdrant rag-api
docker compose -f docker-compose.yml -f docker-compose.rag.yml --profile manual run --rm rag-indexer
.\rag\scripts\backup-qdrant.ps1 -OutputDir . -ArchiveName qdrant-storage.tgz
```

Share `qdrant-storage.tgz` with your deliverable package.

### On the target machine (restore + run)

```powershell
.\rag\scripts\restore-qdrant.ps1 -ArchivePath .\qdrant-storage.tgz
docker compose -f docker-compose.yml -f docker-compose.rag.yml up -d qdrant rag-api
```

Now users can query `/search` immediately without re-indexing.

## Notes

- File filtering is controlled by `rag_config.py` (`extensions`, `filenames`, excluded dirs).
- Splitting uses `RecursiveCharacterTextSplitter.from_language(...)` when file extension maps to a known language, with fallback generic recursive splitting.
- Current embedding provider is OpenAI embeddings (`langchain-openai`).
