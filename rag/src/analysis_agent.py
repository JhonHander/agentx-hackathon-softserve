from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from langfuse_config import langfuse_is_enabled
from pydantic import BaseModel, Field
from rag_config import RagConfig
from retriever import search_code_chunks

if langfuse_is_enabled():
    from langfuse import observe
else:

    def observe(**_kwargs):  # type: ignore[misc]
        """No-op decorator when Langfuse is disabled."""

        def _wrapper(func):
            return func

        return _wrapper


class FixSuggestion(BaseModel):
    file_path: str
    why: str
    proposed_change: str
    confidence: str | None = None


class AnalysisSynthesis(BaseModel):
    summary: str
    suggested_fixes: list[FixSuggestion] = Field(default_factory=list)


def _build_query(incident: dict[str, Any]) -> str:
    parts = [
        incident.get("description", ""),
        f"Expected: {incident.get('expected_result', '')}",
        f"Actual: {incident.get('actual_result', '')}",
        f"Steps: {incident.get('steps_to_reproduce', '')}",
        f"Page URL: {incident.get('page_url', '')}",
        f"Source: {incident.get('source', '')}",
    ]
    return " | ".join(part.strip() for part in parts if part and str(part).strip())


def _build_probable_files(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"matches": 0, "best_score": None}
    )

    for hit in results:
        source = hit.get("source") or "<unknown>"
        score = float(hit.get("score", 0.0))
        entry = grouped[source]
        entry["matches"] += 1
        best_score = entry["best_score"]
        if best_score is None or score < best_score:
            entry["best_score"] = score

    ranked = sorted(
        (
            {
                "source": source,
                "matches": data["matches"],
                "best_score": data["best_score"],
            }
            for source, data in grouped.items()
        ),
        key=lambda item: (-item["matches"], item["best_score"] or 0.0),
    )
    return ranked[:8]


def _analysis_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv(
            "RAG_ANALYSIS_MODEL", os.getenv("ORCHESTRATOR_MODEL", "gpt-4.1-mini")
        ),
        temperature=float(os.getenv("RAG_ANALYSIS_TEMPERATURE", "0.1")),
    )


def _resolve_repo_path() -> Path:
    configured = (os.getenv("RAG_REPO_PATH") or "").strip()
    if configured:
        repo_path = Path(configured)
        if repo_path.exists():
            return repo_path
    return Path(__file__).resolve().parents[2]


def _is_included_file(path: Path, config: RagConfig) -> bool:
    file_name = path.name
    if file_name in config.include_filenames:
        return True
    return path.suffix.lower() in {ext.lower() for ext in config.include_extensions}


def _contains_excluded_dir(path: Path, excluded_dirs: tuple[str, ...]) -> bool:
    parts = {part.lower() for part in path.parts}
    excluded = {item.lower() for item in excluded_dirs}
    return len(parts.intersection(excluded)) > 0


def _extract_keywords(query: str, limit: int = 12) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9_]{4,}", query.lower())
    stop_words = {
        "with",
        "from",
        "that",
        "this",
        "page",
        "source",
        "steps",
        "actual",
        "expected",
        "description",
        "error",
        "report",
        "incidente",
        "usuario",
        "flujo",
    }
    keywords: list[str] = []
    seen: set[str] = set()
    for word in words:
        if word in stop_words or word in seen:
            continue
        seen.add(word)
        keywords.append(word)
        if len(keywords) >= limit:
            break
    return keywords


def _local_keyword_fallback(
    query: str,
    config: RagConfig,
    k: int,
) -> list[dict[str, Any]]:
    repo_path = _resolve_repo_path()
    if not repo_path.exists():
        return []

    keywords = _extract_keywords(query)
    if not keywords:
        return []

    max_file_bytes = max(int(config.max_file_bytes), 20_000)
    candidates: list[dict[str, Any]] = []
    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        if _contains_excluded_dir(path, config.exclude_dirs):
            continue
        if not _is_included_file(path, config):
            continue
        try:
            size = path.stat().st_size
        except Exception:
            continue
        if size <= 0 or size > max_file_bytes:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not content.strip():
            continue

        lowered = content.lower()
        hit_count = sum(lowered.count(keyword) for keyword in keywords)
        if hit_count <= 0:
            continue

        first_keyword = next((kw for kw in keywords if kw in lowered), keywords[0])
        index = lowered.find(first_keyword)
        start = max(0, index - 220)
        end = min(len(content), index + 420)
        snippet = content[start:end].strip()
        relative_source = str(path.relative_to(repo_path)).replace("\\", "/")

        candidates.append(
            {
                "score": float(1 / (1 + hit_count)),
                "source": relative_source,
                "filename": path.name,
                "extension": path.suffix,
                "chunk_index": 0,
                "start_index": start,
                "content": snippet,
            }
        )

    candidates.sort(key=lambda item: item["score"])
    return candidates[:k]


def _chunks_context(results: list[dict[str, Any]], limit: int = 6) -> str:
    lines: list[str] = []
    for item in results[:limit]:
        source = item.get("source") or "<unknown>"
        score = item.get("score")
        preview = (item.get("content") or "").replace("\n", " ").strip()[:450]
        lines.append(f"- source={source} | score={score}\n  snippet={preview}")
    return "\n".join(lines) if lines else "- Sin chunks relevantes"


def _fallback_suggestions(probable_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for file_item in probable_files[:3]:
        source = str(file_item.get("source") or "<unknown>")
        output.append(
            {
                "file_path": source,
                "why": "Archivo con varias coincidencias semanticas al incidente.",
                "proposed_change": (
                    "Agregar validaciones y logs alrededor del flujo afectado, "
                    "luego reproducir y corregir la condicion de error detectada."
                ),
                "confidence": "media",
            }
        )
    return output


@observe(name="analysis_synthesize_llm", as_type="generation")
def _synthesize_with_llm(
    incident: dict[str, Any],
    query: str,
    probable_files: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], str]:
    prompt = f"""
Eres un agente tecnico que analiza incidentes de ecommerce usando evidencia de RAG.
Responde en espanol claro y accionable.

Objetivo:
- Proponer lugares probables del codigo para revisar.
- Sugerir arreglos concretos (no codigo completo), maximo 4.
- Ser prudente: si no hay certeza, dilo.

Incidente:
description: {incident.get("description", "")}
expected_result: {incident.get("expected_result", "")}
actual_result: {incident.get("actual_result", "")}
steps_to_reproduce: {incident.get("steps_to_reproduce", "")}
source: {incident.get("source", "")}
page_url: {incident.get("page_url", "")}

Query RAG usada:
{query}

Archivos probables (ranking):
{probable_files}

Chunks relevantes:
{_chunks_context(results)}

Devuelve JSON con este esquema:
{{
  "summary": "resumen tecnico en 2-5 lineas",
  "suggested_fixes": [
    {{
      "file_path": "ruta/archivo",
      "why": "por que ese archivo",
      "proposed_change": "que cambiar",
      "confidence": "alta|media|baja"
    }}
  ]
}}
"""
    llm = _analysis_model()
    parsed = llm.with_structured_output(AnalysisSynthesis).invoke(prompt)
    suggestions = [
        {
            "file_path": item.file_path.strip(),
            "why": item.why.strip(),
            "proposed_change": item.proposed_change.strip(),
            "confidence": (item.confidence or "").strip() or "media",
        }
        for item in parsed.suggested_fixes
        if item.file_path.strip() and item.proposed_change.strip()
    ][:4]
    summary = parsed.summary.strip() if parsed.summary else ""
    if not summary:
        summary = "Analisis generado con RAG sin resumen explicito."
    return summary, suggestions, str(getattr(llm, "model_name", "unknown"))


@observe(name="analysis_rag_analysis")
def run_rag_analysis(incident: dict[str, Any], config: RagConfig) -> dict[str, Any]:
    top_k = int(os.getenv("ORCHESTRATOR_RAG_TOP_K", "8"))
    query = _build_query(incident)
    retrieval_mode = "qdrant_vector"
    retrieval_warning: str | None = None
    try:
        results = search_code_chunks(query=query, config=config, k=top_k)
    except Exception as exc:
        fallback_enabled = (
            os.getenv("RAG_LOCAL_FALLBACK_ENABLED", "true").strip().lower() != "false"
        )
        if not fallback_enabled:
            raise
        retrieval_mode = "local_keyword_fallback"
        retrieval_warning = str(exc)
        results = _local_keyword_fallback(query=query, config=config, k=top_k)

    probable_files = _build_probable_files(results)

    preview_chunks = [
        {
            "source": item.get("source"),
            "score": item.get("score"),
            "content_preview": (item.get("content") or "")[:300],
        }
        for item in results[:5]
    ]

    suggestion_lines = []
    for file_item in probable_files[:3]:
        suggestion_lines.append(
            f"- Review `{file_item['source']}` (matches={file_item['matches']}, "
            f"best_score={file_item['best_score']})"
        )
    if not suggestion_lines:
        suggestion_lines.append(
            "- No strong matches found. Expand query or increase ORCHESTRATOR_RAG_TOP_K."
        )

    fallback_summary = "\n".join(
        [
            "Potential root cause areas from RAG:",
            *suggestion_lines,
            "Validate by reproducing the issue with logging around these modules.",
        ]
    )
    suggested_fixes = _fallback_suggestions(probable_files)
    llm_model = None

    try:
        summary, llm_suggestions, model_name = _synthesize_with_llm(
            incident=incident,
            query=query,
            probable_files=probable_files,
            results=results,
        )
        if llm_suggestions:
            suggested_fixes = llm_suggestions
        llm_model = model_name
    except Exception:
        summary = fallback_summary

    return {
        "query": query,
        "summary": summary,
        "probable_files": probable_files,
        "top_chunks": preview_chunks,
        "suggested_fixes": suggested_fixes,
        "llm_model": llm_model,
        "retrieval_mode": retrieval_mode,
        "retrieval_warning": retrieval_warning,
    }
