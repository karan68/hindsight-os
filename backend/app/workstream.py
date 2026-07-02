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


WorkstreamSource = Literal["github", "telegram", "codex", "jira", "live_chat", "simulator"]
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
    primary_evidence_labels: list[str] = Field(default_factory=list)
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
    r"(?<!\w)@hindsight\b",
    r"(?<!\w)/hindsight\b",
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


def _contains_term(text: str, term: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"
    return bool(re.search(pattern, text))


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


def _metadata_analysis_blocks(metadata: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    for key, label in (
        ("title", "Title"),
        ("body", "Body"),
        ("summary", "Summary"),
        ("diff", "Diff"),
        ("comment", "Comment"),
    ):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            blocks.append(f"{label}:\n{_analysis_text(value)}")
    return blocks


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
    protected_terms = [term for term in _PROTECTED_TERMS if _contains_term(text, term)]

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
        blocks = [content, *_metadata_analysis_blocks(event.metadata)]
        body = "\n\n".join(block for block in blocks if block.strip())
        return (
            f"GitHub {event.event_type} by {event.actor or 'unknown actor'}:\n"
            f"{body}\n"
            f"Changed files: {files}"
        ).strip()
    if event.source == "telegram":
        return f"Telegram message by {event.actor or 'unknown actor'}:\n{content}"
    if event.source == "live_chat":
        return f"Live chat message by {event.actor or 'unknown actor'}:\n{content}"
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


def _unique_labels(*groups: list[str]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for label in group or []:
            if label and label not in seen:
                seen.add(label)
                labels.append(label)
    return labels


def evidence_labels(warning: WarningCard | None) -> list[str]:
    if warning is None:
        return []
    vector_labels = [item.label for item in warning.evidence]
    return _unique_labels(vector_labels, warning.graph_cited, warning.conflicting_memories)


_LABEL_STOPWORDS = {
    "a",
    "an",
    "and",
    "architecture",
    "branch",
    "change",
    "changes",
    "demo",
    "file",
    "for",
    "github",
    "in",
    "integration",
    "memory",
    "of",
    "on",
    "or",
    "payload",
    "pr",
    "product",
    "proof",
    "pull",
    "request",
    "risk",
    "service",
    "source",
    "the",
    "to",
    "truth",
    "warning",
}


def _label_tokens(label: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", label.lower())
        if len(token) > 2 and token not in _LABEL_STOPWORDS
    }


def primary_evidence_labels(warning: WarningCard | None, *, limit: int = 3) -> list[str]:
    if warning is None:
        return []

    cited = {label.lower(): idx for idx, label in enumerate(warning.conflicting_memories or [])}
    graph_cited = {label.lower() for label in warning.graph_cited or []}
    vector_cited = {label.lower() for label in warning.vector_cited or []}
    summary = (warning.summary or "").lower()
    proposal_summary = f"{warning.proposal or ''}\n{warning.summary or ''}".lower()
    evidence_by_label = {item.label: item for item in warning.evidence}
    scored: list[tuple[int, int, str]] = []
    for idx, label in enumerate(evidence_labels(warning)):
        evidence = evidence_by_label.get(label)
        node_sets = {item.lower() for item in (evidence.node_sets if evidence else [])}
        evidence_text = f"{label} {evidence.snippet if evidence else ''} {evidence.raw if evidence else ''}"
        evidence_overlap = len(_label_tokens(evidence_text) & set(re.findall(r"[a-z0-9]+", proposal_summary)))
        source_truth_match = "source of truth" in label.lower() and "source of truth" in proposal_summary
        summary_match = label.lower() in summary
        cited_match = label.lower() in cited
        graph_topic_match = label.lower() in graph_cited and source_truth_match

        if not (cited_match or summary_match or graph_topic_match or evidence_overlap >= 2):
            continue

        score = 0
        if cited_match:
            score += 100 - cited[label.lower()]
        if label.lower() in graph_cited:
            score += 45
        if label.lower() in vector_cited:
            score += 25
        if summary_match:
            score += 35
        score += 6 * evidence_overlap
        if source_truth_match:
            score += 170
        if "source of truth" in label.lower() and "authoritative" in proposal_summary:
            score += 80
        if "trusted" in node_sets:
            score += 25
        if "architecture-decision" in node_sets:
            score += 20
        if "incident-learning" in node_sets:
            score += 18
        if "policy" in node_sets or "compliance" in node_sets:
            score += 12
        if label.startswith("ADR-"):
            score += 15
        if label.startswith("INC-"):
            score += 12
        if evidence and (evidence.status == "obsolete" or "brainstorm" in node_sets):
            score -= 80
        scored.append((score, -idx, label))

    scored.sort(reverse=True)
    if scored:
        return [label for _, _, label in scored[:limit]]
    return evidence_labels(warning)[:limit]


def _load_records() -> list[WorkstreamRecord]:
    if not _EVENTS_FILE.exists():
        return []
    raw = json.loads(_EVENTS_FILE.read_text(encoding="utf-8"))
    return [WorkstreamRecord.model_validate(item) for item in raw]


def _save_record(record: WorkstreamRecord) -> None:
    _EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    records = [record, *[item for item in _load_records() if item.id != record.id]][:_MAX_EVENTS]
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
        primary_evidence_labels=primary_evidence_labels(warning),
        evidence_labels=evidence_labels(warning),
        ops=ops,
    )
    _save_record(persisted)
    return WorkstreamIngestResponse(record=persisted, warning=warning)