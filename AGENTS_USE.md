# AGENTS_USE

This document describes how agents are used in this project, including implementation, observability, and safety controls.

Reference: https://docs.anthropic.com/en/docs/agents-use-md

## 1. Agent Use Cases
Primary agent: incident orchestrator in rag-api.

Use cases:
- Conversational incident intake from storefront users.
- Data completion (expected result, actual result, steps) when user input is incomplete.
- Priority classification (internal only).
- Technical triage via codebase RAG (internal only).
- Jira ticket creation (MCP-first, REST fallback depending on configuration).
- Reporter notification by email on ticket open and resolved states.

Non-goals for user output:
- Do not expose retrieval internals.
- Do not expose priority details.
- Do not expose Jira internal processing metadata.

## 2. Implementation Details
Core files:
- rag/src/orchestrator_service.py: conversational state machine, guardrails, background post-submit processing.
- rag/src/analysis_agent.py: code retrieval + LLM synthesis for fix suggestions.
- rag/src/jira_agent.py and rag/src/jira_mcp_client.py: Jira integration logic.
- rag/src/reporter_notification.py: SMTP notifications.
- rag/src/api.py: FastAPI endpoints and webhook handling.

State model:
- collecting -> awaiting_confirmation -> completed

Completion behavior:
- After user confirmation, heavy processing is started asynchronously to reduce response latency.

## 3. Observability Evidence
Health and runtime inspection:
- GET /health returns service, vector DB, and integration readiness metadata.
- Response payloads include session status transitions (collecting, ready_to_submit, completed).
- Jira webhook endpoint returns explicit skip/ok reasons for transition processing.

How to verify:
1. Start stack with Docker Compose.
2. Call /health and confirm qdrant_reachable and key config flags.
3. Submit an incident through orchestrator endpoint.
4. Confirm response transitions and final acknowledgement.
5. Trigger webhook payload and inspect skip/sent statuses.

## 4. Safety Measures
Prompt-injection guardrails in orchestrator_service.py:
- Input sanitization before LLM invocation.
- Pattern-based injection detection for role override and prompt exfiltration attempts.
- Prompt-level hard rules to ignore role-change and hidden-instruction requests.
- User-facing response minimization to avoid leaking internal chain behavior.

Data minimization:
- User summary before submit includes only description and reporter email.
- Final response is a concise acknowledgement without internal telemetry.

Operational safeguards:
- Required-field validation (description + valid email).
- Session lock for in-memory consistency.
- Config-based integration toggles and fail-safe paths.
