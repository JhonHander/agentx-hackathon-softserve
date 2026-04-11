# Scaling Strategy

## Scope
This document explains how the application scales, including assumptions and technical decisions.

## Assumptions
- Traffic profile: bursty incident submissions during peak storefront usage.
- Read-heavy operations: search and health checks; write-heavy only at incident confirmation.
- External dependencies (OpenAI, Jira, SMTP) may have variable latency.

## Current Scaling Model
Deployment topology:
- app (EverShop)
- database (PostgreSQL)
- rag-api (FastAPI orchestrator + RAG interface)
- qdrant (vector database)
- rag-indexer (batch/manual profile)

Horizontal scaling candidates:
- app can scale horizontally behind a reverse proxy/load balancer.
- rag-api can scale horizontally if session persistence is externalized.

Vertical scaling candidates:
- qdrant memory/CPU for larger embeddings and higher query concurrency.
- PostgreSQL IOPS for sustained write throughput.

## Technical Decisions
1. Compose overlay split
- Base runtime in docker-compose.yml.
- AI/RAG services in docker-compose.rag.yml.
- Decision: clear separation of concerns and optional AI layer startup.

2. Async post-confirm processing
- Heavy tasks run after confirmation without blocking immediate user acknowledgement.
- Decision: improve perceived latency and UX.

3. MCP-first Jira mode with fallback paths
- Supports auto/mcp/rest modes.
- Decision: deployment flexibility across environments.

4. RAG indexing as batch profile
- rag-indexer runs manually or in scheduled jobs.
- Decision: avoid unnecessary indexing cost on every startup.

## Bottlenecks and Mitigations
Potential bottlenecks:
- LLM latency
- Vector search latency
- Jira/SMTP API latency
- In-memory session storage in single process

Mitigations:
- Move session state to Redis for multi-instance rag-api.
- Queue post-confirm tasks via worker system (Celery/RQ/Sidekiq equivalent).
- Add request timeouts and retry policies per integration.
- Pre-index codebase and ship qdrant snapshot for fast startup.
- Add rate limiting and circuit breakers at API boundary.

## Recommended Next Steps for Production Scale
1. Externalize session state to Redis.
2. Introduce background queue + worker autoscaling.
3. Add metrics/traces (request duration, queue lag, dependency errors).
4. Add structured logs and correlation IDs from app -> rag-api -> external services.
5. Add autoscaling policy based on CPU and p95 latency.
