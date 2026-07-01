from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models import OpEvent, WarningCard
from app.service import analyze_proposal_text
from app.trace import record


WorkstreamSource = Literal["github", "slack", "codex", "jira", "simulator"]
WorkstreamOutcome = Literal[
    "ignored_low_risk",
    "allowed",
    "warned",
    "quarantined",
    "needs_human_review",
]


class WorkstreamEvent(BaseModel):
    source: WorkstreamSource
    event_type: str = "message"
    actor: str = ""
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    event_id: str | None = None
    ts: str | None = None


class WorkstreamScreening(BaseModel):
    decision: Literal["skip", "check"]
    risk_score: float = Field(ge=0, le=1)
    reason: str
    matched_rules: list[str] = Field(default_factory=list)
    protected_terms: list[str] = Field(default_factory=list)
    explicit_request: bool = False


class WorkstreamRecord(BaseModel):
    id: str
    ts: str
    source: WorkstreamSource
    event_type: str
    actor: str = ""
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    screening: WorkstreamScreening
    outcome: WorkstreamOutcome
    warning_id: str | None = None
    classification: str | None = None
    recommended_control: str | None = None
    evidence_labels: list[str] = Field(default_factory=list)
    ops: list[OpEvent] = Field(default_factory=list)


class WorkstreamIngestResponse(BaseModel):
    record: WorkstreamRecord
    warning: WarningCard | None = None


_EVENTS_FILE = Path(
    os.getenv(
        "HINDSIGHT_WORKSTREAM_EVENTS_FILE",
        str(Path(__file__).resolve().parent.parent / "workstream_events.json"),
    )
)
_MAX_EVENTS = 100

_EXPLICIT_PATTERNS = (
    r"\b@hindsight\b",
    r"\b/hindsight\b",
    r"\bhindsight\s+check\b",
    r"\bremember\s+this\b",
    r"\bstore\s+this\s+(?:in|as)\s+memory\b",
)
_DECISION_PATTERNS = (
    r"\bwe\s+decided\b",
    r"\bapproved\b",
    r"\bsource\s+of\s+truth\b",
    r"\bmigrate\b",
    r"\breplace\b",
    r"\bdeprecate\b",
    r"\bignore\s+(?:the\s+)?(?:old|previous|prior)\b",
    r"\boverwrite\s+(?:memory|decision|adr)\b",
    r"\brescind\b",
)
_PROTECTED_TERMS = (
    "billing",
    "invoice",
    "payment",
    "refund",
    "tax",
    "auth",
    "security",
    "compliance",
    "privacy",
    "pii",
    "source of truth",
    "storage",
    "database",
    "spanner",
    "redis",
    "dynamodb",
)
_PROTECTED_PATHS = (
    "billing/",
    "payments/",
    "auth/",
    "security/",
    "compliance/",
    "infra/",
)
_LOW_SIGNAL_EVENT_TYPES = {"reaction", "typing", "presence", "emoji"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _matched(patterns: tuple[str, ...], text: str) -> list[str]:
    return [pattern for pattern in patterns if re.search(pattern, text, re.IGNORECASE)]


def _metadata_text(metadata: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("title", "body", "summary", "diff", "comment"):
        value = metadata.get(key)
        if isinstance(value, str):
            values.append(value)
    changed_files = metadata.get("changed_files") or metadata.get("files") or []
    if isinstance(changed_files, list):
        values.extend(str(item) for item in changed_files)
    return "\n".join(values)


def _analysis_text(text: str) -> str:
    """Remove integration command wrappers before retrieval/classification.

    Commands such as `/hindsight check` are routing signals, not proposal
    content. Leaving them as the first line can cause retrieval to search the
    command instead of the memory-relevant change.
    """
    cleaned: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered in {"/hindsight", "/hindsight check", "@hindsight", "@hindsight check"}:
            continue
        if lowered.startswith("/hindsight "):
            remainder = stripped.split(maxsplit=1)[1]
            if remainder.lower() in {"check", "verify", "review"}:
                continue
            cleaned.append(remainder)
            continue
        if lowered.startswith("@hindsight "):
            remainder = stripped.split(maxsplit=1)[1]
            if remainder.lower() in {"check", "verify", "review"}:
                continue
            cleaned.append(remainder)
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _screen_event(event: WorkstreamEvent) -> WorkstreamScreening:
    if event.event_type.lower() in _LOW_SIGNAL_EVENT_TYPES:
        return WorkstreamScreening(
            decision="skip",
            risk_score=0.0,
            reason="low-signal event type",
            matched_rules=[f"event_type:{event.event_type}"],
        )

    text = f"{event.content}\n{_metadata_text(event.metadata)}".lower()
    explicit = _matched(_EXPLICIT_PATTERNS, text)
    decision = _matched(_DECISION_PATTERNS, text)
    protected_terms = [term for term in _PROTECTED_TERMS if term in text]

    changed_files = event.metadata.get("changed_files") or event.metadata.get("files") or []
    changed_text = "\n".join(str(item).replace("\\", "/").lower() for item in changed_files)
    protected_paths = [path for path in _PROTECTED_PATHS if path in changed_text]

    score = 0.0
    matched_rules: list[str] = []
    if explicit:
        score += 0.65
        matched_rules.append("explicit_hindsight_request")
    if decision:
        score += 0.25
        matched_rules.append("decision_language")
    if protected_terms:
        score += 0.25
        matched_rules.append("protected_topic")
    if protected_paths:
        score += 0.35
        matched_rules.append("protected_path")
    if event.source == "github" and event.event_type.startswith("pr"):
        score += 0.10
        matched_rules.append("github_pr_context")

    score = min(score, 1.0)
    should_check = bool(explicit or protected_paths or (decision and protected_terms) or score >= 0.5)
    reason = "memory-risk signal matched" if should_check else "no memory-changing signal matched"
    return WorkstreamScreening(
        decision="check" if should_check else "skip",
        risk_score=score,
        reason=reason,
        matched_rules=matched_rules,
        protected_terms=protected_terms[:8],
        explicit_request=bool(explicit),
    )


def _event_to_proposal(event: WorkstreamEvent) -> str:
    content = _analysis_text(event.content)
    if event.source == "github":
        changed_files = event.metadata.get("changed_files") or event.metadata.get("files") or []
        files = ", ".join(str(item) for item in changed_files[:12]) if isinstance(changed_files, list) else ""
        return (
            f"GitHub {event.event_type} by {event.actor or 'unknown actor'}:\n"
            f"{content}\n"
            f"Changed files: {files}"
        ).strip()
    if event.source == "slack":
        return f"Slack message by {event.actor or 'unknown actor'}:\n{content}"
    if event.source == "codex":
        return f"Codex/agent session event by {event.actor or 'unknown actor'}:\n{content}"
    if event.source == "jira":
        return f"Jira {event.event_type} by {event.actor or 'unknown actor'}:\n{content}"
    return content


def _outcome_for_warning(warning: WarningCard) -> WorkstreamOutcome:
    classification = getattr(warning.classification, "value", str(warning.classification))
    if warning.is_poisoning or warning.recommended_control == "quarantine":
        return "quarantined"
    if classification in {"conflict", "stale_assumption"} or warning.recommended_control == "warn":
        return "warned"
    if warning.recommended_action == "allow":
        return "allowed"
    return "needs_human_review"


def _load_records() -> list[WorkstreamRecord]:
    if not _EVENTS_FILE.exists():
        return []
    raw = json.loads(_EVENTS_FILE.read_text(encoding="utf-8"))
    return [WorkstreamRecord.model_validate(item) for item in raw]


def _save_record(record: WorkstreamRecord) -> None:
    _EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    records = [record, *_load_records()][:_MAX_EVENTS]
    _EVENTS_FILE.write_text(
        json.dumps([item.model_dump(mode="json") for item in records], indent=2),
        encoding="utf-8",
    )


def list_workstream_events() -> list[WorkstreamRecord]:
    return _load_records()


async def ingest_workstream_event(event: WorkstreamEvent) -> WorkstreamIngestResponse:
    ops: list[OpEvent] = []
    screening = _screen_event(event)
    record(
        ops,
        "workstream.screen",
        {"source": event.source, "event_type": event.event_type},
        detail=f"{screening.decision}: {screening.reason}",
        raw=screening.model_dump_json(indent=2),
    )

    record_id = event.event_id or f"evt-{uuid.uuid4().hex[:10]}"
    ts = event.ts or _now()
    warning: WarningCard | None = None
    outcome: WorkstreamOutcome = "ignored_low_risk"

    if screening.decision == "check":
        proposal = _event_to_proposal(event)
        warning = await analyze_proposal_text(proposal, persist_latest=False)
        ops.extend(warning.ops)
        outcome = _outcome_for_warning(warning)

    persisted = WorkstreamRecord(
        id=record_id,
        ts=ts,
        source=event.source,
        event_type=event.event_type,
        actor=event.actor,
        content=event.content,
        metadata=event.metadata,
        screening=screening,
        outcome=outcome,
        warning_id=warning.id if warning else None,
        classification=(
            getattr(warning.classification, "value", str(warning.classification)) if warning else None
        ),
        recommended_control=warning.recommended_control if warning else None,
        evidence_labels=[item.label for item in warning.evidence] if warning else [],
        ops=ops,
    )
    _save_record(persisted)
    return WorkstreamIngestResponse(record=persisted, warning=warning)