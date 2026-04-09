from __future__ import annotations

import os
from typing import Any

import httpx
try:
    from jira_mcp_client import (
        create_jira_ticket_via_mcp,
        jira_mcp_is_configured,
        mcp_enabled_for_auto_mode,
    )
except ImportError:
    from .jira_mcp_client import (  # type: ignore
        create_jira_ticket_via_mcp,
        jira_mcp_is_configured,
        mcp_enabled_for_auto_mode,
    )

ALLOWED_JIRA_MODES = {"auto", "mcp", "rest", "off"}


def _jira_mode() -> str:
    mode = (os.getenv("JIRA_MODE") or "auto").strip().lower()
    return mode if mode in ALLOWED_JIRA_MODES else "auto"


def _is_rest_configured() -> bool:
    return all(
        [
            os.getenv("JIRA_BASE_URL"),
            os.getenv("JIRA_EMAIL"),
            os.getenv("JIRA_API_TOKEN"),
            os.getenv("JIRA_PROJECT_KEY"),
        ]
    )


def _adf_paragraph(text: str) -> dict[str, Any]:
    return {
        "type": "paragraph",
        "content": [{"type": "text", "text": text}],
    }


def _build_description_adf(
    incident: dict[str, Any], analysis: dict[str, Any], incident_id: Any
) -> dict[str, Any]:
    lines = [
        f"Incident ID: {incident_id}",
        f"Source: {incident.get('source', 'unknown')}",
        f"Page URL: {incident.get('page_url') or 'not provided'}",
        "",
        f"Description: {incident.get('description', '')}",
        f"Expected: {incident.get('expected_result', '')}",
        f"Actual: {incident.get('actual_result', '')}",
        f"Steps to Reproduce: {incident.get('steps_to_reproduce', '')}",
        "",
        "RAG Analysis:",
        analysis.get("summary", ""),
    ]
    return {
        "type": "doc",
        "version": 1,
        "content": [_adf_paragraph(line) for line in lines if line.strip()],
    }


def _create_jira_ticket_via_rest(
    incident: dict[str, Any],
    analysis: dict[str, Any],
    incident_id: Any,
) -> dict[str, Any]:
    if not _is_rest_configured():
        return {
            "created": False,
            "reason": "Jira environment is not configured",
            "issue_key": None,
            "issue_url": None,
        }

    base_url = (os.getenv("JIRA_BASE_URL") or "").rstrip("/")
    email = os.getenv("JIRA_EMAIL") or ""
    api_token = os.getenv("JIRA_API_TOKEN") or ""
    project_key = os.getenv("JIRA_PROJECT_KEY") or ""
    issue_type = os.getenv("JIRA_ISSUE_TYPE", "Bug")
    timeout = float(os.getenv("JIRA_TIMEOUT_SECONDS", "20"))

    summary = f"[Incident #{incident_id}] {incident.get('description', '')}".strip()
    summary = summary[:240] if len(summary) > 240 else summary

    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "description": _build_description_adf(incident, analysis, incident_id),
            "issuetype": {"name": issue_type},
        }
    }

    url = f"{base_url}/rest/api/3/issue"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload, headers=headers, auth=(email, api_token))

    if response.status_code >= 400:
        return {
            "created": False,
            "reason": f"Jira API returned {response.status_code}",
            "details": response.text[:500],
            "issue_key": None,
            "issue_url": None,
        }

    data = response.json()
    issue_key = data.get("key")
    issue_url = f"{base_url}/browse/{issue_key}" if issue_key else None
    return {
        "created": bool(issue_key),
        "issue_key": issue_key,
        "issue_url": issue_url,
        "transport": "rest",
        "raw_response": data,
    }


def create_jira_ticket(
    incident: dict[str, Any],
    analysis: dict[str, Any],
    incident_id: Any,
) -> dict[str, Any]:
    mode = _jira_mode()
    if mode == "off":
        return {
            "created": False,
            "reason": "Jira integration is disabled (JIRA_MODE=off).",
            "issue_key": None,
            "issue_url": None,
            "transport": None,
        }

    errors: list[str] = []

    should_try_mcp = mode == "mcp" or (mode == "auto" and mcp_enabled_for_auto_mode())
    if should_try_mcp:
        configured, config_reason = jira_mcp_is_configured()
        if configured:
            mcp_result = create_jira_ticket_via_mcp(incident, analysis, incident_id)
            if mcp_result.get("created"):
                return mcp_result
            errors.append(str(mcp_result.get("reason") or "Jira MCP failed"))
            if mode == "mcp":
                return mcp_result
        elif mode == "mcp":
            return {
                "created": False,
                "reason": config_reason,
                "issue_key": None,
                "issue_url": None,
                "transport": "mcp",
            }

    if mode in {"rest", "auto"}:
        rest_result = _create_jira_ticket_via_rest(incident, analysis, incident_id)
        if rest_result.get("created"):
            return rest_result
        errors.append(str(rest_result.get("reason") or "Jira REST failed"))
        if mode == "rest":
            return rest_result

    return {
        "created": False,
        "reason": " | ".join(error for error in errors if error).strip()
        or "Jira integration is not configured.",
        "issue_key": None,
        "issue_url": None,
        "transport": "mcp" if should_try_mcp else "rest",
    }
