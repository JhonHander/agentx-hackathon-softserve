from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any

_REGISTRY_LOCK = Lock()


def _registry_path() -> Path:
    configured = (os.getenv("JIRA_TICKET_REGISTRY_PATH") or "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / "data" / "jira_ticket_registry.json"


def _read_registry() -> dict[str, Any]:
    path = _registry_path()
    if not path.exists():
        return {"tickets": {}}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"tickets": {}}
    if not isinstance(parsed, dict):
        return {"tickets": {}}
    tickets = parsed.get("tickets")
    if not isinstance(tickets, dict):
        parsed["tickets"] = {}
    return parsed


def _write_registry(data: dict[str, Any]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def register_ticket_contact(
    issue_key: str,
    incident_id: Any,
    reporter_email: str,
    issue_url: str | None = None,
) -> None:
    normalized_key = issue_key.strip().upper()
    normalized_email = reporter_email.strip().lower()
    if not normalized_key or not normalized_email:
        return

    with _REGISTRY_LOCK:
        data = _read_registry()
        tickets = data.setdefault("tickets", {})
        tickets[normalized_key] = {
            "incident_id": str(incident_id),
            "reporter_email": normalized_email,
            "issue_url": (issue_url or "").strip() or None,
            "resolved_notified": bool(
                tickets.get(normalized_key, {}).get("resolved_notified", False)
            ),
        }
        _write_registry(data)


def get_ticket_contact(issue_key: str) -> dict[str, Any] | None:
    normalized_key = issue_key.strip().upper()
    if not normalized_key:
        return None

    with _REGISTRY_LOCK:
        data = _read_registry()
        tickets = data.get("tickets")
        if not isinstance(tickets, dict):
            return None
        entry = tickets.get(normalized_key)
        if isinstance(entry, dict):
            return entry
        return None


def mark_resolved_notification_sent(issue_key: str) -> None:
    normalized_key = issue_key.strip().upper()
    if not normalized_key:
        return

    with _REGISTRY_LOCK:
        data = _read_registry()
        tickets = data.setdefault("tickets", {})
        entry = tickets.get(normalized_key)
        if not isinstance(entry, dict):
            return
        entry["resolved_notified"] = True
        tickets[normalized_key] = entry
        _write_registry(data)
