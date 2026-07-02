from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

from app.workstream import WorkstreamEvent, WorkstreamIngestResponse, ingest_workstream_event


class CodexSessionCheckRequest(BaseModel):
    transcript: str = Field(min_length=3)
    session_id: str = "manual-codex-session"
    actor: str = "codex-agent"
    event_type: Literal["agent_message", "agent_memory_write", "transcript"] = "transcript"
    event_id: str | None = None
    source_label: str = "manual-transcript"
    transcript_char_limit: int = Field(default=12000, ge=1000, le=50000)


class CodexSessionCheckResponse(BaseModel):
    session_id: str
    event_id: str
    source_label: str
    transcript_chars: int
    transcript_truncated: bool
    can_remember: bool
    blocked: bool
    ingest: WorkstreamIngestResponse


def _bounded_transcript(text: str, limit: int) -> tuple[str, bool]:
    text = text.strip()
    if len(text) <= limit:
        return text, False
    head = text[: limit - 220].rstrip()
    return f"{head}\n\n[Hindsight truncated {len(text) - len(head)} chars from this transcript]", True


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
    return CodexSessionCheckResponse(
        session_id=request.session_id,
        event_id=event_id,
        source_label=request.source_label,
        transcript_chars=len(request.transcript),
        transcript_truncated=truncated,
        can_remember=can_remember,
        blocked=blocked,
        ingest=ingest,
    )