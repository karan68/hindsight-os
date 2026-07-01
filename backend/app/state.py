from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from app.models import DemoState, LedgerEntry, MemoryItem, WarningCard


DEFAULT_DATASET = os.getenv("HINDSIGHT_DATASET", "hindsight_decisions")
_DEFAULT_STATE_FILE = Path(__file__).resolve().parent.parent / "app_state.json"
STATE_FILE = Path(os.getenv("HINDSIGHT_STATE_FILE", str(_DEFAULT_STATE_FILE)))


def _host(url: str) -> str:
    """Return just the host of an endpoint URL (never the key/path)."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]
    except Exception:
        return ""


def _cognee_version() -> str:
    try:
        from importlib.metadata import version

        return version("cognee")
    except Exception:
        return ""


def _runtime_info(state: DemoState) -> DemoState:
    """Annotate state with the live LLM/embedding telemetry for UI badges."""
    state.llm_model = os.getenv("LLM_MODEL", "")
    state.llm_provider = os.getenv("LLM_PROVIDER", "")
    state.llm_endpoint = _host(os.getenv("LLM_ENDPOINT", "") or os.getenv("AZURE_API_BASE", ""))
    state.embedding_model = os.getenv("EMBEDDING_MODEL", "")
    state.embedding_provider = os.getenv("EMBEDDING_PROVIDER", "")
    state.embedding_dims = os.getenv("EMBEDDING_DIMENSIONS", "")
    state.structured_framework = os.getenv("STRUCTURED_OUTPUT_FRAMEWORK", "") or "litellm_instructor"
    state.cognee_version = _cognee_version()
    return state


def _empty_state() -> DemoState:
    return _runtime_info(
        DemoState(dataset=DEFAULT_DATASET, mode="demo", seeded=False, memories=[])
    )


def _backfill_sources(state: DemoState) -> DemoState:
    """Fill memory provenance for state persisted before the source field existed."""
    from app.seed_data import SEED_SOURCE_BY_ID

    for memory in state.memories:
        if not memory.source:
            memory.source = SEED_SOURCE_BY_ID.get(memory.id, "")
    return state


def load_state() -> DemoState:
    if not STATE_FILE.exists():
        return _empty_state()
    return _backfill_sources(
        _runtime_info(DemoState.model_validate_json(STATE_FILE.read_text(encoding="utf-8")))
    )


def save_state(state: DemoState) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def replace_memories(memories: list[MemoryItem], mode: str, lifecycle: list[str]) -> DemoState:
    state = DemoState(
        dataset=DEFAULT_DATASET,
        mode="cognee" if mode == "cognee" else "demo",
        seeded=True,
        memories=memories,
        lifecycle=lifecycle,
    )
    save_state(state)
    return state


def update_latest_warning(warning: WarningCard, lifecycle: list[str]) -> DemoState:
    state = load_state()
    state.latest_warning = warning
    state.lifecycle = lifecycle
    if warning.mode == "cognee":
        state.mode = "cognee"
    save_state(state)
    return state


def update_memory_status(data_id: str, status: str, lifecycle: list[str]) -> DemoState:
    state = load_state()
    for memory in state.memories:
        if memory.id == data_id:
            memory.status = status  # type: ignore[assignment]
    state.lifecycle = lifecycle
    save_state(state)
    return state


def append_ledger(entry: LedgerEntry) -> DemoState:
    """Append a feedback decision to the trust ledger (most-recent-first)."""
    state = load_state()
    state.ledger = [entry, *state.ledger][:25]
    save_state(state)
    return state
