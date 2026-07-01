"""Operation tracing — the demo's "receipts".

Every real Cognee SDK call is wrapped in :func:`timed`, which measures wall-clock
duration, captures a short human summary plus a truncated raw payload, and appends
a structured :class:`~app.models.OpEvent`. The frontend renders these as a live
ops console so a viewer can see the actual machinery (recall, classify, improve,
forget) executing with real latencies — not canned prose.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar

from app.models import OpEvent

T = TypeVar("T")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def truncate(text: str, limit: int = 1400) -> str:
    return text if len(text) <= limit else f"{text[:limit]}\u2026 (+{len(text) - limit} chars)"


def record(
    ops: list[OpEvent],
    op: str,
    params: dict[str, Any] | None = None,
    *,
    status: str = "ok",
    duration_ms: int = 0,
    detail: str = "",
    raw: str | None = None,
) -> OpEvent:
    """Append a pre-computed event (for non-awaitable / synthesized steps)."""
    event = OpEvent(
        op=op,
        params=params or {},
        status=status,  # type: ignore[arg-type]
        duration_ms=duration_ms,
        detail=detail,
        raw=raw,
        ts=_now(),
    )
    ops.append(event)
    return event


async def timed(
    ops: list[OpEvent],
    op: str,
    params: dict[str, Any] | None,
    coro: Awaitable[T],
    *,
    summarize: Callable[[T], str] | None = None,
    raw: Callable[[T], str] | None = None,
) -> T:
    """Await *coro*, timing it and appending an :class:`OpEvent` to *ops*.

    On success records ``status="ok"`` with an optional ``summarize`` detail and
    ``raw`` payload. On failure records ``status="error"`` with the exception text
    and re-raises so callers can fall back.
    """
    start = time.perf_counter()
    try:
        result = await coro
    except Exception as exc:
        record(
            ops,
            op,
            params,
            status="error",
            duration_ms=int((time.perf_counter() - start) * 1000),
            detail=f"{type(exc).__name__}: {exc}",
        )
        raise

    duration_ms = int((time.perf_counter() - start) * 1000)
    detail = ""
    raw_str: str | None = None
    if summarize is not None:
        try:
            detail = summarize(result)
        except Exception:  # summary is cosmetic — never fail the request over it
            detail = ""
    if raw is not None:
        try:
            raw_str = truncate(raw(result))
        except Exception:
            raw_str = None

    record(ops, op, params, status="ok", duration_ms=duration_ms, detail=detail, raw=raw_str)
    return result
