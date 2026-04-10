# Langfuse Observability — Deployment Guide

## What This Gives You

Langfuse provides **full tracing** of the AI agent pipeline. Each incident flow from
intake → triage → RAG analysis → Jira ticket → email notification is captured as a
trace with nested spans, so you can inspect latency, token usage, and errors per step
in a web dashboard.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  EverShop UI │────▶│   rag-api    │────▶│   Langfuse   │
│  (port 3000) │     │  (port 8008) │     │  (port 3010) │
└──────────────┘     └──────────────┘     └──────────────┘
                            │                     │
                     ┌──────┴──────┐       ┌──────┴──────┐
                     │   Qdrant    │       │ langfuse-db │
                     │  (port 6333)│       │  (Postgres) │
                     └─────────────┘       └─────────────┘
```

All services run in Docker Compose on the `MyEverShop` network.

## Quick Start

### 1. Configure environment

Copy the Langfuse section from `rag/.env.example` into your `rag/.env` (or root `.env`):

```bash
LANGFUSE_PUBLIC_KEY=pk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LANGFUSE_SECRET_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LANGFUSE_HOST=http://langfuse:3000
LANGFUSE_ENABLED=true
```

The keys will be generated in step 3 below.

### 2. Start all services

```bash
docker compose -f docker-compose.yml -f docker-compose.rag.yml up -d --build
```

This brings up: `app`, `database`, `qdrant`, `langfuse`, `langfuse-db`, `rag-api`.

### 3. Create a Langfuse project and get API keys

1. Open **http://localhost:3010** in your browser.
2. Create your first user account (sign up).
3. Create a new project (e.g. "EverShop SRE Agent").
4. Go to **Settings → API Keys** and copy the **Public Key** and **Secret Key**.
5. Set those values in your `.env` file:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...your-key...
LANGFUSE_SECRET_KEY=sk-lf-...your-secret...
```

### 4. Restart rag-api to pick up the new keys

```bash
docker compose -f docker-compose.yml -f docker-compose.rag.yml restart rag-api
```

### 5. Verify

Submit an incident through the EverShop UI. Then go to
**http://localhost:3010** → your project → **Traces**. You should see a trace for
each `/agents/orchestrator/message` call, with nested spans for:

| Span Name                         | What it traces                               |
|-----------------------------------|-----------------------------------------------|
| `api_orchestrator_message`        | Full HTTP request to the orchestrator         |
| `orchestrator_handle_message`      | Top-level orchestrator session handler         |
| `orchestrator_agent_node`          | LangGraph agent node (LLM conversation turn)  |
| `orchestrator_conversational_turn` | Single LLM call for conversational triage     |
| `orchestrator_infer_missing_details` | LLM call to fill in missing incident fields   |
| `orchestrator_classify_priority`   | LLM call for priority classification           |
| `orchestrator_analyze_images`      | Multimodal LLM call for image analysis         |
| `orchestrator_save_and_analyze`    | Full save pipeline (incident + RAG + Jira + email) |
| `orchestrator_save_node`           | LangGraph save node                            |
| `analysis_rag_analysis`            | RAG code search + LLM synthesis               |
| `analysis_synthesize_llm`          | LLM call to synthesize analysis from RAG chunks |
| `jira_create_ticket`              | Jira ticket creation (REST or MCP)             |
| `notification_ticket_opened`      | Email notification on ticket creation           |
| `notification_ticket_resolved`    | Email notification on ticket resolution          |
| `incident_create_report`           | HTTP POST to EverShop incident API               |
| `incident_create_recommendation`   | HTTP POST to EverShop recommendation API          |
| `api_jira_webhook`                | Jira webhook for resolved-ticket notifications  |

## Disabling Langfuse

Set `LANGFUSE_ENABLED=false` (or remove the keys). All `@observe` decorators become
no-ops and the CallbackHandler is skipped — zero overhead.

## Langfuse Dashboard Tips

- **Latency breakdown**: Click a trace → see which spans are slow.
- **Token cost**: Each LLM span shows input/output tokens and estimated cost.
- **Filter by session**: Use `session_id` tags to trace a single conversation.
- **Scores**: You can add custom scores from your code or from user feedback.

## Environment Variables Reference

| Variable                  | Default                     | Description                              |
|---------------------------|-----------------------------|------------------------------------------|
| `LANGFUSE_PUBLIC_KEY`     | (required)                  | Project public key from Langfuse UI       |
| `LANGFUSE_SECRET_KEY`     | (required)                  | Project secret key from Langfuse UI       |
| `LANGFUSE_HOST`           | `http://langfuse:3000`       | Langfuse server URL                       |
| `LANGFUSE_ENABLED`        | `true`                       | Set to `false` to disable tracing          |
| `LANGFUSE_NEXTAUTH_SECRET`| `my-secret-change-me`        | NextAuth secret for Langfuse UI (change!) |
| `LANGFUSE_SALT`            | `my-salt-change-me`          | Salt for Langfuse (change!)               |
| `LANGFUSE_NEXTAUTH_URL`   | `http://localhost:3010`      | Public URL for Langfuse UI                |
| `LANGFUSE_HOST_PORT`       | `3010`                       | Host port mapping for Langfuse UI         |

## Troubleshooting

- **No traces appear**: Check `LANGFUSE_ENABLED=true` and that keys are set.
  Inspect `rag-api` logs for `langfuse` errors.
- **Connection refused to langfuse:3000**: Ensure the `langfuse` service is healthy
  (`docker compose -f docker-compose.yml -f docker-compose.rag.yml ps`).
- **Keys not accepted**: Make sure you copied the full `pk-lf-...` and `sk-lf-...`
  strings without trailing whitespace.