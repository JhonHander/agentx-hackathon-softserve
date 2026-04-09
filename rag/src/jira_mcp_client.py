from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

import httpx

ISSUE_KEY_REGEX = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
ISSUE_URL_REGEX = re.compile(r"https?://[^\s)]+/browse/[A-Z][A-Z0-9]+-\d+", re.IGNORECASE)
DEFAULT_MCP_URL = "https://mcp.atlassian.com/v1/mcp"
DEFAULT_TOOL_NAME = "createJiraIssue"


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "si", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _exception_to_text(exc: Exception) -> str:
    nested = getattr(exc, "exceptions", None)
    if isinstance(nested, (list, tuple)) and nested:
        parts = [
            _exception_to_text(item)
            for item in nested[:3]
            if isinstance(item, Exception)
        ]
        compact = " | ".join(part for part in parts if part)
        if compact:
            return compact

    message = str(exc).strip()
    if message and "unhandled errors in a TaskGroup" not in message:
        return message
    if getattr(exc, "__cause__", None):
        return _exception_to_text(exc.__cause__)  # type: ignore[arg-type]
    return message or exc.__class__.__name__


def _mcp_transport() -> str:
    transport = (os.getenv("JIRA_MCP_TRANSPORT") or "streamable_http").strip().lower()
    if transport in {"streamable-http", "http", "streamablehttp"}:
        return "streamable_http"
    if transport == "stdio":
        return "stdio"
    return "streamable_http"


def jira_mcp_is_configured() -> tuple[bool, str]:
    transport = _mcp_transport()
    if transport == "stdio":
        command = (os.getenv("JIRA_MCP_COMMAND") or "").strip()
        if not command:
            return False, "JIRA_MCP_COMMAND no esta configurado."
        return True, ""
    url = (os.getenv("JIRA_MCP_URL") or "").strip() or DEFAULT_MCP_URL
    if not url:
        return False, "JIRA_MCP_URL no esta configurado."
    return True, ""


def _parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _parse_stdio_args(raw: str | None) -> list[str]:
    if not raw:
        return []
    text = raw.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    return [item.strip() for item in text.split(",") if item.strip()]


def _build_stdio_env_overrides() -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith("JIRA_") or key.startswith("ATLASSIAN_") or key.startswith("MCP_"):
            env[key] = value
    return env


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _priority_name(incident: dict[str, Any]) -> str:
    is_high = bool(incident.get("is_high_priority"))
    level = str(incident.get("priority_level") or "").strip().lower()
    if level == "high" or is_high:
        return "High"
    return "Low"


def _build_summary(incident: dict[str, Any], incident_id: Any) -> str:
    description = str(incident.get("description") or "Incident report").strip()
    summary = f"[Incident #{incident_id}] {description}".strip()
    return summary[:240] if len(summary) > 240 else summary


def _format_probable_files(probable_files: Any, limit: int = 5) -> list[str]:
    if not isinstance(probable_files, list):
        return []

    lines: list[str] = []
    for item in probable_files[:limit]:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        if not source:
            continue
        matches = item.get("matches")
        score = item.get("best_score")
        details: list[str] = []
        if matches is not None:
            details.append(f"matches={matches}")
        if score is not None:
            details.append(f"best_score={score}")
        suffix = f" ({', '.join(details)})" if details else ""
        lines.append(f"- {source}{suffix}")
    return lines


def _format_suggested_fixes(suggested_fixes: Any, limit: int = 4) -> list[str]:
    if not isinstance(suggested_fixes, list):
        return []

    lines: list[str] = []
    for item in suggested_fixes[:limit]:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file_path") or "").strip()
        why = str(item.get("why") or "").strip()
        proposed_change = str(item.get("proposed_change") or "").strip()
        confidence = str(item.get("confidence") or "").strip() or "media"
        if not file_path and not proposed_change:
            continue

        title = file_path or "<ruta no especificada>"
        lines.append(f"- Archivo: {title}")
        if why:
            lines.append(f"  Motivo: {why}")
        if proposed_change:
            lines.append(f"  Recomendacion: {proposed_change}")
        lines.append(f"  Confianza: {confidence}")
    return lines


def _build_description_text(
    incident: dict[str, Any], analysis: dict[str, Any], incident_id: Any
) -> str:
    rag_summary = str(analysis.get("summary") or "No analysis summary available.")
    retrieval_mode = str(analysis.get("retrieval_mode") or "").strip() or "unknown"
    retrieval_warning = str(analysis.get("retrieval_warning") or "").strip()
    suggested_fixes_lines = _format_suggested_fixes(analysis.get("suggested_fixes"))
    probable_files_lines = _format_probable_files(analysis.get("probable_files"))

    lines = [
        f"Incident ID: {incident_id}",
        f"Source: {incident.get('source') or 'unknown'}",
        f"Page URL: {incident.get('page_url') or 'not provided'}",
        f"Reporter email: {incident.get('reporter_email') or 'not provided'}",
        f"Priority: {_priority_name(incident)}",
        "",
        "Problem details:",
        f"Description: {incident.get('description') or ''}",
        f"Expected: {incident.get('expected_result') or ''}",
        f"Actual: {incident.get('actual_result') or ''}",
        f"Steps: {incident.get('steps_to_reproduce') or ''}",
        "",
        "RAG analysis summary:",
        rag_summary,
        f"Retrieval mode: {retrieval_mode}",
    ]

    if retrieval_warning:
        lines.extend(["", f"Retrieval warning: {retrieval_warning}"])

    lines.extend(["", "Developer recommendations:"])
    if suggested_fixes_lines:
        lines.extend(suggested_fixes_lines)
    else:
        lines.append(
            "- No specific fix suggestions were produced. Validate the flow with additional logs."
        )

    lines.extend(["", "Suggested files to review first:"])
    if probable_files_lines:
        lines.extend(probable_files_lines)
    else:
        lines.append("- No high-confidence file matches from RAG.")

    lines.extend(
        [
            "",
            "Suggested validation for the assignee:",
            "- Reproduce the issue with the reported steps and capture logs around the touched modules.",
            "- Validate expected vs actual behavior after the fix.",
            "- Run a quick regression on nearby checkout/cart flows.",
        ]
    )

    return "\n".join(line for line in lines if line is not None)


def _schema_type(schema: Any) -> str | None:
    if not isinstance(schema, dict):
        return None
    value = schema.get("type")
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item != "null":
                return item
        return None
    if isinstance(value, str):
        return value
    return None


def _value_for_property(
    property_name: str,
    property_schema: Any,
    values: dict[str, Any],
) -> Any:
    key = property_name.strip().lower()
    expected_type = _schema_type(property_schema)

    if key in {"summary", "title"}:
        return values["summary"]
    if key in {"description", "details", "body", "content", "text"}:
        return values["description"]
    if key in {"projectkey", "project_key"}:
        return values["project_key"]
    if key == "project":
        if expected_type == "object":
            return {"key": values["project_key"]} if values["project_key"] else None
        return values["project_key"]
    if key in {"issuetypename", "issue_type_name"}:
        return values["issue_type"]
    if key in {"issuetype", "issue_type"}:
        if expected_type == "object":
            return {"name": values["issue_type"]} if values["issue_type"] else None
        return values["issue_type"]
    if key in {"priority", "priorityname", "priority_name"}:
        if expected_type == "object":
            return {"name": values["priority_name"]}
        return values["priority_name"]
    if key in {"labels", "tags"}:
        return values["labels"]
    if key in {"cloudid", "cloud_id", "siteid", "site_id"}:
        return values["cloud_id"]
    if key in {"reporter", "reporteremail", "reporter_email"}:
        if expected_type == "object":
            return {"emailAddress": values["reporter_email"]} if values["reporter_email"] else None
        return values["reporter_email"]
    if key in {"incidentid", "incident_id"}:
        return values["incident_id"]
    return None


def _build_schema_arguments(tool_schema: Any, values: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(tool_schema, dict):
        return {}
    properties = tool_schema.get("properties")
    if not isinstance(properties, dict):
        return {}

    args: dict[str, Any] = {}
    for property_name, property_schema in properties.items():
        value = _value_for_property(property_name, property_schema, values)
        if value is not None:
            args[property_name] = value
    return _drop_none(args)


def _build_argument_candidates(tool_schema: Any, values: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    custom_raw = (os.getenv("JIRA_MCP_CREATE_ISSUE_ARGS_JSON") or "").strip()
    if custom_raw:
        try:
            parsed = json.loads(custom_raw)
            if isinstance(parsed, dict):
                candidates.append(parsed)
            elif isinstance(parsed, list):
                candidates.extend(item for item in parsed if isinstance(item, dict))
        except Exception:
            pass

    schema_args = _build_schema_arguments(tool_schema, values)
    if schema_args:
        candidates.append(schema_args)

    candidates.extend(
        [
            _drop_none(
                {
                    "projectKey": values["project_key"],
                    "issueTypeName": values["issue_type"],
                    "summary": values["summary"],
                    "description": values["description"],
                    "priority": values["priority_name"],
                    "labels": values["labels"],
                }
            ),
            _drop_none(
                {
                    "project": {"key": values["project_key"]} if values["project_key"] else None,
                    "issueType": {"name": values["issue_type"]} if values["issue_type"] else None,
                    "summary": values["summary"],
                    "description": values["description"],
                }
            ),
            _drop_none(
                {
                    "fields": {
                        "project": {"key": values["project_key"]},
                        "issuetype": {"name": values["issue_type"]},
                        "summary": values["summary"],
                        "description": values["description"],
                        "labels": values["labels"],
                        "priority": {"name": values["priority_name"]},
                    }
                    if values["project_key"] and values["issue_type"]
                    else None
                }
            ),
            _drop_none(
                {
                    "summary": values["summary"],
                    "description": values["description"],
                    "title": values["summary"],
                }
            ),
        ]
    )

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict) or not item:
            continue
        marker = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(item)
    return unique


def _find_key_recursively(payload: Any, wanted_key: str) -> Any:
    wanted = wanted_key.lower()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).strip().lower() == wanted:
                return value
            found = _find_key_recursively(value, wanted_key)
            if found is not None:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _find_key_recursively(item, wanted_key)
            if found is not None:
                return found
    return None


def _extract_issue_key(structured_content: Any, text: str) -> str | None:
    for candidate_key in ("issueKey", "issue_key", "key", "jiraIssueKey"):
        value = _find_key_recursively(structured_content, candidate_key)
        if isinstance(value, str):
            match = ISSUE_KEY_REGEX.search(value)
            if match:
                return match.group(1)
    match = ISSUE_KEY_REGEX.search(text or "")
    return match.group(1) if match else None


def _extract_issue_url(structured_content: Any, text: str, issue_key: str | None) -> str | None:
    for candidate_key in ("issueUrl", "issue_url", "url", "browseUrl", "browse_url"):
        value = _find_key_recursively(structured_content, candidate_key)
        if isinstance(value, str) and value.startswith("http"):
            return value

    text_match = ISSUE_URL_REGEX.search(text or "")
    if text_match:
        return text_match.group(0)

    base_url = (os.getenv("JIRA_BASE_URL") or "").rstrip("/")
    if base_url and issue_key:
        return f"{base_url}/browse/{issue_key}"
    return None


def _select_tool(tools: list[Any], preferred_tool_name: str) -> Any | None:
    if not tools:
        return None
    for tool in tools:
        if str(getattr(tool, "name", "")).strip().lower() == preferred_tool_name.lower():
            return tool

    ranked_patterns = [
        "createjiraissue",
        "create_jira_issue",
        "jira_create_issue",
        "createissue",
    ]
    for pattern in ranked_patterns:
        for tool in tools:
            name = str(getattr(tool, "name", "")).strip().lower()
            normalized = name.replace("-", "").replace("_", "")
            if pattern in normalized:
                return tool

    for tool in tools:
        name = str(getattr(tool, "name", "")).strip().lower()
        if "jira" in name and "create" in name and "issue" in name:
            return tool
    return None


def _parse_call_tool_result(call_result: Any) -> dict[str, Any]:
    content_items = getattr(call_result, "content", None) or []
    structured_content = getattr(call_result, "structuredContent", None)
    is_error = bool(getattr(call_result, "isError", False))

    text_parts: list[str] = []
    normalized_content: list[dict[str, Any]] = []
    for item in content_items:
        if hasattr(item, "model_dump"):
            parsed = item.model_dump(exclude_none=True)
        elif isinstance(item, dict):
            parsed = item
        else:
            parsed = {"value": str(item)}
        normalized_content.append(parsed)
        text_value = parsed.get("text")
        if isinstance(text_value, str) and text_value.strip():
            text_parts.append(text_value.strip())

    return {
        "is_error": is_error,
        "structured_content": structured_content,
        "content": normalized_content,
        "text": "\n".join(text_parts).strip(),
    }


async def _call_with_session(
    session: Any,
    incident: dict[str, Any],
    analysis: dict[str, Any],
    incident_id: Any,
    transport: str,
) -> dict[str, Any]:
    preferred_tool_name = (
        os.getenv("JIRA_MCP_TOOL_CREATE_ISSUE") or DEFAULT_TOOL_NAME
    ).strip()
    list_tools_result = await session.list_tools()
    tools = list(getattr(list_tools_result, "tools", []) or [])
    available_tool_names = [str(getattr(tool, "name", "")) for tool in tools]
    selected_tool = _select_tool(tools, preferred_tool_name)
    if selected_tool is None:
        return {
            "created": False,
            "reason": "No se encontro una tool MCP para crear issues de Jira.",
            "issue_key": None,
            "issue_url": None,
            "transport": f"mcp/{transport}",
            "available_tools": available_tool_names,
        }

    values = {
        "summary": _build_summary(incident, incident_id),
        "description": _build_description_text(incident, analysis, incident_id),
        "project_key": (os.getenv("JIRA_PROJECT_KEY") or "").strip() or None,
        "issue_type": (os.getenv("JIRA_ISSUE_TYPE") or "Bug").strip() or "Bug",
        "priority_name": _priority_name(incident),
        "reporter_email": str(incident.get("reporter_email") or "").strip() or None,
        "incident_id": str(incident_id),
        "labels": ["incident-report", "orchestrator-mvp"],
        "cloud_id": (os.getenv("JIRA_CLOUD_ID") or "").strip() or None,
    }
    tool_schema = getattr(selected_tool, "inputSchema", None)
    argument_candidates = _build_argument_candidates(tool_schema, values)
    if not argument_candidates:
        argument_candidates = [{"summary": values["summary"], "description": values["description"]}]

    last_error = ""
    for args in argument_candidates:
        try:
            tool_result = await session.call_tool(getattr(selected_tool, "name"), arguments=args)
        except Exception as exc:
            last_error = str(exc)
            continue
        parsed = _parse_call_tool_result(tool_result)
        if parsed["is_error"]:
            last_error = parsed["text"] or "MCP tool returned isError=true."
            continue

        issue_key = _extract_issue_key(parsed["structured_content"], parsed["text"])
        issue_url = _extract_issue_url(parsed["structured_content"], parsed["text"], issue_key)
        return {
            "created": True,
            "reason": None,
            "issue_key": issue_key,
            "issue_url": issue_url,
            "transport": f"mcp/{transport}",
            "tool_name": getattr(selected_tool, "name"),
            "raw_response": {
                "structured_content": parsed["structured_content"],
                "content": parsed["content"],
                "text": parsed["text"],
            },
        }

    return {
        "created": False,
        "reason": f"La tool MCP fallo al crear el ticket. {last_error}".strip(),
        "issue_key": None,
        "issue_url": None,
        "transport": f"mcp/{transport}",
        "tool_name": getattr(selected_tool, "name", None),
    }


async def _create_ticket_via_streamable_http(
    incident: dict[str, Any], analysis: dict[str, Any], incident_id: Any
) -> dict[str, Any]:
    try:
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except Exception as exc:
        return {
            "created": False,
            "reason": f"No se pudo importar MCP client HTTP: {exc}",
            "issue_key": None,
            "issue_url": None,
            "transport": "mcp/streamable_http",
        }

    url = (os.getenv("JIRA_MCP_URL") or "").strip() or DEFAULT_MCP_URL
    timeout_seconds = float(os.getenv("JIRA_MCP_TIMEOUT_SECONDS", "25"))
    headers = _parse_json_object(os.getenv("JIRA_MCP_HEADERS_JSON"))
    bearer = (os.getenv("JIRA_MCP_BEARER_TOKEN") or "").strip()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds, read=timeout_seconds),
        headers=headers or None,
    ) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await _call_with_session(
                    session, incident, analysis, incident_id, "streamable_http"
                )


async def _create_ticket_via_stdio(
    incident: dict[str, Any], analysis: dict[str, Any], incident_id: Any
) -> dict[str, Any]:
    try:
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
    except Exception as exc:
        return {
            "created": False,
            "reason": f"No se pudo importar MCP client stdio: {exc}",
            "issue_key": None,
            "issue_url": None,
            "transport": "mcp/stdio",
        }

    command = (os.getenv("JIRA_MCP_COMMAND") or "").strip()
    if not command:
        return {
            "created": False,
            "reason": "JIRA_MCP_COMMAND no esta configurado.",
            "issue_key": None,
            "issue_url": None,
            "transport": "mcp/stdio",
        }

    args = _parse_stdio_args(os.getenv("JIRA_MCP_ARGS"))
    cwd = (os.getenv("JIRA_MCP_CWD") or "").strip() or None
    params = StdioServerParameters(
        command=command,
        args=args,
        env=_build_stdio_env_overrides() or None,
        cwd=cwd,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await _call_with_session(session, incident, analysis, incident_id, "stdio")


async def _create_jira_ticket_via_mcp_async(
    incident: dict[str, Any], analysis: dict[str, Any], incident_id: Any
) -> dict[str, Any]:
    transport = _mcp_transport()
    if transport == "stdio":
        return await _create_ticket_via_stdio(incident, analysis, incident_id)
    return await _create_ticket_via_streamable_http(incident, analysis, incident_id)


def create_jira_ticket_via_mcp(
    incident: dict[str, Any], analysis: dict[str, Any], incident_id: Any
) -> dict[str, Any]:
    try:
        return asyncio.run(_create_jira_ticket_via_mcp_async(incident, analysis, incident_id))
    except Exception as exc:
        return {
            "created": False,
            "reason": f"Fallo Jira MCP: {_exception_to_text(exc)}",
            "issue_key": None,
            "issue_url": None,
            "transport": f"mcp/{_mcp_transport()}",
        }


def mcp_enabled_for_auto_mode() -> bool:
    return _parse_bool(os.getenv("JIRA_MCP_ENABLED"), default=True)
