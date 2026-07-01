from __future__ import annotations

import asyncio

from dotenv import load_dotenv

from app.models import ProposalRequest
from app.service import check_proposal, forget_obsolete, seed_demo, submit_feedback


async def main() -> None:
    load_dotenv(override=True)
    seed = await seed_demo()
    print(f"seeded {len(seed.items)} memories in {seed.mode} mode")

    warning = await check_proposal(
        ProposalRequest(proposal="New RFC: move billing invoices to DynamoDB for scalability.")
    )
    print(warning.classification, warning.summary)

    feedback = await submit_feedback(warning.id, useful=True)
    print(feedback.improve_status, feedback.recall_after_feedback)

    forget = await forget_obsolete("brainstorm-0319")
    print(forget.removed, forget.preserved)


if __name__ == "__main__":
    asyncio.run(main())
