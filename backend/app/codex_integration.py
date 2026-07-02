from __future__ import annotations

import hashlib
import os
from typing import Literal

from pydantic import BaseModel, Field

from app.telegram_integration import TelegramPostResult, send_telegram_message
from app.workstream import WorkstreamEvent, WorkstreamIngestResponse, ingest_workstream_event


class CodexSessionCheckRequest(BaseModel):
    transcript: str = Field(min_length=3)
    session_id: str = "manual-codex-session"
    actor: str = "codex-agent"
    event_type: Literal["agent_message", "agent_memory_write", "transcript"] = "transcript"
    event_id: str | None = None
    source_label: str = "manual-transcript"
    transcript_char_limit: int = Field(default=12000, ge=1000, le=50000)
    notify_telegram: bool | None = None
    telegram_chat_id: str | None = None


class CodexSessionCheckResponse(BaseModel):
    session_id: str
    event_id: str
    source_label: str
    transcript_chars: int
    transcript_truncated: bool
    can_remember: bool
    blocked: bool
    notification: TelegramPostResult | None = None
    ingest: WorkstreamIngestResponse


def _bounded_transcript(text: str, limit: int) -> tuple[str, bool]:
    text = text.strip()
    if len(text) <= limit:
        return text, False
    head = text[: limit - 220].rstrip()
    return f"{head}\n\n[Hindsight truncated {len(text) - len(head)} chars from this transcript]", True


def _should_notify(request: CodexSessionCheckRequest) -> bool:
    if request.notify_telegram is not None:
        return request.notify_telegram
    return os.getenv("HINDSIGHT_CODEX_NOTIFY_TELEGRAM", "").lower() in {"1", "true", "yes"}


def _notification_text(response: WorkstreamIngestResponse, session_id: str) -> str:
    record = response.record
    warning = response.warning
    primary = record.primary_evidence_labels or record.evidence_labels[:3]
    evidence = "\n".join(f"- {label}" for label in primary) or "- none"
    summary = warning.summary if warning else record.screening.reason
    return (
        "Hindsight OS: Codex output flagged\n"
        f"Session: {session_id}\n"
        f"Outcome: {record.outcome}\n"
        f"Classification: {record.classification or 'none'}\n"
        f"Can remember: {'yes' if record.outcome in {'allowed', 'ignored_low_risk'} else 'no'}\n\n"
        f"{summary}\n\n"
        f"Primary evidence:\n{evidence}"
    )[:3900]


def _notify_telegram(request: CodexSessionCheckRequest, response: WorkstreamIngestResponse) -> TelegramPostResult | None:
    if not _should_notify(request):
        return None
    chat_id = (request.telegram_chat_id or os.getenv("HINDSIGHT_TELEGRAM_NOTIFY_CHAT_ID", "")).strip()
    if not chat_id:
        return TelegramPostResult(
            attempted=False,
            posted=False,
            error="HINDSIGHT_TELEGRAM_NOTIFY_CHAT_ID is not configured",
        )
    return send_telegram_message(chat_id, _notification_text(response, request.session_id))


async def check_codex_session(request: CodexSessionCheckRequest) -> CodexSessionCheckResponse:
    transcript, truncated = _bounded_transcript(request.transcript, request.transcript_char_limit)
    digest = hashlib.sha256(f"{request.session_id}\n{transcript}".encode("utf-8")).hexdigest()[:12]
    event_id = request.event_id or f"codex-{request.session_id}-{digest}"
    event = WorkstreamEvent(
        source="codex",
        event_type=request.event_type,
        actor=request.actor,
        content=transcript,
        metadata={
            "session_id": request.session_id,
            "source_label": request.source_label,
            "transcript_chars": len(request.transcript),
            "transcript_truncated": truncated,
        },
        event_id=event_id,
    )
    ingest = await ingest_workstream_event(event)
    blocked = ingest.record.outcome == "quarantined"
    can_remember = ingest.record.outcome in {"allowed", "ignored_low_risk"}
    notification = None if can_remember else _notify_telegram(request, ingest)
    return CodexSessionCheckResponse(
        session_id=request.session_id,
        event_id=event_id,
        source_label=request.source_label,
        transcript_chars=len(request.transcript),
        transcript_truncated=truncated,
        can_remember=can_remember,
        blocked=blocked,
        notification=notification,
        ingest=ingest,
    )
