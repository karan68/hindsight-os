from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.codex_integration import CodexSessionCheckRequest, check_codex_session


def _read_text(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("Provide --file or pipe a transcript on stdin.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a Codex/agent transcript to Hindsight.")
    parser.add_argument("--file", help="Transcript file to inspect")
    parser.add_argument("--session-id", default="manual-codex-session")
    parser.add_argument("--actor", default="codex-agent")
    parser.add_argument("--source-label", default="manual-transcript")
    parser.add_argument("--event-type", default="transcript", choices=["agent_message", "agent_memory_write", "transcript"])
    parser.add_argument("--notify-telegram", action="store_true", help="Send a Telegram alert when Hindsight blocks/warns")
    parser.add_argument("--telegram-chat-id", help="Telegram chat id for alert override")
    parser.add_argument("--json", action="store_true", help="Print full JSON response")
    args = parser.parse_args()

    load_dotenv(".env", override=True)
    transcript = _read_text(args.file)
    response = asyncio.run(
        check_codex_session(
            CodexSessionCheckRequest(
                transcript=transcript,
                session_id=args.session_id,
                actor=args.actor,
                source_label=args.source_label,
                event_type=args.event_type,
                notify_telegram=args.notify_telegram,
                telegram_chat_id=args.telegram_chat_id,
            )
        )
    )
    if args.json:
        print(response.model_dump_json(indent=2))
        return

    record = response.ingest.record
    print(json.dumps({
        "session_id": response.session_id,
        "event_id": response.event_id,
        "outcome": record.outcome,
        "classification": record.classification,
        "recommended_control": record.recommended_control,
        "primary_evidence": record.primary_evidence_labels,
        "can_remember": response.can_remember,
        "blocked": response.blocked,
        "notification": response.notification.model_dump() if response.notification else None,
    }, indent=2))


if __name__ == "__main__":
    main()