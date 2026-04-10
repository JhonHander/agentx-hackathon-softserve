from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from langfuse_config import flush_langfuse, langfuse_is_enabled

if langfuse_is_enabled():
    from langfuse import observe
else:

    def observe(**_kwargs):  # type: ignore[misc]
        """No-op decorator when Langfuse is disabled."""

        def _wrapper(func):
            return func

        return _wrapper


PLACEHOLDER_API_KEYS = {"TU_API_KEY", "your_openai_api_key", "YOUR_OPENAI_API_KEY"}


def _load_local_env() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    root_env = repo_root / ".env"
    rag_env = repo_root / "rag" / ".env"

    # First pass: keep existing environment values.
    load_dotenv(root_env, override=False)
    load_dotenv(rag_env, override=False)

    # If OPENAI_API_KEY is missing or clearly a placeholder, force values from .env files.
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key or key in PLACEHOLDER_API_KEYS:
        load_dotenv(root_env, override=True)
        load_dotenv(rag_env, override=True)


_load_local_env()

from indexer import run_indexing
from jira_ticket_registry import (
    get_ticket_contact,
    mark_resolved_notification_sent,
)
from orchestrator_service import handle_message, reset_session
from reporter_notification import send_ticket_resolved_email
from qdrant_client import QdrantClient
from rag_config import RagConfig
from retriever import search_code_chunks

app = FastAPI(title="Codebase RAG API", version="1.0.0")


@app.on_event("shutdown")
def _shutdown_langfuse() -> None:
    """Flush any remaining Langfuse traces before the server shuts down."""
    flush_langfuse()


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


class OrchestratorMessageRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(default="", max_length=4000)
    source: str | None = None
    page_url: str | None = None
    reporter_name: str | None = None
    reporter_email: str | None = None
    attachments_base64: list[dict[str, Any]] | None = None


class OrchestratorResetRequest(BaseModel):
    session_id: str = Field(min_length=1)


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "si", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _jira_done_statuses() -> set[str]:
    raw = (
        os.getenv("JIRA_DONE_STATUS_NAMES")
        or "done,resolved,closed,finalizado,terminado"
    ).strip()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _extract_issue_key(payload: dict[str, Any]) -> str | None:
    issue = payload.get("issue")
    if isinstance(issue, dict):
        key = issue.get("key")
        if isinstance(key, str) and key.strip():
            return key.strip().upper()
    data = payload.get("data")
    if isinstance(data, dict):
        key = data.get("issueKey") or data.get("issue_key")
        if isinstance(key, str) and key.strip():
            return key.strip().upper()
    direct = payload.get("issue_key")
    if isinstance(direct, str) and direct.strip():
        return direct.strip().upper()
    return None


def _extract_status_name(payload: dict[str, Any]) -> str | None:
    issue = payload.get("issue")
    if isinstance(issue, dict):
        fields = issue.get("fields")
        if isinstance(fields, dict):
            status = fields.get("status")
            if isinstance(status, dict):
                name = status.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        status = data.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip()
    direct = payload.get("status")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    return None


def _status_category_is_done(payload: dict[str, Any]) -> bool:
    issue = payload.get("issue")
    if not isinstance(issue, dict):
        return False
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return False
    status = fields.get("status")
    if not isinstance(status, dict):
        return False
    category = status.get("statusCategory")
    if not isinstance(category, dict):
        return False
    key = str(category.get("key") or "").strip().lower()
    return key == "done"


@app.get("/health")
def health() -> dict[str, Any]:
    config = RagConfig.from_env()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    qdrant_reachable = False
    qdrant_error: str | None = None
    try:
        client = QdrantClient(url=config.qdrant_url, timeout=2.0)
        client.get_collections()
        qdrant_reachable = True
    except Exception as exc:
        qdrant_error = str(exc)
    jira_mode = (os.getenv("JIRA_MODE") or "auto").strip().lower()
    jira_transport = (
        (os.getenv("JIRA_MCP_TRANSPORT") or "streamable_http").strip().lower()
    )
    jira_rest_configured = bool(
        os.getenv("JIRA_BASE_URL")
        and os.getenv("JIRA_EMAIL")
        and os.getenv("JIRA_API_TOKEN")
        and os.getenv("JIRA_PROJECT_KEY")
    )
    jira_mcp_configured = bool(
        (jira_transport == "stdio" and os.getenv("JIRA_MCP_COMMAND"))
        or (
            jira_transport != "stdio"
            and (os.getenv("JIRA_MCP_URL") or "https://mcp.atlassian.com/v1/mcp")
        )
    )
    jira_webhook_enabled = _parse_bool(os.getenv("JIRA_WEBHOOK_ENABLED"), default=True)

    return {
        "ok": True,
        "collection": config.qdrant_collection,
        "qdrant_url": config.qdrant_url,
        "qdrant_reachable": qdrant_reachable,
        "qdrant_error": qdrant_error,
        "embedding_model": config.openai_embedding_model,
        "openai_api_key_loaded": bool(
            openai_key and openai_key not in PLACEHOLDER_API_KEYS
        ),
        "repo_path_default": os.getenv("RAG_REPO_PATH", "/workspace/repo"),
        "incident_api_url": os.getenv(
            "INCIDENT_API_URL", "http://app:3000/api/incidents"
        ),
        "jira_mode": jira_mode,
        "jira_transport": jira_transport,
        "jira_rest_configured": jira_rest_configured,
        "jira_mcp_configured": jira_mcp_configured,
        "jira_configured": jira_rest_configured or jira_mcp_configured,
        "jira_webhook_enabled": jira_webhook_enabled,
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


@observe(name="api_orchestrator_message")
def _orchestrator_message_observed(payload: dict[str, Any]) -> dict[str, Any]:
    return handle_message(payload)


@app.post("/agents/orchestrator/message")
def orchestrator_message(request: OrchestratorMessageRequest) -> dict[str, Any]:
    try:
        return _orchestrator_message_observed(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/agents/orchestrator/reset")
def orchestrator_reset(request: OrchestratorResetRequest) -> dict[str, Any]:
    try:
        return reset_session(request.session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@observe(name="api_jira_webhook")
def _jira_webhook_observed(
    payload: dict[str, Any],
    x_jira_webhook_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    if not _parse_bool(os.getenv("JIRA_WEBHOOK_ENABLED"), default=True):
        return {"ok": True, "skipped": True, "reason": "Webhook disabled"}

    expected_token = (os.getenv("JIRA_WEBHOOK_SECRET") or "").strip()
    provided_token = (x_jira_webhook_token or "").strip() or (token or "").strip()
    if expected_token and provided_token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    issue_key = _extract_issue_key(payload)
    if not issue_key:
        return {"ok": True, "skipped": True, "reason": "Issue key not found"}

    status_name = (_extract_status_name(payload) or "").strip()
    is_done = (
        _status_category_is_done(payload)
        or status_name.lower() in _jira_done_statuses()
    )
    if not is_done:
        return {
            "ok": True,
            "issue_key": issue_key,
            "status": status_name or None,
            "skipped": True,
            "reason": "Status is not final",
        }

    entry = get_ticket_contact(issue_key)
    if not entry:
        return {
            "ok": True,
            "issue_key": issue_key,
            "status": status_name or None,
            "skipped": True,
            "reason": "Ticket not registered locally",
        }

    if bool(entry.get("resolved_notified")):
        return {
            "ok": True,
            "issue_key": issue_key,
            "status": status_name or None,
            "skipped": True,
            "reason": "Resolved notification already sent",
        }

    reporter_email = str(entry.get("reporter_email") or "").strip()
    incident_id = entry.get("incident_id")
    issue_url = str(entry.get("issue_url") or "").strip() or None

    send_result = send_ticket_resolved_email(
        reporter_email=reporter_email,
        incident_id=incident_id,
        issue_key=issue_key,
        issue_url=issue_url,
    )
    if send_result.get("sent"):
        mark_resolved_notification_sent(issue_key)

    return {
        "ok": True,
        "issue_key": issue_key,
        "status": status_name or None,
        "notification": send_result,
    }


@app.post("/jira/webhook")
def jira_webhook(
    payload: dict[str, Any],
    x_jira_webhook_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    return _jira_webhook_observed(payload, x_jira_webhook_token, token)
