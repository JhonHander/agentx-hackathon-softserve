"""Centralized Langfuse configuration for the RAG AI agent system.

Provides a single place to initialize the Langfuse SDK and the
LangChain CallbackHandler.  All modules that need observability
import from here so that configuration is consistent and easy to
toggle via environment variables.

Environment variables:
    LANGFUSE_PUBLIC_KEY  – Langfuse project public key.
    LANGFUSE_SECRET_KEY  – Langfuse project secret key.
    LANGFUSE_HOST        – Langfuse server URL (default: http://langfuse:3000).
    LANGFUSE_ENABLED     – Set to "false" to disable tracing entirely.
"""

from __future__ import annotations

import os
from typing import Any

_langfuse_available: bool = False
_langfuse_client: Any = None

try:
    from langfuse import Langfuse, get_client
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

    _langfuse_client = get_client()
    _langfuse_available = True
except ImportError:
    # Fallback for older SDK variants without get_client.
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

        _langfuse_available = True
    except ImportError:
        pass


def langfuse_is_enabled() -> bool:
    """Return True when Langfuse is installed AND explicitly enabled."""
    if not _langfuse_available:
        return False
    enabled = (os.getenv("LANGFUSE_ENABLED", "true")).strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return False
    has_keys = bool(
        os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        and os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    )
    return has_keys


def get_langfuse_host() -> str:
    """Return the Langfuse server URL from env or the Docker default."""
    return (os.getenv("LANGFUSE_HOST") or "http://langfuse:3000").strip()


def _init_langfuse() -> Any:
    """Initialize and return the Langfuse client singleton.

    Safe to call even when Langfuse is disabled – returns None.
    """
    if not langfuse_is_enabled():
        return None
    global _langfuse_client
    if _langfuse_client is not None:
        return _langfuse_client

    # Newer SDK exposes get_client(); older versions require direct construction.
    try:
        _langfuse_client = get_client()
    except NameError:
        _langfuse_client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "").strip(),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", "").strip(),
            host=get_langfuse_host(),
        )
    return _langfuse_client


def get_langfuse_handler() -> Any:
    """Return a Langchain CallbackHandler wired to the current Langfuse config.

    Returns None when Langfuse is disabled so callers can safely skip it.
    """
    if not langfuse_is_enabled():
        return None
    _init_langfuse()
    return LangfuseCallbackHandler()


def flush_langfuse() -> None:
    """Flush any buffered traces to Langfuse.  Call on shutdown."""
    if not langfuse_is_enabled():
        return
    try:
        client = _init_langfuse()
        if client is not None:
            client.flush()
    except Exception:
        pass


def langfuse_session_metadata(
    session_id: str | None, incident_id: Any = None
) -> dict[str, Any]:
    """Build metadata dict to attach to Langfuse traces for a session."""
    meta: dict[str, Any] = {}
    if session_id:
        meta["session_id"] = session_id
    if incident_id is not None:
        meta["incident_id"] = str(incident_id)
    return meta
