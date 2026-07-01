from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Classification(str, Enum):
    conflict = "conflict"
    confirmation = "confirmation"
    duplicate = "duplicate"
    stale_assumption = "stale_assumption"
    unrelated = "unrelated"
    insufficient_evidence = "insufficient_evidence"


class OpEvent(BaseModel):
    """One real Cognee/LLM operation, timed — a line in the live ops console."""

    op: str
    params: dict[str, Any] = {}
    status: Literal["ok", "error"] = "ok"
    duration_ms: int = 0
    detail: str = ""
    raw: str | None = None
    ts: str = ""


class ThreatTactic(str, Enum):
    none = "none"
    authority_spoof = "authority_spoof"
    instruction_override = "instruction_override"
    fabricated_approval = "fabricated_approval"
    urgency_coercion = "urgency_coercion"
    social_engineering = "social_engineering"


class ClassifierVerdict(BaseModel):
    """Structured output the LLM returns when reasoning over recalled evidence."""

    classification: Classification
    confidence: float = 0.5
    summary: str = ""
    conflicting_memories: list[str] = []
    recommended_action: Literal["warn", "allow", "ask_human", "remember_new_info"] = "ask_human"
    limits: str = ""
    # --- Sentinel: memory-integrity / adversarial-intent assessment ---
    manipulation_risk: float = 0.0
    manipulation_tactic: ThreatTactic = ThreatTactic.none
    is_poisoning: bool = False
    threat_rationale: str = ""


class GroundedAnswer(BaseModel):
    """Structured output for a Q&A recall answer grounded in retrieved memory."""

    answer: str = ""


class MemoryItem(BaseModel):
    id: str
    label: str
    text: str
    node_sets: list[str]
    status: Literal["active", "obsolete", "forgotten"] = "active"
    source: str = ""


class SeedResponse(BaseModel):
    dataset: str
    mode: Literal["demo", "cognee"]
    items: list[MemoryItem]
    lifecycle: list[str]


class ProposalRequest(BaseModel):
    proposal: str = Field(min_length=3)


class AskRequest(BaseModel):
    question: str = Field(min_length=3)


class EvidenceItem(BaseModel):
    id: str
    label: str
    snippet: str
    node_sets: list[str] = []
    score: float | None = None
    data_id: str | None = None
    chunk_index: int | None = None
    status: str = "active"
    is_target: bool = False
    raw: str | None = None


class WarningCard(BaseModel):
    id: str
    proposal: str
    classification: Classification
    confidence: float = Field(ge=0, le=1)
    summary: str
    recommended_action: Literal["warn", "allow", "ask_human", "remember_new_info"]
    evidence: list[EvidenceItem]
    limits: str
    session_id: str | None = None
    qa_id: str | None = None
    mode: Literal["demo", "cognee"] = "demo"
    reasoning: str = ""
    conflicting_memories: list[str] = []
    raw_context: str = ""
    # --- Graph-native retrieval: the multi-hop reasoning path Cognee walked ---
    reasoning_path: list[str] = []
    graph_nodes: list[str] = []
    vector_cited: list[str] = []
    graph_cited: list[str] = []
    retrieval_note: str = ""
    # --- Sentinel threat assessment ---
    manipulation_risk: float = 0.0
    manipulation_tactic: str = "none"
    is_poisoning: bool = False
    threat_id: str = ""
    threat_rationale: str = ""
    recommended_control: Literal["allow", "warn", "quarantine"] = "allow"
    ops: list[OpEvent] = []
    latency_ms: int = 0


class FeedbackRequest(BaseModel):
    useful: bool


class FeedbackResponse(BaseModel):
    warning_id: str
    feedback_score: int
    improve_status: Literal[
        "queued", "completed", "demo_recorded", "skipped", "blocked_quarantined"
    ]
    recall_after_feedback: str
    lifecycle: list[str]
    mode: Literal["demo", "cognee"] = "demo"
    blocked: bool = False
    threat_id: str = ""
    ops: list[OpEvent] = []


class AskResponse(BaseModel):
    question: str
    answer: str
    evidence: list[EvidenceItem] = []
    mode: Literal["demo", "cognee"] = "demo"
    ops: list[OpEvent] = []
    latency_ms: int = 0


class LedgerEntry(BaseModel):
    """One persisted feedback decision — the visible record of self-correction."""

    id: str
    ts: str
    proposal: str
    classification: str
    cited: list[str] = []
    feedback: Literal["useful", "wrong", "quarantine"]
    feedback_score: int
    improve_status: str
    answer: str = ""
    mode: Literal["demo", "cognee"] = "demo"
    blocked: bool = False


class ForgetResponse(BaseModel):
    data_id: str
    removed: list[str]
    preserved: list[str]
    recall_after_forget: str
    lifecycle: list[str]
    mode: Literal["demo", "cognee"] = "demo"
    before: list[EvidenceItem] = []
    after: list[EvidenceItem] = []
    graph_before: dict[str, int] = {}
    graph_after: dict[str, int] = {}
    ops: list[OpEvent] = []


class GraphNode(BaseModel):
    id: str
    label: str
    type: str = ""
    group: str = ""
    node_sets: list[str] = []
    content_hash: str = ""


class GraphEdge(BaseModel):
    source: str
    target: str
    rel: str = ""


class GraphSnapshot(BaseModel):
    mode: Literal["demo", "cognee"] = "demo"
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    node_count: int = 0
    edge_count: int = 0
    truncated: bool = False
    ops: list[OpEvent] = []


class DemoState(BaseModel):
    dataset: str
    mode: Literal["demo", "cognee"]
    seeded: bool
    memories: list[MemoryItem]
    latest_warning: WarningCard | None = None
    lifecycle: list[str] = []
    ledger: list[LedgerEntry] = []
    llm_model: str = ""
    llm_provider: str = ""
    llm_endpoint: str = ""
    embedding_model: str = ""
    embedding_provider: str = ""
    embedding_dims: str = ""
    structured_framework: str = ""
    cognee_version: str = ""
