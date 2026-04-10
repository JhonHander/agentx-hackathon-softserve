# Incident Triage Copilot for EverShop

## Project Summary
This project extends EverShop with an AI-assisted incident intake and triage workflow.

Users can report incidents from the storefront, and an orchestrator agent:
- gathers the minimum required data conversationally,
- validates reporter email,
- confirms details with the user,
- saves the incident,
- runs technical codebase analysis (RAG),
- creates a Jira ticket,
- and sends reporter notifications.

The user-facing flow is intentionally minimal and safe:
- English-only responses,
- no exposure of internal priority, retrieval, or tool outputs,
- final acknowledgement confirms the issue is being worked on.

## Architecture Overview
Main runtime components:
- app: EverShop Node.js web application (UI + API proxy route).
- database: PostgreSQL for EverShop data.
- qdrant: Vector store for code chunks.
- rag-api: FastAPI service hosting orchestrator, RAG search, and webhook endpoints.
- rag-indexer: One-shot indexing job for repository ingestion.

High-level request flow:
1. User submits incident through EverShop UI.
2. EverShop app proxies request to rag-api orchestrator endpoint.
3. Orchestrator collects/validates incident details and asks for confirmation.
4. On confirmation, incident is persisted, RAG analysis runs, Jira ticket is created, and email notifications are triggered.
5. User gets concise confirmation message.

Relevant compose files:
- docker-compose.yml: base app + database.
- docker-compose.rag.yml: qdrant + rag-api + rag-indexer overlay.

## Setup Instructions
Prerequisites:
- Docker + Docker Compose
- Optional local Python 3.11+ (for non-container FastAPI runs)

1. Copy environment template:
- cp .env.example .env

2. Fill required secrets in .env:
- OPENAI_API_KEY
- JIRA_* credentials
- SMTP_* credentials (if notifications enabled)

3. Start stack with RAG overlay:
- docker compose -f docker-compose.yml -f docker-compose.rag.yml up -d --build

4. (Optional but recommended) build code index:
- docker compose -f docker-compose.yml -f docker-compose.rag.yml --profile manual run --rm rag-indexer

5. Verify health:
- GET http://localhost:8008/health
- Open app at http://localhost:3000

## Repository Deliverables
This repository includes required handoff documents:
- README.md
- AGENTS_USE.md
- SCALING.md
- QUICKGUIDE.md
- docker-compose.yml
- .env.example
- LICENSE (MIT)

## Notes
- The orchestrator now includes prompt-injection guardrails (pattern detection, sanitization, and prompt-level instruction hardening).
- The post-confirmation pipeline runs asynchronously to keep user response latency low.
