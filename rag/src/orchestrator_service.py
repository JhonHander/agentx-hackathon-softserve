from __future__ import annotations

import base64
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from analysis_agent import run_rag_analysis
from incident_client import create_incident_recommendation, create_incident_report
from jira_agent import create_jira_ticket
from jira_ticket_registry import register_ticket_contact
from reporter_notification import send_ticket_opened_email
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel
from rag_config import RagConfig

EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PLACEHOLDER_API_KEYS = {"TU_API_KEY", "your_openai_api_key", "YOUR_OPENAI_API_KEY"}


@dataclass
class IncidentDraft:
    description: str = ""
    expected_result: str = ""
    actual_result: str = ""
    steps_to_reproduce: str = ""
    reporter_name: str | None = None
    reporter_email: str | None = None
    page_url: str | None = None
    source: str | None = None
    priority_level: str | None = None
    priority_reason: str | None = None
    attachments_base64: list[dict[str, Any]] = field(default_factory=list)
    attachment_notes: list[str] = field(default_factory=list)


@dataclass
class SessionState:
    id: str
    stage: Literal["collecting", "awaiting_confirmation", "completed"] = "collecting"
    draft: IncidentDraft = field(default_factory=IncidentDraft)
    incident_id: Any = None
    turns: list[dict[str, str]] = field(default_factory=list)


class ConversationalTurn(BaseModel):
    assistant_message: str
    action: Literal["collect", "ready_to_save", "save_now"] = "collect"
    description: str | None = None
    expected_result: str | None = None
    actual_result: str | None = None
    steps_to_reproduce: str | None = None
    reporter_email: str | None = None


class InferredDetails(BaseModel):
    description: str | None = None
    expected_result: str | None = None
    actual_result: str | None = None
    steps_to_reproduce: str | None = None


class PriorityOutput(BaseModel):
    priority_level: str
    priority_reason: str


class ImageInsights(BaseModel):
    summary: str | None = None
    actual_result_hint: str | None = None
    priority_hint: str | None = None


class GraphState(TypedDict):
    session: SessionState
    user_message: str
    action: str
    assistant_message: str
    result: dict[str, Any] | None
    error: str | None


_SESSIONS: dict[str, SessionState] = {}
_LOCK = threading.Lock()


def _validate_openai_key() -> None:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key or key in PLACEHOLDER_API_KEYS:
        raise ValueError(
            "OPENAI_API_KEY no esta configurada correctamente. "
            "Configura una key real en .env."
        )


def _model() -> ChatOpenAI:
    _validate_openai_key()
    return ChatOpenAI(
        model=os.getenv("ORCHESTRATOR_MODEL", "gpt-4.1-mini"),
        temperature=float(os.getenv("ORCHESTRATOR_TEMPERATURE", "0.1")),
    )


def _safe_model_error(exc: Exception) -> Exception:
    message = str(exc)
    if "invalid_api_key" in message or "Incorrect API key provided" in message:
        return ValueError("OPENAI_API_KEY invalida. Verifica la key en .env.")
    return exc


def _history_text(session: SessionState, limit: int = 8) -> str:
    if not session.turns:
        return "[]"
    short = session.turns[-limit:]
    return "\n".join([f"{turn['role']}: {turn['text']}" for turn in short])


def _attachment_context_text(draft: IncidentDraft) -> str:
    if not draft.attachments_base64:
        return "Sin adjuntos."
    names = [str(item.get("name") or "attachment.bin") for item in draft.attachments_base64]
    notes = draft.attachment_notes[-3:]
    note_text = "\n".join(notes) if notes else "Sin analisis visual disponible."
    return (
        f"Adjuntos ({len(draft.attachments_base64)}): {', '.join(names)}\n"
        f"Analisis visual:\n{note_text}"
    )


def _missing_fields(draft: IncidentDraft) -> list[str]:
    missing: list[str] = []
    if not draft.description.strip():
        missing.append("description")
    if not draft.reporter_email or not EMAIL_REGEX.match(draft.reporter_email):
        missing.append("reporter_email")
    return missing


def _is_low_signal_description(description: str) -> bool:
    normalized = re.sub(r"\s+", " ", (description or "").strip().lower())
    if not normalized:
        return True
    generic_markers = [
        "hola",
        "quiero reportar",
        "quiero mostrar",
        "tengo un error",
        "te envio una captura",
        "te mando una captura",
        "adjunto",
        "hay un bug",
        "reportar un bug",
        "incidente",
    ]
    return len(normalized) < 40 and any(marker in normalized for marker in generic_markers)


def _run_conversational_turn(session: SessionState, user_message: str) -> ConversationalTurn:
    prompt = f"""
Eres un agente orquestador de incidentes ecommerce.
Habla SIEMPRE en espanol, natural y breve.
Evita plantillas rigidas y demasiadas preguntas.

Objetivo:
- Obtener solo lo necesario para crear incidente.
- Campos obligatorios: description y reporter_email.
- Tu decides si sigues preguntando o si ya toca guardar.

Acciones posibles:
- collect: falta info o quieres una aclaracion simple.
- ready_to_save: ya esta casi listo, muestra resumen y pide "confirmar".
- save_now: usuario confirmo y ya hay datos suficientes.

Reglas:
- Maximo UNA pregunta por turno.
- Si puedes inferir contexto desde lo dicho y adjuntos, no molestes.
- Si hay adjuntos, usalos para enriquecer la descripcion.

Historial reciente:
{_history_text(session)}

Draft actual:
description: {session.draft.description}
expected_result: {session.draft.expected_result}
actual_result: {session.draft.actual_result}
steps_to_reproduce: {session.draft.steps_to_reproduce}
reporter_email: {session.draft.reporter_email}
source: {session.draft.source}
page_url: {session.draft.page_url}
adjuntos_y_analisis:
{_attachment_context_text(session.draft)}

Mensaje actual:
{user_message}

Devuelve SOLO JSON:
{{
  "assistant_message":"texto",
  "action":"collect|ready_to_save|save_now",
  "description":"string|null",
  "expected_result":"string|null",
  "actual_result":"string|null",
  "steps_to_reproduce":"string|null",
  "reporter_email":"string|null"
}}
"""
    try:
        return _model().with_structured_output(ConversationalTurn).invoke(prompt)
    except Exception as exc:
        raise _safe_model_error(exc) from exc


def _merge_turn(draft: IncidentDraft, turn: ConversationalTurn) -> None:
    if turn.description:
        draft.description = turn.description.strip()
    if turn.expected_result:
        draft.expected_result = turn.expected_result.strip()
    if turn.actual_result:
        draft.actual_result = turn.actual_result.strip()
    if turn.steps_to_reproduce:
        draft.steps_to_reproduce = turn.steps_to_reproduce.strip()
    if turn.reporter_email:
        draft.reporter_email = turn.reporter_email.strip().lower()


def _infer_missing_details(draft: IncidentDraft) -> None:
    if (
        draft.expected_result.strip()
        and draft.actual_result.strip()
        and draft.steps_to_reproduce.strip()
    ):
        return

    prompt = f"""
Completa detalles faltantes de un incidente ecommerce.
Si falta informacion, infierela con cautela.
No inventes datos absurdos.

description: {draft.description}
expected_result: {draft.expected_result}
actual_result: {draft.actual_result}
steps_to_reproduce: {draft.steps_to_reproduce}
source: {draft.source}
page_url: {draft.page_url}
adjuntos_y_analisis:
{_attachment_context_text(draft)}

Devuelve SOLO JSON:
{{
  "description":"string|null",
  "expected_result":"string|null",
  "actual_result":"string|null",
  "steps_to_reproduce":"string|null"
}}
"""
    inferred: InferredDetails | None = None
    try:
        inferred = _model().with_structured_output(InferredDetails).invoke(prompt)
    except Exception:
        inferred = None

    if _is_low_signal_description(draft.description):
        fallback_description = (
            draft.attachment_notes[-1].split("\n")[0]
            if draft.attachment_notes
            else draft.actual_result
        )
        draft.description = (
            inferred.description.strip()
            if inferred and inferred.description and inferred.description.strip()
            else (fallback_description or draft.description or "Incidente reportado por usuario.")
        )

    if not draft.expected_result.strip():
        draft.expected_result = (
            inferred.expected_result.strip()
            if inferred and inferred.expected_result
            else "El flujo deberia completarse sin errores."
        )
    if not draft.actual_result.strip():
        draft.actual_result = (
            inferred.actual_result.strip()
            if inferred and inferred.actual_result
            else draft.description
        )
    if not draft.steps_to_reproduce.strip():
        draft.steps_to_reproduce = (
            inferred.steps_to_reproduce.strip()
            if inferred and inferred.steps_to_reproduce
            else "No proporcionado explicitamente por el usuario."
        )


def _classify_priority_with_llm(draft: IncidentDraft) -> tuple[str, str]:
    prompt = f"""
Clasifica prioridad de un incidente ecommerce.
Devuelve SOLO JSON:
{{"priority_level":"high|low","priority_reason":"texto corto"}}

Reglas:
- high: checkout/login/pago caidos, error 5xx critico, o impacto masivo.
- low: impacto acotado o menor.

description: {draft.description}
expected_result: {draft.expected_result}
actual_result: {draft.actual_result}
steps_to_reproduce: {draft.steps_to_reproduce}
adjuntos_y_analisis:
{_attachment_context_text(draft)}
"""
    try:
        parsed = _model().with_structured_output(PriorityOutput).invoke(prompt)
    except Exception as exc:
        raise _safe_model_error(exc) from exc

    level = (parsed.priority_level or "low").strip().lower()
    reason = (parsed.priority_reason or "").strip() or "Clasificacion por modelo."
    if level not in {"high", "low"}:
        level = "low"
    return level, reason


def _build_summary(draft: IncidentDraft) -> str:
    level_label = "ALTA" if draft.priority_level == "high" else "BAJA"
    return "\n".join(
        [
            "Perfecto, te comparto el resumen antes de enviarlo:",
            f"- Problema: {draft.description}",
            f"- Correo: {draft.reporter_email}",
            f"- Prioridad: {level_label}",
            f"- Motivo: {draft.priority_reason or 'No especificado'}",
            f"- URL: {draft.page_url or 'no proporcionada'}",
            f"- Adjuntos: {len(draft.attachments_base64)}",
            "Si esta bien, responde 'confirmar' y lo guardo.",
        ]
    )


def _prepare_for_save(draft: IncidentDraft) -> None:
    _infer_missing_details(draft)
    priority_level, priority_reason = _classify_priority_with_llm(draft)
    draft.priority_level = priority_level
    draft.priority_reason = priority_reason


def _save_and_analyze(session: SessionState) -> dict[str, Any]:
    incident_payload = {
        "description": session.draft.description,
        "expected_result": session.draft.expected_result,
        "actual_result": session.draft.actual_result,
        "steps_to_reproduce": session.draft.steps_to_reproduce,
        "source": session.draft.source,
        "reporter_name": session.draft.reporter_name,
        "reporter_email": session.draft.reporter_email,
        "page_url": session.draft.page_url,
        "status": "new",
        "metadata": {
            "captured_by": "orchestrator_langgraph",
            "conversation_turns": len(session.turns),
            "attachment_count": len(session.draft.attachments_base64),
            "attachment_notes": session.draft.attachment_notes[-3:],
        },
        "priority_level": session.draft.priority_level,
        "is_high_priority": session.draft.priority_level == "high",
        "priority_reason": session.draft.priority_reason,
        "attachments_base64": session.draft.attachments_base64,
    }
    incident_result = create_incident_report(incident_payload)
    session.incident_id = incident_result["incident_id"]

    analysis_data: dict[str, Any] | None = None
    analysis_error: str | None = None
    recommendation_error: str | None = None
    recommendation_id: Any = None
    jira_result: dict[str, Any] | None = None
    reporter_notification: dict[str, Any] | None = None

    try:
        analysis_data = run_rag_analysis(incident_payload, RagConfig.from_env())
    except Exception as exc:
        analysis_error = str(exc)
    else:
        try:
            rec = create_incident_recommendation(
                {
                    "incident_report_id": session.incident_id,
                    "analysis_query": analysis_data.get("query"),
                    "analysis_summary": analysis_data.get("summary"),
                    "probable_files": analysis_data.get("probable_files"),
                    "top_chunks": analysis_data.get("top_chunks"),
                    "suggested_fixes": analysis_data.get("suggested_fixes"),
                    "llm_model": analysis_data.get("llm_model"),
                    "run_status": "completed",
                    "error_message": analysis_data.get("retrieval_warning"),
                }
            )
            recommendation_id = rec.get("recommendation_id")
        except Exception as exc:
            recommendation_error = str(exc)

    if analysis_data is None:
        try:
            rec_fail = create_incident_recommendation(
                {
                    "incident_report_id": session.incident_id,
                    "analysis_query": incident_payload.get("description") or "incident",
                    "analysis_summary": "No se pudo generar el analisis tecnico automatico.",
                    "probable_files": [],
                    "top_chunks": [],
                    "suggested_fixes": [],
                    "llm_model": None,
                    "run_status": "failed",
                    "error_message": analysis_error,
                }
            )
            recommendation_id = rec_fail.get("recommendation_id")
        except Exception:
            pass

    analysis_for_jira = analysis_data or {
        "summary": "No se pudo generar analisis tecnico automatico.",
        "suggested_fixes": [],
    }
    jira_result = create_jira_ticket(incident_payload, analysis_for_jira, session.incident_id)

    if jira_result and jira_result.get("created"):
        issue_key = str(jira_result.get("issue_key") or "").strip()
        if issue_key and session.draft.reporter_email:
            register_ticket_contact(
                issue_key=issue_key,
                incident_id=session.incident_id,
                reporter_email=session.draft.reporter_email,
                issue_url=str(jira_result.get("issue_url") or "").strip() or None,
            )

    if jira_result and jira_result.get("created") and session.draft.reporter_email:
        reporter_notification = send_ticket_opened_email(
            reporter_email=session.draft.reporter_email,
            incident_id=session.incident_id,
            jira_result=jira_result,
            incident=incident_payload,
        )

    level_label = "ALTA" if session.draft.priority_level == "high" else "BAJA"
    assistant_message = (
        f"Listo, incidente guardado con id {session.incident_id}. "
        f"Prioridad: {level_label}."
    )
    if analysis_data:
        assistant_message += " Ya hice el analisis tecnico con posibles archivos y fixes."
        suggested = analysis_data.get("suggested_fixes") or []
        if suggested:
            top_files = ", ".join(
                [str(item.get("file_path") or "") for item in suggested[:2] if item.get("file_path")]
            )
            if top_files:
                assistant_message += f" Posibles archivos: {top_files}."
    else:
        assistant_message += " No pude completar el analisis tecnico automatico."

    if analysis_data and analysis_data.get("retrieval_mode") == "local_keyword_fallback":
        assistant_message += " Nota: use modo local de respaldo (Qdrant no disponible)."
    if recommendation_error:
        assistant_message += " El analisis se genero, pero no se pudo guardar en recomendaciones."
    if jira_result and jira_result.get("created"):
        key = jira_result.get("issue_key")
        url = jira_result.get("issue_url")
        if key and url:
            assistant_message += f" Ticket Jira creado: {key} ({url})."
        elif key:
            assistant_message += f" Ticket Jira creado: {key}."
        else:
            assistant_message += " Ticket Jira creado via MCP."
        if reporter_notification and reporter_notification.get("sent"):
            assistant_message += " Notifique por correo al usuario reportante."
        elif reporter_notification and reporter_notification.get("reason"):
            assistant_message += (
                " No se pudo enviar correo al reportante: "
                f"{reporter_notification['reason']}"
            )
    elif jira_result and jira_result.get("reason"):
        assistant_message += f" No se pudo crear ticket Jira: {jira_result['reason']}"

    return {
        "assistant_message": assistant_message,
        "incident_id": session.incident_id,
        "priority": {
            "level": session.draft.priority_level,
            "is_high_priority": session.draft.priority_level == "high",
            "reason": session.draft.priority_reason,
        },
        "analysis": {
            "status": "completed" if analysis_data else "failed",
            "query": analysis_data.get("query") if analysis_data else None,
            "summary": analysis_data.get("summary") if analysis_data else None,
            "suggested_fixes": analysis_data.get("suggested_fixes") if analysis_data else [],
            "retrieval_mode": analysis_data.get("retrieval_mode") if analysis_data else None,
            "retrieval_warning": analysis_data.get("retrieval_warning") if analysis_data else None,
            "recommendation_id": recommendation_id,
            "error": analysis_error or recommendation_error,
        },
        "jira": jira_result,
        "reporter_notification": reporter_notification,
    }


def _normalize_attachments(raw_attachments: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_attachments, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in raw_attachments[:6]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"attachment-{len(normalized) + 1}.bin").strip()[:255]
        mime_type = (
            str(item.get("type") or item.get("mime_type") or "application/octet-stream")
            .strip()
            .lower()
        )
        raw_base64 = item.get("data_base64") or item.get("base64") or item.get("data")
        if not isinstance(raw_base64, str) or not raw_base64.strip():
            continue
        payload = raw_base64.strip()
        data_url_match = re.match(r"^data:([^;]+);base64,(.+)$", payload, flags=re.IGNORECASE)
        if data_url_match:
            mime_type = mime_type or data_url_match.group(1).strip().lower()
            payload = data_url_match.group(2).strip()

        try:
            decoded = base64.b64decode(payload, validate=True)
        except Exception:
            continue
        if not decoded:
            continue

        normalized.append(
            {
                "name": name or "attachment.bin",
                "type": mime_type or "application/octet-stream",
                "data_base64": payload,
                "size": len(decoded),
            }
        )
    return normalized[:6]


def _analyze_image_attachments(
    attachments: list[dict[str, Any]], user_message: str
) -> str | None:
    image_attachments = [
        item
        for item in attachments
        if str(item.get("type") or "").strip().lower().startswith("image/")
        and item.get("data_base64")
    ]
    if not image_attachments:
        return None

    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Analiza las imagenes adjuntas de un posible bug ecommerce. "
                "Devuelve SOLO JSON con este esquema: "
                '{"summary":"string|null","actual_result_hint":"string|null","priority_hint":"string|null"}. '
                "No inventes detalles inexistentes."
            ),
        },
        {
            "type": "text",
            "text": f"Mensaje del usuario: {user_message or '(sin texto)'}",
        },
    ]
    for attachment in image_attachments[:3]:
        mime_type = str(attachment.get("type") or "image/png")
        data_base64 = str(attachment.get("data_base64") or "").strip()
        if not data_base64:
            continue
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{data_base64}"},
            }
        )

    try:
        parsed = _model().with_structured_output(ImageInsights).invoke(
            [HumanMessage(content=content)]
        )
    except Exception:
        return None

    chunks: list[str] = []
    if parsed.summary and parsed.summary.strip():
        chunks.append(parsed.summary.strip())
    if parsed.actual_result_hint and parsed.actual_result_hint.strip():
        chunks.append(f"Hallazgo visual: {parsed.actual_result_hint.strip()}")
    if parsed.priority_hint and parsed.priority_hint.strip():
        chunks.append(f"Senal de prioridad: {parsed.priority_hint.strip()}")
    return "\n".join(chunks) if chunks else None


def _agent_node(state: GraphState) -> GraphState:
    session = state["session"]
    user_message = state["user_message"]

    try:
        turn = _run_conversational_turn(session, user_message)
    except ValueError as exc:
        return {
            **state,
            "action": "collect",
            "assistant_message": str(exc),
            "error": str(exc),
        }

    _merge_turn(session.draft, turn)
    if _is_low_signal_description(session.draft.description) and session.draft.attachment_notes:
        session.draft.description = session.draft.attachment_notes[-1].split("\n")[0]
    if session.draft.reporter_email and not EMAIL_REGEX.match(session.draft.reporter_email):
        session.draft.reporter_email = None

    missing = _missing_fields(session.draft)
    if missing:
        session.stage = "collecting"
        return {
            **state,
            "action": "collect",
            "assistant_message": turn.assistant_message.strip() or "Cuentame un poco mas.",
        }

    user_lower = user_message.lower()
    is_confirm = any(word in user_lower for word in ["confirmar", "confirmo", "enviar", "ok"])
    action = turn.action

    if action == "save_now" and is_confirm:
        return {**state, "action": "save", "assistant_message": ""}

    _prepare_for_save(session.draft)
    session.stage = "awaiting_confirmation"
    return {
        **state,
        "action": "collect",
        "assistant_message": _build_summary(session.draft),
    }


def _save_node(state: GraphState) -> GraphState:
    session = state["session"]
    try:
        result = _save_and_analyze(session)
    except Exception as exc:
        return {
            **state,
            "result": None,
            "assistant_message": f"No pude guardar el incidente: {exc}",
            "error": str(exc),
        }
    session.stage = "completed"
    return {
        **state,
        "result": result,
        "assistant_message": result.get("assistant_message", ""),
    }


def _route_after_agent(state: GraphState) -> str:
    return "save" if state.get("action") == "save" else "end"


def _build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("agent", _agent_node)
    graph.add_node("save", _save_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_agent,
        {"save": "save", "end": END},
    )
    graph.add_edge("save", END)
    return graph.compile()


_GRAPH = _build_graph()


def handle_message(request: dict[str, Any]) -> dict[str, Any]:
    message = (request.get("message") or "").strip()
    incoming_attachments = _normalize_attachments(request.get("attachments_base64"))
    if not message and not incoming_attachments:
        raise ValueError("message is required")

    with _LOCK:
        session_id = request.get("session_id")
        session = _SESSIONS.get(session_id) if session_id else None

        if session is None:
            new_id = str(uuid.uuid4())
            session = SessionState(id=new_id)
            session.draft.page_url = request.get("page_url")
            session.draft.source = request.get("source")
            session.draft.reporter_name = request.get("reporter_name")
            session.draft.reporter_email = request.get("reporter_email")
            _SESSIONS[new_id] = session
        else:
            session.draft.page_url = request.get("page_url") or session.draft.page_url
            session.draft.source = request.get("source") or session.draft.source
            session.draft.reporter_name = (
                request.get("reporter_name") or session.draft.reporter_name
            )
            session.draft.reporter_email = (
                request.get("reporter_email") or session.draft.reporter_email
            )

        if session.stage == "completed":
            return {
                "session_id": session.id,
                "status": "completed",
                "assistant_message": "Este incidente ya fue procesado. Inicia una nueva sesion.",
                "incident_id": session.incident_id,
                "missing_fields": [],
            }

        if incoming_attachments:
            session.draft.attachments_base64 = (
                session.draft.attachments_base64 + incoming_attachments
            )[:6]
            visual_note = _analyze_image_attachments(incoming_attachments, message)
            if visual_note:
                session.draft.attachment_notes.append(visual_note)

        user_turn_text = message or "Adjunte evidencia del error."
        if incoming_attachments:
            names = ", ".join(
                [str(item.get("name") or "attachment.bin") for item in incoming_attachments]
            )
            user_turn_text = f"{user_turn_text}\nAdjuntos: {names}"
        session.turns.append({"role": "user", "text": user_turn_text})

        graph_state = _GRAPH.invoke(
            {
                "session": session,
                "user_message": user_turn_text,
                "action": "",
                "assistant_message": "",
                "result": None,
                "error": None,
            }
        )

        assistant_message = (
            (graph_state.get("assistant_message") or "").strip() or "Entiendo. Continuemos."
        )
        session.turns.append({"role": "assistant", "text": assistant_message})

        if session.stage == "completed":
            result = graph_state.get("result") or {}
            return {
                "session_id": session.id,
                "status": "completed",
                "assistant_message": assistant_message,
                "incident_id": session.incident_id,
                "priority": result.get("priority"),
                "analysis": result.get("analysis"),
                "jira": result.get("jira"),
                "missing_fields": [],
            }

        missing = _missing_fields(session.draft)
        status = "ready_to_submit" if session.stage == "awaiting_confirmation" else "collecting"
        return {
            "session_id": session.id,
            "status": status,
            "assistant_message": assistant_message,
            "missing_fields": missing,
            "priority": (
                {
                    "level": session.draft.priority_level,
                    "is_high_priority": session.draft.priority_level == "high",
                    "reason": session.draft.priority_reason,
                }
                if session.draft.priority_level
                else None
            ),
        }


def reset_session(session_id: str) -> dict[str, Any]:
    with _LOCK:
        existed = _SESSIONS.pop(session_id, None) is not None
    return {"session_id": session_id, "deleted": existed}
