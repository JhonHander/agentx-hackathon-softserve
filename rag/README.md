# Codebase RAG with Qdrant + LangChain

This module indexes the full EverShop codebase into Qdrant so an agent can retrieve relevant code chunks for bug triage.

## MVP local (no Docker) - Orchestrator with LangGraph

For the first MVP agent, you can run only the conversational orchestrator with OpenAI API and save incidents into EverShop DB.

1. Start EverShop app normally (local).
2. Create and activate a virtual environment (recommended):
   ```powershell
   py -3 -m venv rag/.venv
   .\rag\.venv\Scripts\Activate.ps1
   ```
3. Install Python deps inside the venv:
   ```bash
   pip install -r rag/requirements.txt
   ```
4. Run FastAPI locally:
   ```bash
   python -m uvicorn api:app --app-dir rag/src --host 0.0.0.0 --port 8008 --reload
   ```
5. Optional env in EverShop app (if you want explicit URL):
   ```bash
   RAG_ORCHESTRATOR_MESSAGE_URL=http://localhost:8008/agents/orchestrator/message
   ```
6. Use a real OpenAI key (not placeholder values like `TU_API_KEY`).

The orchestrator flow now does:
- Conversational data collection
- Required email validation
- Priority classification (high/low)
- Save incident in DB after user confirms (`confirmar`)

Notes:
- Recommended Python for LangGraph/LangChain in this MVP: 3.12.
- Python 3.14 can show compatibility warnings from transitive dependencies.

## What is included

- `src/index_codebase.py`: CLI to index repository files.
- `src/search_codebase.py`: CLI semantic search over indexed chunks.
- `src/api.py`: FastAPI service with:
  - `POST /search`
  - `POST /reindex`
  - `GET /health`
  - `POST /agents/orchestrator/message`
  - `POST /agents/orchestrator/reset`
- `../docker-compose.rag.yml`: Compose overlay with `qdrant`, `rag-api`, and `rag-indexer`.

## 1) Environment variables

Create a `.env` in the `evershop` root (or export variables in shell):

```bash
OPENAI_API_KEY=your_openai_api_key
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
INCIDENT_API_URL=http://app:3000/api/incidents
ORCHESTRATOR_RAG_TOP_K=8
JIRA_BASE_URL=
JIRA_EMAIL=
JIRA_API_TOKEN=
JIRA_PROJECT_KEY=
JIRA_ISSUE_TYPE=Bug
JIRA_MODE=auto
JIRA_MCP_ENABLED=true
JIRA_MCP_TRANSPORT=streamable_http
JIRA_MCP_URL=https://mcp.atlassian.com/v1/mcp
JIRA_MCP_TOOL_CREATE_ISSUE=createJiraIssue
# Optional auth/header values depending on MCP server:
JIRA_MCP_BEARER_TOKEN=
JIRA_MCP_HEADERS_JSON=
# Optional stdio transport (local VS-like MCP config):
JIRA_MCP_COMMAND=
JIRA_MCP_ARGS=-y,mcp-remote,https://mcp.atlassian.com/v1/mcp
JIRA_WEBHOOK_ENABLED=true
JIRA_WEBHOOK_SECRET=
JIRA_DONE_STATUS_NAMES=done,resolved,closed,finalizado,terminado
JIRA_TICKET_REGISTRY_PATH=/app/data/jira_ticket_registry.json
REPORTER_EMAIL_NOTIFICATIONS_ENABLED=true
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_FROM_NAME=EverShop Support
SMTP_REPLY_TO=
SMTP_USE_TLS=true
SMTP_USE_SSL=false
RAG_CHUNK_SIZE=1200
RAG_CHUNK_OVERLAP=200
RAG_MAX_FILE_BYTES=800000
```

Notes:

- For containerized runs, keep `JIRA_TICKET_REGISTRY_PATH=/app/data/jira_ticket_registry.json` so ticket/contact mapping survives restarts.
- `docker-compose.rag.yml` mounts a named volume at `/app/data` for this registry.

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

## 6) Orchestrator agent flow (collect -> classify -> save)

The orchestrator endpoint manages a session:

1. Collect required incident fields in chat:
   - description
   - expected_result
   - actual_result
   - steps_to_reproduce
   - reporter_email (validated)
   - priority_level (`high` or `low`) + short reason
2. Show a summary and wait for user confirmation (`"confirmar"`).
3. Call `INCIDENT_API_URL` to persist incident in DB.
4. Run RAG analysis and persist recommendations.
5. Try Jira ticket creation:
   - `JIRA_MODE=mcp`: only MCP.
   - `JIRA_MODE=rest`: only Jira REST API env vars.
   - `JIRA_MODE=auto`: MCP first, REST fallback.
6. Return final payload to front-end (`incident_id`, `priority`, `analysis`, `jira`).

For EverShop UI integration, use the app proxy endpoint:

- `POST /incidents/orchestrator/message` (inside EverShop app)
- The app forwards requests to `rag-api` (`/agents/orchestrator/message`).

Example conversation call:

```bash
curl -X POST http://localhost:8008/agents/orchestrator/message \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"No puedo aplicar cupon en checkout\",\"source\":\"frontStore\",\"page_url\":\"https://demo.local/checkout\"}"
```

Use the returned `session_id` in subsequent messages.

Confirm submit:

```bash
curl -X POST http://localhost:8008/agents/orchestrator/message \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"<SESSION_ID>\",\"message\":\"confirmar\"}"
```

## 7) Ship pre-indexed data (no waiting on first run)

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
