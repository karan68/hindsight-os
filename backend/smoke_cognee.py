r"""Standalone validation that Cognee works with Groq (LLM) + Ollama (embeddings).
Run from the backend/ folder:  .\.venv\Scripts\python.exe smoke_cognee.py
"""

from __future__ import annotations

import asyncio
import os
import time

from dotenv import load_dotenv

# override=True so our .env wins over any pre-existing shell env vars (e.g. a
# global Ollama LLM_MODEL) that would otherwise leak into Cognee's config.
load_dotenv(override=True)

import cognee  # noqa: E402

DATASET = "hindsight_smoke"


async def main() -> None:
    print("LLM:", os.getenv("LLM_PROVIDER"), os.getenv("LLM_MODEL"))
    print("EMBED:", os.getenv("EMBEDDING_PROVIDER"), os.getenv("EMBEDDING_MODEL"))

    t0 = time.time()
    try:
        await cognee.forget(dataset=DATASET)
    except Exception:
        pass
    print(f"[reset]    {time.time() - t0:5.1f}s")

    t1 = time.time()
    await cognee.remember(
        "ADR-007: Billing invoices stay in Postgres because invoices need relational "
        "transactions and audit reconstruction across payments, refunds, and taxes. "
        "DynamoDB was evaluated and rejected for primary invoice storage.",
        dataset_name=DATASET,
        self_improvement=False,
    )
    print(f"[remember] {time.time() - t1:5.1f}s")

    t2 = time.time()
    res = await cognee.recall(
        query_text="What storage should billing invoices use and why?",
        datasets=[DATASET],
    )
    print(f"[recall]   {time.time() - t2:5.1f}s")

    items = res if isinstance(res, list) else [res]
    for r in items[:3]:
        text = getattr(r, "text", r)
        source = getattr(r, "source", "?")
        print(f"  [{source}] {str(text)[:400]}")

    print(f"[total]    {time.time() - t0:5.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
