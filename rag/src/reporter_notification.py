from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Any

from langfuse_config import langfuse_is_enabled

if langfuse_is_enabled():
    from langfuse import observe
else:

    def observe(**_kwargs):  # type: ignore[misc]
        """No-op decorator when Langfuse is disabled."""

        def _wrapper(func):
            return func

        return _wrapper


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "si", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def reporter_email_notifications_enabled() -> bool:
    return _parse_bool(os.getenv("REPORTER_EMAIL_NOTIFICATIONS_ENABLED"), default=True)


def smtp_is_configured() -> tuple[bool, str]:
    host = (os.getenv("SMTP_HOST") or "").strip()
    from_email = (os.getenv("SMTP_FROM_EMAIL") or "").strip()
    if not host:
        return False, "SMTP_HOST no esta configurado."
    if not from_email:
        return False, "SMTP_FROM_EMAIL no esta configurado."

    use_ssl = _parse_bool(os.getenv("SMTP_USE_SSL"), default=False)
    if not use_ssl:
        username = (os.getenv("SMTP_USERNAME") or "").strip()
        password = (os.getenv("SMTP_PASSWORD") or "").strip()
        if username and not password:
            return False, "SMTP_PASSWORD no esta configurado."
    return True, ""


def _build_subject(incident_id: Any, issue_key: str | None) -> str:
    key_part = f" ({issue_key})" if issue_key else ""
    return f"[EverShop] Incidente #{incident_id} en revision{key_part}"


def _build_resolved_subject(incident_id: Any, issue_key: str | None) -> str:
    key_part = f" ({issue_key})" if issue_key else ""
    return f"[EverShop] Incidente #{incident_id} resuelto{key_part}"


def _build_body(
    incident_id: Any,
    issue_key: str | None,
    issue_url: str | None,
    incident: dict[str, Any],
) -> str:
    description = str(incident.get("description") or "").strip() or "Sin descripcion"
    source = str(incident.get("source") or "unknown").strip()
    page_url = str(incident.get("page_url") or "").strip() or "No especificada"

    lines = [
        "Hola,",
        "",
        "Gracias por reportar el incidente. Te confirmamos que ya abrimos un ticket y el equipo de desarrollo ya esta trabajando en ello.",
        "",
        f"- Incident ID: {incident_id}",
        f"- Ticket Jira: {issue_key or 'Creado'}",
        f"- URL Jira: {issue_url or 'No disponible'}",
        f"- Fuente: {source}",
        f"- Pagina: {page_url}",
        "",
        "Resumen del reporte:",
        f"{description}",
        "",
        "Te avisaremos cuando haya actualizacion o solucion.",
        "",
        "Saludos,",
        "Equipo de soporte",
    ]
    return "\n".join(lines)


def _build_resolved_body(
    incident_id: Any,
    issue_key: str | None,
    issue_url: str | None,
) -> str:
    lines = [
        "Hola,",
        "",
        "Te confirmamos que el ticket de tu incidente ya fue marcado como finalizado por el equipo.",
        "",
        f"- Incident ID: {incident_id}",
        f"- Ticket Jira: {issue_key or 'Finalizado'}",
        f"- URL Jira: {issue_url or 'No disponible'}",
        "",
        "Si el problema persiste, responde este correo con nuevos detalles para reabrir el caso.",
        "",
        "Saludos,",
        "Equipo de soporte",
    ]
    return "\n".join(lines)


def _send_smtp_message(
    to_email: str,
    subject: str,
    body: str,
) -> dict[str, Any]:
    host = (os.getenv("SMTP_HOST") or "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    username = (os.getenv("SMTP_USERNAME") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").strip()
    from_email = (os.getenv("SMTP_FROM_EMAIL") or "").strip()
    from_name = (os.getenv("SMTP_FROM_NAME") or "EverShop Support").strip()
    reply_to = (os.getenv("SMTP_REPLY_TO") or "").strip() or None
    use_tls = _parse_bool(os.getenv("SMTP_USE_TLS"), default=True)
    use_ssl = _parse_bool(os.getenv("SMTP_USE_SSL"), default=False)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = to_email.strip()
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                if username:
                    server.login(username, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                if use_tls:
                    server.starttls()
                if username:
                    server.login(username, password)
                server.send_message(msg)
    except Exception as exc:
        return {
            "sent": False,
            "reason": f"No se pudo enviar email: {exc}",
            "to": to_email.strip(),
            "subject": subject,
        }

    return {
        "sent": True,
        "reason": None,
        "to": to_email.strip(),
        "subject": subject,
    }


@observe(name="notification_ticket_opened")
def send_ticket_opened_email(
    reporter_email: str,
    incident_id: Any,
    jira_result: dict[str, Any],
    incident: dict[str, Any],
) -> dict[str, Any]:
    if not reporter_email.strip():
        return {
            "sent": False,
            "reason": "reporter_email vacio.",
        }

    if not reporter_email_notifications_enabled():
        return {
            "sent": False,
            "reason": "Notificaciones por email deshabilitadas.",
        }

    configured, reason = smtp_is_configured()
    if not configured:
        return {
            "sent": False,
            "reason": reason,
        }

    issue_key = str(jira_result.get("issue_key") or "").strip() or None
    issue_url = str(jira_result.get("issue_url") or "").strip() or None

    subject = _build_subject(incident_id, issue_key)
    body = _build_body(incident_id, issue_key, issue_url, incident)

    return _send_smtp_message(
        to_email=reporter_email,
        subject=subject,
        body=body,
    )


@observe(name="notification_ticket_resolved")
def send_ticket_resolved_email(
    reporter_email: str,
    incident_id: Any,
    issue_key: str | None,
    issue_url: str | None,
) -> dict[str, Any]:
    if not reporter_email.strip():
        return {
            "sent": False,
            "reason": "reporter_email vacio.",
        }

    if not reporter_email_notifications_enabled():
        return {
            "sent": False,
            "reason": "Notificaciones por email deshabilitadas.",
        }

    configured, reason = smtp_is_configured()
    if not configured:
        return {
            "sent": False,
            "reason": reason,
        }

    subject = _build_resolved_subject(incident_id, issue_key)
    body = _build_resolved_body(incident_id, issue_key, issue_url)

    return _send_smtp_message(
        to_email=reporter_email,
        subject=subject,
        body=body,
    )
