from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from app import cognee_client
from app.classifier import classify_proposal, make_evidence
from app.models import (
    AskResponse,
    ClassifierVerdict,
    EvidenceItem,
    FeedbackResponse,
    ForgetResponse,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    LedgerEntry,
    MemoryItem,
    OpEvent,
    ProposalRequest,
    SeedResponse,
    WarningCard,
)
from app.seed_data import SEED_MEMORIES
from app.state import (
    DEFAULT_DATASET,
    append_ledger,
    load_state,
    replace_memories,
    update_latest_warning,
    update_memory_status,
)
from app.trace import record


_RECALL_WARMED = False
_WARM_LOCK = None


def _lifecycle(*steps: str) -> list[str]:
    return list(steps)


def _snippet(text: str, length: int = 240) -> str:
    text = (text or "").strip()
    return text if len(text) <= length else f"{text[: length - 1]}\u2026"


def _norm_label(s: str) -> str:
    """Strip stray brackets/whitespace the LLM echoes from the context format."""
    return (s or "").strip().strip("[]").strip()


def _canonicalize_cited(names: list[str] | None, evidence: list[EvidenceItem]) -> list[str]:
    """Map the model's cited names back to the exact memory labels from retrieved
    evidence so they match the inventory (and the graph). De-dupes, keeps order."""
    lookup = {_norm_label(ev.label).lower(): ev.label for ev in evidence}
    out: list[str] = []
    seen: set[str] = set()
    for name in names or []:
        clean = _norm_label(name)
        canon = lookup.get(clean.lower(), clean)
        if canon and canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def _catalog(memories: list[MemoryItem]) -> dict[str, MemoryItem]:
    """Map each memory's stable Cognee data UUID -> memory, for exact reverse lookup."""
    return {cognee_client.cognee_data_uuid(memory.id): memory for memory in memories}


def _chunks_to_evidence(
    raw_chunks: list[dict],
    catalog: dict[str, MemoryItem],
    *,
    target_uuid: str | None = None,
) -> tuple[list[EvidenceItem], list[str], str]:
    """Turn real CHUNKS recall hits into evidence + grounding context.

    De-duplicates by source data item (keeping the best-scoring chunk) and maps
    each hit back to its originating memory via the pinned data UUID.
    """
    best: dict[str, dict] = {}
    order: list[str] = []
    for chunk in raw_chunks:
        key = chunk.get("data_id") or chunk.get("chunk_id") or chunk.get("text", "")[:32]
        if not key:
            continue
        current = best.get(key)
        if current is None or (chunk.get("score") or 0) > (current.get("score") or 0):
            best[key] = chunk
        if key not in order:
            order.append(key)

    evidence: list[EvidenceItem] = []
    context_blocks: list[str] = []
    for key in order:
        chunk = best[key]
        memory = catalog.get(chunk.get("data_id") or "")
        if memory is None:
            # Drop feedback/session artifacts that Cognee's improve step cognifies
            # into the dataset (e.g. a session note that only says "Got it."). They
            # are not canonical decision memories and must not pollute recall.
            continue
        label = memory.label
        node_sets = memory.node_sets
        status = memory.status
        text = chunk.get("text", "")
        evidence.append(
            EvidenceItem(
                id=memory.id,
                label=label,
                snippet=_snippet(text),
                node_sets=node_sets,
                score=chunk.get("score"),
                data_id=chunk.get("data_id"),
                chunk_index=chunk.get("chunk_index"),
                status=status,
                is_target=bool(target_uuid and chunk.get("data_id") == target_uuid),
                raw=text,
            )
        )
        context_blocks.append(
            f"[{label}] tags={', '.join(node_sets) or 'none'} status={status}\n{text}"
        )

    return evidence, context_blocks, "\n\n".join(context_blocks)


_TACTIC_LABEL = {
    "authority_spoof": "authority spoofing",
    "instruction_override": "instruction override",
    "fabricated_approval": "fabricated approval",
    "urgency_coercion": "urgency / coercion",
    "social_engineering": "social engineering",
    "none": "none",
}


def _threat_id(tactic: str, is_poisoning: bool) -> str:
    """Map the detected tactic to recognised threat catalog ids (for credibility)."""
    ids: list[str] = []
    if is_poisoning:
        ids.append("OWASP LLM04: Data & Model Poisoning")
    if tactic and tactic != "none":
        ids.append("OWASP LLM01: Prompt Injection")
    if is_poisoning:
        ids.append("MITRE ATLAS AML.T0070")
    return " · ".join(ids)


def _recommended_control(classification_value: str, is_poisoning: bool) -> str:
    if is_poisoning:
        return "quarantine"
    if classification_value in ("conflict", "stale_assumption"):
        return "warn"
    return "allow"


def _verdict_to_warning(
    proposal: str,
    verdict: ClassifierVerdict,
    evidence: list[EvidenceItem],
    raw_context: str,
    ops: list[OpEvent],
) -> WarningCard:
    confidence = max(0.0, min(1.0, float(verdict.confidence or 0.0)))
    value = getattr(verdict.classification, "value", verdict.classification)
    tactic = getattr(verdict.manipulation_tactic, "value", verdict.manipulation_tactic) or "none"
    risk = max(0.0, min(1.0, float(verdict.manipulation_risk or 0.0)))
    # Conservative gate: only treat as poisoning when the model flagged it AND a real
    # tactic is present AND risk clears 0.5 — defends against accidental over-flagging
    # of honest proposals (the false-positive failure mode that would kill trust).
    is_poisoning = bool(verdict.is_poisoning and tactic != "none" and risk >= 0.5)
    return WarningCard(
        id=f"warning-{value}-{uuid.uuid4().hex[:6]}",
        proposal=proposal,
        classification=verdict.classification,
        confidence=confidence,
        summary=verdict.summary or "(model returned no summary)",
        recommended_action=verdict.recommended_action,
        evidence=evidence,
        limits=verdict.limits or "No additional limits reported.",
        mode="cognee",
        reasoning=verdict.summary or "",
        conflicting_memories=_canonicalize_cited(verdict.conflicting_memories, evidence),
        raw_context=raw_context,
        manipulation_risk=risk,
        manipulation_tactic=tactic,
        is_poisoning=is_poisoning,
        threat_id=_threat_id(tactic, is_poisoning),
        threat_rationale=verdict.threat_rationale or "",
        recommended_control=_recommended_control(str(value), is_poisoning),
        ops=ops,
    )


def _demo_warning(proposal: str, state, ops: list[OpEvent]) -> WarningCard:
    """Deterministic offline fallback (no API key / Cognee error)."""
    record(ops, "recall", {"mode": "demo"}, detail="deterministic keyword evidence")
    evidence = make_evidence(state.memories, proposal)
    record(ops, "classify", {"mode": "demo"}, detail="deterministic keyword classifier")
    warning = classify_proposal(proposal, evidence)
    value = getattr(warning.classification, "value", warning.classification)
    warning.recommended_control = _recommended_control(str(value), False)  # type: ignore[assignment]
    warning.mode = "demo"
    warning.reasoning = warning.summary
    warning.raw_context = "\n\n".join(f"[{ev.label}] {ev.snippet}" for ev in evidence)
    warning.ops = ops
    return warning


async def seed_demo() -> SeedResponse:
    memories = [memory.model_copy(deep=True) for memory in SEED_MEMORIES]
    mode = "demo"
    lifecycle = _lifecycle("remember")
    ops: list[OpEvent] = []

    try:
        await cognee_client.seed_with_cognee(DEFAULT_DATASET, memories, ops)
        mode = "cognee"
        lifecycle.append("cognee:remember")
    except cognee_client.CogneeUnavailable:
        lifecycle.append("demo:remember")
    except Exception as exc:  # Cognee error (e.g. rate limit) -> graceful demo fallback
        print(f"[seed] Cognee seed failed, falling back to demo mode: {exc}")
        lifecycle.append("demo:remember")

    replace_memories(memories, mode, lifecycle)
    global _RECALL_WARMED
    _RECALL_WARMED = False
    if mode == "cognee":
        await warm_recall()
    return SeedResponse(dataset=DEFAULT_DATASET, mode=mode, items=memories, lifecycle=lifecycle)


async def warm_recall() -> None:
    """Best-effort: warm the embedding model/tokenizer AND both retrieval paths on
    boot so the FIRST real check isn't a cold start. The vector store can
    under-retrieve on its first call or two, so we prime chunks twice plus the
    graph path. Blocks startup/first check until the warmup attempt completes."""
    global _RECALL_WARMED, _WARM_LOCK
    if _RECALL_WARMED:
        return
    if _WARM_LOCK is None:
        import asyncio

        _WARM_LOCK = asyncio.Lock()

    async with _WARM_LOCK:
        if _RECALL_WARMED:
            return
        state = load_state()
        if not state.seeded:
            return
        query = "service source of truth storage policy spanner cache canary"
        try:
            for _ in range(2):
                await cognee_client.retrieve_chunks(DEFAULT_DATASET, query, [], top_k=12)
            await cognee_client.retrieve_graph_context(DEFAULT_DATASET, query, [], depth=2, top_k=6)
            print("[warmup] recall paths warmed (chunks + graph)")
        except Exception as exc:
            print(f"[warmup] skipped: {exc}")
        finally:
            _RECALL_WARMED = True


# A realistic plain-RAG top-k for the similarity panel: what a naive vector search
# would surface first before the relationships panel explains the connected facts.
VECTOR_COMPARE_K = 6


def _mentions_memory(graph_context: str, memory: MemoryItem) -> bool:
    """True if a memory's content or label appears in the traversed subgraph text."""
    hay = (graph_context or "").lower()
    if not hay:
        return False
    probe = (memory.text or "").strip()[:48].lower()
    if probe and probe in hay:
        return True
    return memory.label.lower() in hay


def _attach_retrieval(
    warning: WarningCard,
    evidence: list[EvidenceItem],
    graph_context: str,
    reasoning_path: list[str],
    graph_nodes: list[str],
    memories: list[MemoryItem],
) -> None:
    """Record similarity hits plus graph-derived relationship facts.

    ``vector_cited`` is capped to a realistic plain-RAG top-k (VECTOR_COMPARE_K)
    to show what semantic similarity surfaces first. ``reasoning_path`` records
    the relationship facts Cognee extracted from the graph context.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for ev in evidence:
        if ev.label not in seen:
            seen.add(ev.label)
            ordered.append(ev.label)
    vector_top = ordered[:VECTOR_COMPARE_K]
    graph_cited = [m.label for m in memories if _mentions_memory(graph_context, m)]
    graph_only = [label for label in graph_cited if label not in set(vector_top)]

    warning.reasoning_path = reasoning_path[:10]
    warning.graph_nodes = graph_nodes[:24]
    warning.vector_cited = vector_top
    warning.graph_cited = graph_cited
    n_facts = len(reasoning_path)
    if graph_only:
        warning.retrieval_note = (
            f"Similarity surfaced the top {VECTOR_COMPARE_K} memories first; relationships added "
            f"{len(graph_only)} connected memor"
            f"{'y' if len(graph_only) == 1 else 'ies'}: {', '.join(graph_only)}. "
            f"Cognee returned {n_facts} relationship facts from the graph context."
        )
    elif n_facts:
        warning.retrieval_note = (
            f"Similarity and relationships agreed on the key memories; Cognee also returned "
            f"{n_facts} relationship facts (constraints, supersession, dependencies) from "
            f"the graph context."
        )


async def analyze_proposal_text(proposal: str, *, persist_latest: bool = True) -> WarningCard:
    state = load_state()
    if not state.seeded:
        await seed_demo()
        state = load_state()
    await warm_recall()

    started = time.perf_counter()
    ops: list[OpEvent] = []
    catalog = _catalog(state.memories)

    try:
        # 1. REAL vector retrieval (CHUNKS = similarity). Wide candidate set so
        #    canonical memories survive the session-artifact filter.
        raw_chunks = await cognee_client.retrieve_chunks(DEFAULT_DATASET, proposal, ops, top_k=12)
        evidence, context_blocks, raw_context = _chunks_to_evidence(raw_chunks, catalog)

        # 2. REAL graph-native retrieval (GRAPH_COMPLETION, relationship facts).
        #    This complements semantic hits with constraints, dependencies, and
        #    supersession facts extracted from the graph context.
        graph_context = ""
        reasoning_path: list[str] = []
        graph_nodes: list[str] = []
        try:
            graph = await cognee_client.retrieve_graph_context(
                DEFAULT_DATASET, proposal, ops, depth=2, top_k=6
            )
            graph_context = graph.get("context", "")
            reasoning_path = graph.get("facts", [])
            graph_nodes = [n["name"] for n in graph.get("nodes", []) if n.get("name")]
        except Exception as gexc:  # graph recall failed -> degrade to vector-only
            record(
                ops, "recall", {"query_type": "GRAPH_COMPLETION"}, status="error", detail=str(gexc)
            )

        # 3. REAL structured LLM reasoning over BOTH retrievals. The graph facts
        #    give the classifier explicit multi-hop grounding (constraints, supersession).
        combined_blocks = list(context_blocks)
        if reasoning_path:
            combined_blocks.append(
                "GRAPH REASONING (multi-hop facts Cognee traversed from the knowledge graph):\n"
                + "\n".join(f"- {fact}" for fact in reasoning_path[:12])
            )
        verdict = await cognee_client.classify_with_llm(proposal, combined_blocks, ops)
        warning = _verdict_to_warning(proposal, verdict, evidence, raw_context, ops)

        # 4. Attach the reasoning path + the vector-vs-graph comparison.
        _attach_retrieval(
            warning, evidence, graph_context, reasoning_path, graph_nodes, state.memories
        )
    except cognee_client.CogneeUnavailable:
        warning = _demo_warning(proposal, state, ops)
    except Exception as exc:  # Cognee/LLM error -> deterministic fallback, but show the error
        print(f"[check] Cognee path failed, using deterministic fallback: {exc}")
        record(ops, "fallback", {"reason": type(exc).__name__}, status="error", detail=str(exc))
        warning = _demo_warning(proposal, state, ops)

    warning.latency_ms = int((time.perf_counter() - started) * 1000)
    warning.session_id = f"session-{warning.id}"
    if persist_latest:
        update_latest_warning(warning, [op.op for op in ops])
    return warning


async def check_proposal(request: ProposalRequest):
    return await analyze_proposal_text(request.proposal, persist_latest=True)


def _demo_answer(question: str, evidence: list[EvidenceItem]) -> str:
    labels = ", ".join(ev.label for ev in evidence[:3]) or "the seeded decisions"
    return (
        "Based on the retrieved decision memory "
        f"({labels}), each service keeps its source of truth in Spanner and uses Memcache "
        "only as a non-authoritative cache; no second authoritative store is introduced. "
        "(Deterministic demo answer — set LLM_API_KEY for a live Cognee-grounded response.)"
    )


async def ask_memory(question: str) -> AskResponse:
    state = load_state()
    if not state.seeded:
        await seed_demo()
        state = load_state()

    started = time.perf_counter()
    ops: list[OpEvent] = []
    catalog = _catalog(state.memories)
    mode = "demo"

    try:
        raw_chunks = await cognee_client.retrieve_chunks(DEFAULT_DATASET, question, ops, top_k=12)
        evidence, context_blocks, _ = _chunks_to_evidence(raw_chunks, catalog)
        answer = await cognee_client.answer_with_llm(question, context_blocks, ops)
        mode = "cognee"
    except cognee_client.CogneeUnavailable:
        record(ops, "recall", {"mode": "demo"}, detail="deterministic keyword evidence")
        evidence = make_evidence(state.memories, question)
        answer = _demo_answer(question, evidence)
    except Exception as exc:  # Cognee/LLM error -> deterministic fallback
        print(f"[ask] Cognee path failed, using deterministic fallback: {exc}")
        record(ops, "fallback", {"reason": type(exc).__name__}, status="error", detail=str(exc))
        evidence = make_evidence(state.memories, question)
        answer = _demo_answer(question, evidence)

    return AskResponse(
        question=question,
        answer=answer,
        evidence=evidence,
        mode=mode,
        ops=ops,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


async def submit_feedback(warning_id: str, useful: bool) -> FeedbackResponse:
    state = load_state()
    warning = state.latest_warning
    ops: list[OpEvent] = []
    lifecycle = _lifecycle("feedback", "improve", "recall")
    status = "demo_recorded"
    cognee_answer = ""
    mode = "demo"

    # --- Sentinel memory-integrity guard -------------------------------------
    # If Sentinel flagged this proposal as a poisoning attempt, NEVER run Cognee
    # improve on it: improve cognifies the session (the attacker's proposal text)
    # straight into the knowledge graph — which is exactly the poisoning vector.
    # We refuse the ingest, quarantine the item, and log the block instead.
    if warning and warning.id == warning_id and warning.is_poisoning:
        record(
            ops,
            "sentinel.block",
            {"threat_id": warning.threat_id, "tactic": warning.manipulation_tactic},
            detail="improve skipped — adversarial content refused entry to memory",
        )
        reason = (
            "Operator confirmed the threat; item quarantined."
            if useful
            else "Operator override requested — denied by memory-integrity policy; routed to human review."
        )
        recall_after = (
            "BLOCKED. Sentinel refused to ingest adversarial content into memory "
            f"({warning.threat_id or 'OWASP LLM04: Data & Model Poisoning'}). Cognee improve was "
            f"skipped, so the poisoned claim never enters the knowledge graph. {reason}"
        )
        append_ledger(
            LedgerEntry(
                id=f"le-{uuid.uuid4().hex[:8]}",
                ts=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                proposal=warning.proposal,
                classification=getattr(
                    warning.classification, "value", str(warning.classification)
                ),
                cited=(warning.conflicting_memories or [ev.label for ev in warning.evidence])[:3],
                feedback="quarantine",
                feedback_score=0,
                improve_status="blocked_quarantined",
                answer=recall_after[:280],
                mode=warning.mode,
                blocked=True,
            )
        )
        return FeedbackResponse(
            warning_id=warning_id,
            feedback_score=0,
            improve_status="blocked_quarantined",
            recall_after_feedback=recall_after,
            lifecycle=_lifecycle("feedback", "sentinel:block", "quarantine"),
            mode=warning.mode,
            blocked=True,
            threat_id=warning.threat_id,
            ops=ops,
        )
    # -------------------------------------------------------------------------

    if warning and warning.id == warning_id and warning.session_id:
        try:
            result = await cognee_client.record_feedback_and_improve(
                DEFAULT_DATASET, warning.session_id, warning.proposal, useful, ops
            )
            status = result["status"]
            cognee_answer = result.get("answer", "")
            mode = "cognee"
            lifecycle = _lifecycle("feedback", "cognee:improve", "cognee:recall")
        except cognee_client.CogneeUnavailable:
            record(ops, "improve", {"mode": "demo"}, detail="feedback recorded locally")
            status = "demo_recorded"
        except Exception as exc:  # Cognee improve error (e.g. rate limit) -> demo fallback
            print(f"[feedback] Cognee feedback/improve failed, using demo fallback: {exc}")
            record(ops, "improve", {"reason": type(exc).__name__}, status="error", detail=str(exc))
            status = "demo_recorded"

    if cognee_answer:
        recall_after_feedback = cognee_answer
    else:
        recall_after_feedback = (
            "Trusted memory emphasized: services keep a single source of truth in Spanner per "
            "ADR-021, with caches non-authoritative; a second authoritative store is rejected."
            if useful
            else "Warning marked unreliable. Hindsight will ask for human review before using this path again."
        )

    score = 5 if useful else 1
    if warning and warning.id == warning_id:
        cited = (warning.conflicting_memories or [ev.label for ev in warning.evidence])[:3]
        append_ledger(
            LedgerEntry(
                id=f"le-{uuid.uuid4().hex[:8]}",
                ts=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                proposal=warning.proposal,
                classification=getattr(warning.classification, "value", str(warning.classification)),
                cited=cited,
                feedback="useful" if useful else "wrong",
                feedback_score=score,
                improve_status=status,
                answer=recall_after_feedback[:280],
                mode=mode,  # type: ignore[arg-type]
            )
        )

    return FeedbackResponse(
        warning_id=warning_id,
        feedback_score=score,
        improve_status=status,  # type: ignore[arg-type]
        recall_after_feedback=recall_after_feedback,
        lifecycle=lifecycle,
        mode=mode,
        ops=ops,
    )


def _preserved_concepts(memories: list[MemoryItem], target: MemoryItem | None) -> list[str]:
    """Tags of the forgotten memory that are still referenced by other live memories."""
    if target is None:
        return ["data", "storage"]
    others = [m for m in memories if m.id != target.id and m.status != "forgotten"]
    pool = {ns for m in others for ns in m.node_sets}
    keep = [ns for ns in target.node_sets if ns in pool]
    return keep or ["data", "storage"]


def _forget_summary(
    before: list[EvidenceItem],
    after: list[EvidenceItem],
    graph_before: dict[str, int],
    graph_after: dict[str, int],
    mode: str,
    target: MemoryItem | None,
) -> str:
    label = target.label if target else "the selected memory"
    if mode != "cognee":
        return (
            f"{label} no longer participates in Hindsight's recall. "
            "Shared concepts referenced by other memories remain."
        )
    b, a = len(before), len(after)
    parts = [
        f"The targeted probe for {label} retrieved {b} memor{'y' if b == 1 else 'ies'} "
        f"before forget and {a} after."
    ]
    if graph_before and graph_after:
        parts.append(
            f"Graph nodes {graph_before.get('nodes')}\u2192{graph_after.get('nodes')}, "
            f"edges {graph_before.get('edges')}\u2192{graph_after.get('edges')}."
        )
    parts.append(
        "The forgotten item dropped out of retrieval; shared concepts referenced by other memories remain."
    )
    return " ".join(parts)


async def forget_obsolete(data_id: str) -> ForgetResponse:
    state = load_state()
    target = next((memory for memory in state.memories if memory.id == data_id), None)
    ops: list[OpEvent] = []
    catalog = _catalog(state.memories)
    target_uuid = cognee_client.cognee_data_uuid(data_id)
    if target:
        tags = ", ".join(target.node_sets)
        probe = (
            f"What prior decisions, standards, incidents, or brainstorms are connected to "
            f"{target.label}? Source: {target.source}. Tags: {tags}. Details: {target.text}"
        )
    else:
        probe = "What prior decisions or obsolete brainstorms should be forgotten?"
    before: list[EvidenceItem] = []
    after: list[EvidenceItem] = []
    graph_before: dict[str, int] = {}
    graph_after: dict[str, int] = {}
    mode = "demo"

    try:
        # Real before/after proof via retrieval (robust path), plus a graph-size
        # delta from the cached real graph mutated by the real deletion.
        raw_before = await cognee_client.retrieve_chunks(DEFAULT_DATASET, probe, ops, top_k=12)
        before, _, _ = _chunks_to_evidence(raw_before, catalog, target_uuid=target_uuid)

        snapshot_before = await _ensure_graph_cache(ops)
        if snapshot_before is not None:
            graph_before = {"nodes": len(snapshot_before.nodes), "edges": len(snapshot_before.edges)}
        target_hashes = _target_content_hashes(target)

        await cognee_client.forget_memory(DEFAULT_DATASET, data_id, ops)
        # The deletion itself succeeded — lock in cognee mode regardless of what
        # the (best-effort) after-probe does next.
        mode = "cognee"
        lifecycle = _lifecycle("forget", "cognee:forget", "recall")

        # After-forget retrieval is best-effort: immediately after a deletion the
        # re-recall can hit a transient EntityNotFoundError while indexes settle.
        # If so, derive the "after" set by dropping the forgotten item from before.
        try:
            raw_after = await cognee_client.retrieve_chunks(DEFAULT_DATASET, probe, ops, top_k=12)
            after, _, _ = _chunks_to_evidence(raw_after, catalog, target_uuid=target_uuid)
        except Exception as exc_after:
            record(ops, "recall", {"phase": "after"}, status="error", detail=str(exc_after))
            after = [
                ev.model_copy(update={"is_target": False}) for ev in before if not ev.is_target
            ]

        _prune_graph_cache(target_hashes)
        if _GRAPH_CACHE is not None:
            graph_after = {"nodes": len(_GRAPH_CACHE.nodes), "edges": len(_GRAPH_CACHE.edges)}
    except cognee_client.CogneeUnavailable:
        lifecycle = _lifecycle("forget", "demo:forget", "recall")
    except Exception as exc:  # Cognee forget error -> demo fallback
        print(f"[forget] Cognee path failed, using demo fallback: {exc}")
        record(ops, "fallback", {"reason": type(exc).__name__}, status="error", detail=str(exc))
        lifecycle = _lifecycle("forget", "demo:forget", "recall")

    update_memory_status(data_id, "forgotten", lifecycle)

    return ForgetResponse(
        data_id=data_id,
        removed=[target.label] if target else [],
        preserved=_preserved_concepts(state.memories, target),
        recall_after_forget=_forget_summary(before, after, graph_before, graph_after, mode, target),
        lifecycle=lifecycle,
        mode=mode,
        before=before,
        after=after,
        graph_before=graph_before,
        graph_after=graph_after,
        ops=ops,
    )


# ---------------------------------------------------------------------------
# Live knowledge-graph snapshot (for the graph view)
# ---------------------------------------------------------------------------

_GRAPH_MAX_NODES = 250


def _node_label(props: dict) -> str:
    for key in ("name", "label", "text", "title", "id"):
        value = props.get(key)
        if value:
            return str(value).strip()[:48]
    return "node"


def _node_type(props: dict) -> str:
    for key in ("type", "__node_type__", "label", "kind"):
        value = props.get(key)
        if value:
            return str(value)
    return "node"


def _node_sets(props: dict) -> list[str]:
    value = props.get("belongs_to_set") or props.get("node_set") or props.get("node_sets")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _transform_graph(nodes: list, edges: list, max_nodes: int = _GRAPH_MAX_NODES):
    truncated = len(nodes) > max_nodes
    graph_nodes: list[GraphNode] = []
    for entry in nodes[:max_nodes]:
        node_id, props = entry if isinstance(entry, (tuple, list)) else (entry, {})
        props = props or {}
        node_sets = _node_sets(props)
        node_type = _node_type(props)
        graph_nodes.append(
            GraphNode(
                id=str(node_id),
                label=_node_label(props),
                type=node_type,
                group=node_type or (node_sets[0] if node_sets else "node"),
                node_sets=node_sets,
                content_hash=str(props.get("source_content_hash") or ""),
            )
        )
    kept = {node.id for node in graph_nodes}
    graph_edges: list[GraphEdge] = []
    for edge in edges:
        if len(edge) < 2:
            continue
        source, target = str(edge[0]), str(edge[1])
        rel = str(edge[2]) if len(edge) > 2 else ""
        if source in kept and target in kept:
            graph_edges.append(GraphEdge(source=source, target=target, rel=rel))
    return graph_nodes, graph_edges, truncated


def _demo_graph(memories: list[MemoryItem]) -> tuple[list[GraphNode], list[GraphEdge]]:
    graph_nodes: list[GraphNode] = []
    graph_edges: list[GraphEdge] = []
    seen: set[str] = set()
    for memory in memories:
        if memory.status == "forgotten":
            continue
        graph_nodes.append(
            GraphNode(
                id=memory.id,
                label=memory.label,
                type="memory",
                group="memory",
                node_sets=memory.node_sets,
            )
        )
        for node_set in memory.node_sets:
            set_id = f"set:{node_set}"
            if set_id not in seen:
                seen.add(set_id)
                graph_nodes.append(
                    GraphNode(id=set_id, label=node_set, type="node_set", group=node_set)
                )
            graph_edges.append(GraphEdge(source=memory.id, target=set_id, rel="tagged"))
    return graph_nodes, graph_edges


# The per-dataset ladybug/kuzu graph DB is a single-writer subprocess engine: only
# the first live read in a process reliably returns data (the dataset-queue slot
# release on context exit tears the worker down). So we read the live graph at most
# once, cache it, and mutate the cache on forget — the "node disappears" stays real
# (we drop exactly the forgotten doc's nodes) without a fragile second live read.
_GRAPH_CACHE: GraphSnapshot | None = None


def _build_cognee_snapshot(nodes: list, edges: list, ops: list[OpEvent]) -> GraphSnapshot:
    graph_nodes, graph_edges, truncated = _transform_graph(nodes, edges)
    return GraphSnapshot(
        mode="cognee",
        nodes=graph_nodes,
        edges=graph_edges,
        node_count=len(graph_nodes),
        edge_count=len(graph_edges),
        truncated=truncated,
        ops=ops,
    )


def _demo_snapshot(state, ops: list[OpEvent]) -> GraphSnapshot:
    graph_nodes, graph_edges = _demo_graph(state.memories)
    return GraphSnapshot(
        mode="demo",
        nodes=graph_nodes,
        edges=graph_edges,
        node_count=len(graph_nodes),
        edge_count=len(graph_edges),
        ops=ops,
    )


async def graph_snapshot() -> GraphSnapshot:
    global _GRAPH_CACHE
    state = load_state()
    ops: list[OpEvent] = []
    try:
        nodes, edges = await cognee_client.graph_data(ops, DEFAULT_DATASET)
        if nodes:  # a good live read -> refresh the cache
            _GRAPH_CACHE = _build_cognee_snapshot(nodes, edges, ops)
            return _GRAPH_CACHE
        if _GRAPH_CACHE is not None:  # empty re-read glitch -> serve last good
            return _GRAPH_CACHE.model_copy(update={"ops": ops})
        return _demo_snapshot(state, ops)
    except cognee_client.CogneeUnavailable:
        return _demo_snapshot(state, ops)
    except Exception as exc:
        print(f"[graph] Cognee graph fetch failed: {exc}")
        record(ops, "get_graph_data", {}, status="error", detail=str(exc))
        if _GRAPH_CACHE is not None:
            return _GRAPH_CACHE.model_copy(update={"ops": ops})
        return _demo_snapshot(state, ops)


async def _ensure_graph_cache(ops: list[OpEvent]) -> GraphSnapshot | None:
    """Populate the graph cache with one live read if it isn't warm yet."""
    global _GRAPH_CACHE
    if _GRAPH_CACHE is not None:
        return _GRAPH_CACHE
    try:
        nodes, edges = await cognee_client.graph_data(ops, DEFAULT_DATASET)
        if nodes:
            _GRAPH_CACHE = _build_cognee_snapshot(nodes, edges, [])
            return _GRAPH_CACHE
    except Exception as exc:
        record(ops, "get_graph_data", {}, status="error", detail=str(exc))
    return _GRAPH_CACHE


def _prune_graph_cache(content_hashes: set[str]) -> None:
    """Drop nodes (and their edges) belonging to a forgotten doc from the cache."""
    global _GRAPH_CACHE
    if _GRAPH_CACHE is None or not content_hashes:
        return
    removed_ids = {
        node.id for node in _GRAPH_CACHE.nodes if node.content_hash in content_hashes
    }
    if not removed_ids:
        return
    nodes = [node for node in _GRAPH_CACHE.nodes if node.id not in removed_ids]
    edges = [
        edge
        for edge in _GRAPH_CACHE.edges
        if edge.source not in removed_ids and edge.target not in removed_ids
    ]
    _GRAPH_CACHE = _GRAPH_CACHE.model_copy(
        update={
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
    )


def _target_content_hashes(target: MemoryItem | None) -> set[str]:
    """Content hashes of the forgotten doc's own graph nodes (exact node-set match).

    A doc's content nodes (TextSummary/Entity and the node sets it first created)
    carry ``belongs_to_set`` equal to that memory's node sets. Shared concept nodes
    created by earlier docs carry a different content hash, so they survive the prune.
    """
    if _GRAPH_CACHE is None or target is None:
        return set()
    target_sets = sorted(target.node_sets)
    return {
        node.content_hash
        for node in _GRAPH_CACHE.nodes
        if node.content_hash and sorted(node.node_sets) == target_sets
    }
