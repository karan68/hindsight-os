from __future__ import annotations

import asyncio
import time

from dotenv import load_dotenv

from app.telegram_integration import get_telegram_updates, process_telegram_update


def run() -> None:
    load_dotenv(override=True)
    offset: int | None = None
    print("[telegram] polling started. Send /hindsight or a memory-risk message to the bot.")
    while True:
        try:
            updates = get_telegram_updates(offset, timeout=25)
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                result = asyncio.run(process_telegram_update(update, post_message=True))
                status = result.ingest.record.outcome if result.ingest else result.reason
                print(f"[telegram] processed update {update_id}: {status}")
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[telegram] polling error: {type(exc).__name__}: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    run()