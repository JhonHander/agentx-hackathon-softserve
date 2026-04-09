from __future__ import annotations

import os
from typing import Any

import httpx


def _candidate_incident_urls() -> list[str]:
    configured_url = (os.getenv("INCIDENT_API_URL") or "").strip()
    if configured_url:
        return [configured_url]

    return [
        "http://app:3000/api/incidents",
        "http://localhost:3000/api/incidents",
        "http://127.0.0.1:3000/api/incidents",
    ]


def _candidate_recommendation_urls() -> list[str]:
    configured_url = (os.getenv("INCIDENT_RECOMMENDATION_API_URL") or "").strip()
    if configured_url:
        return [configured_url]

    urls: list[str] = []
    for incident_url in _candidate_incident_urls():
        base = incident_url.rstrip("/")
        if base.endswith("/incidents"):
            urls.append(f"{base}/recommendations")
        else:
            urls.append(f"{base}/incidents/recommendations")
    return urls


def create_incident_report(payload: dict[str, Any]) -> dict[str, Any]:
    timeout = float(os.getenv("INCIDENT_API_TIMEOUT_SECONDS", "20"))

    body = {
        "description": payload.get("description", ""),
        "expected_result": payload.get("expected_result"),
        "actual_result": payload.get("actual_result"),
        "steps_to_reproduce": payload.get("steps_to_reproduce"),
        "source": payload.get("source"),
        "reporter_name": payload.get("reporter_name"),
        "reporter_email": payload.get("reporter_email"),
        "page_url": payload.get("page_url"),
        "status": payload.get("status"),
        "metadata": payload.get("metadata"),
        "priority_level": payload.get("priority_level"),
        "is_high_priority": payload.get("is_high_priority"),
        "priority_reason": payload.get("priority_reason"),
        "attachments_base64": payload.get("attachments_base64"),
    }

    response: httpx.Response | None = None
    used_url: str | None = None
    last_error: Exception | None = None

    for incident_api_url in _candidate_incident_urls():
        used_url = incident_api_url
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(incident_api_url, json=body)
        except Exception as exc:
            last_error = exc
            continue

        if response.status_code >= 400:
            raise RuntimeError(
                f"Incident API returned {response.status_code}: {response.text[:300]}"
            )

        break
    else:
        raise RuntimeError(f"Could not reach Incident API: {last_error}")

    if response is None:
        raise RuntimeError("Incident API request failed without response")

    data = response.json()
    incident_id = (
        data.get("data", {}).get("incidentId")
        or data.get("incidentId")
        or data.get("id")
    )

    if not incident_id:
        raise RuntimeError("Incident API response did not include incidentId")

    return {
        "incident_id": incident_id,
        "api_url": used_url,
        "raw_response": data,
    }


def create_incident_recommendation(payload: dict[str, Any]) -> dict[str, Any]:
    timeout = float(os.getenv("INCIDENT_API_TIMEOUT_SECONDS", "20"))

    body = {
        "incident_report_id": payload.get("incident_report_id"),
        "analysis_query": payload.get("analysis_query") or "",
        "analysis_summary": payload.get("analysis_summary") or "",
        "probable_files": payload.get("probable_files") or [],
        "top_chunks": payload.get("top_chunks") or [],
        "suggested_fixes": payload.get("suggested_fixes") or [],
        "llm_model": payload.get("llm_model"),
        "run_status": payload.get("run_status") or "completed",
        "error_message": payload.get("error_message"),
    }

    response: httpx.Response | None = None
    used_url: str | None = None
    last_error: Exception | None = None

    for recommendation_url in _candidate_recommendation_urls():
        used_url = recommendation_url
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(recommendation_url, json=body)
        except Exception as exc:
            last_error = exc
            continue

        if response.status_code >= 400:
            raise RuntimeError(
                "Incident recommendation API returned "
                f"{response.status_code}: {response.text[:300]}"
            )

        break
    else:
        raise RuntimeError(f"Could not reach Incident Recommendation API: {last_error}")

    if response is None:
        raise RuntimeError("Incident recommendation API request failed without response")

    data = response.json()
    recommendation_id = (
        data.get("data", {}).get("recommendationId")
        or data.get("recommendationId")
        or data.get("id")
    )

    return {
        "recommendation_id": recommendation_id,
        "api_url": used_url,
        "raw_response": data,
    }
