from __future__ import annotations

from app.models import Classification, EvidenceItem, WarningCard


SOT_KEYWORDS = ("second source of truth", "authoritative", "source of truth")
STORAGE_KEYWORDS = ("spanner", "redis", "store", "storage", "database")
CACHE_KEYWORDS = ("memcache", "read-through", "cache", "cdn")
INFINITE_KEYWORDS = ("infinite scroll", "infinite-scroll")


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _snippet(text: str, length: int = 220) -> str:
    return text if len(text) <= length else f"{text[: length - 3]}..."


def classify_proposal(proposal: str, evidence: list[EvidenceItem]) -> WarningCard:
    lowered = proposal.lower()
    evidence_labels = [item.label for item in evidence]

    # Introducing a second authoritative store conflicts with ADR-021.
    if _contains_any(lowered, SOT_KEYWORDS) and _contains_any(lowered, STORAGE_KEYWORDS):
        return WarningCard(
            id="warning-second-source-of-truth",
            proposal=proposal,
            classification=Classification.conflict,
            confidence=0.90,
            summary=(
                "The proposal conflicts with ADR-021: a service must not introduce a second "
                "authoritative store. Spanner is the source of truth; caches stay non-authoritative."
            ),
            recommended_action="warn",
            evidence=evidence,
            limits="Deterministic demo classifier — only the seeded source-of-truth conflict path is flagged.",
        )

    if _contains_any(lowered, INFINITE_KEYWORDS):
        return WarningCard(
            id="warning-infinite-scroll",
            proposal=proposal,
            classification=Classification.conflict,
            confidence=0.84,
            summary="EXP-208 tested infinite scroll and rolled it back; pagination was kept.",
            recommended_action="warn",
            evidence=evidence,
            limits="Based on the seeded experiment result EXP-208.",
        )

    if "pagination" in lowered:
        return WarningCard(
            id="warning-pagination-confirmation",
            proposal=proposal,
            classification=Classification.confirmation,
            confidence=0.86,
            summary="The proposal confirms EXP-208: pagination is retained over infinite scroll.",
            recommended_action="allow",
            evidence=evidence,
            limits="Confirmation based on retrieved memories: " + ", ".join(evidence_labels[:3]),
        )

    if _contains_any(lowered, CACHE_KEYWORDS) and (
        "non-authoritative" in lowered or "read-through" in lowered or "ttl" in lowered
    ):
        return WarningCard(
            id="warning-cache-safe",
            proposal=proposal,
            classification=Classification.confirmation,
            confidence=0.82,
            summary="A non-authoritative cache in front of Spanner aligns with ADR-021.",
            recommended_action="allow",
            evidence=evidence,
            limits="A cache must remain non-authoritative and regenerable from Spanner.",
        )

    return WarningCard(
        id="warning-insufficient-evidence",
        proposal=proposal,
        classification=Classification.insufficient_evidence,
        confidence=0.42,
        summary="Hindsight did not find enough seeded evidence to make a conflict claim.",
        recommended_action="ask_human",
        evidence=evidence,
        limits="No conflict is claimed unless prior memory clearly supports it.",
    )


def make_evidence(memories: list, proposal: str) -> list[EvidenceItem]:
    lowered = proposal.lower()
    scored = []
    for memory in memories:
        # Obsolete/forgotten memories are not trustworthy evidence — the obsolete
        # brainstorm note is the item we later forget, not support for a conflict.
        if memory.status in ("forgotten", "obsolete"):
            continue
        text = f"{memory.label} {memory.text} {' '.join(memory.node_sets)}".lower()
        score = 0
        for token in (
            "spanner",
            "cache",
            "memcache",
            "redis",
            "storage",
            "source of truth",
            "pagination",
            "infinite scroll",
            "canary",
            "release",
            "pii",
            "logging",
            "dependency",
            "registry",
            "grpc",
            "api",
        ):
            if token in lowered and token in text:
                score += 1
        if score:
            scored.append((score, memory))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        EvidenceItem(
            id=memory.id,
            label=memory.label,
            snippet=_snippet(memory.text),
            node_sets=memory.node_sets,
        )
        for _, memory in scored[:4]
    ]


_MANIPULATION_TACTICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "instruction_override",
        (
            "ignore adr",
            "ignore the adr",
            "ignore prior",
            "ignore previous",
            "ignore the prior",
            "ignore the previous",
            "disregard",
            "overwrite the",
            "overwrite memory",
            "overwrite the decision",
            "rescind",
            "override the",
            "overrule",
        ),
    ),
    (
        "authority_spoof",
        (
            "approved by",
            "signed off",
            "sign-off by",
            "already approved",
            "was approved by",
            "leadership approved",
            "exec approved",
        ),
    ),
)


def detect_manipulation(proposal: str) -> tuple[str, float]:
    """Deterministic manipulation-tactic detector used when the LLM Sentinel classifier
    is unavailable (content-policy refusal or timeout).

    Conservative by design: returns ("none", 0.0) unless explicit instruction-override or
    authority-spoof language is present, so a legitimate proposal is never quarantined by
    this fallback."""
    lowered = (proposal or "").lower()
    for tactic, keywords in _MANIPULATION_TACTICS:
        if any(keyword in lowered for keyword in keywords):
            return tactic, 0.9
    return "none", 0.0
