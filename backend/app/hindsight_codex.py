from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.codex_integration import CodexSessionCheckRequest, check_codex_session
from app.service import activate_demo_mode


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _codex_command(args: list[str]) -> list[str]:
    executable = shutil.which("codex") or shutil.which("codex.cmd") or shutil.which("codex.ps1")
    if executable is None:
        raise SystemExit("codex CLI was not found on PATH")
    if executable.lower().endswith(".ps1"):
        return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", executable, *args]
    return [executable, *args]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Codex, then automatically check its output with Hindsight.")
    parser.add_argument("message", nargs="*", help="User message to send to Codex")
    parser.add_argument("--session-id", default="hindsight-codex-sidecar")
    parser.add_argument("--live-cognee", action="store_true", help="Use live Cognee instead of deterministic demo mode")
    parser.add_argument("--notify-telegram", action="store_true", help="Send Telegram alert when Hindsight blocks/warns")
    parser.add_argument("--telegram-chat-id", help="Telegram chat id for alert override")
    parser.add_argument("--output-last-message", default="backend/codex_live_last_message.txt")
    parser.add_argument("--sandbox", default="read-only", choices=["read-only", "workspace-write", "danger-full-access"])
    args = parser.parse_args()

    load_dotenv(".env", override=True)
    message = " ".join(args.message).strip()
    if not message and not sys.stdin.isatty():
        message = sys.stdin.read().strip()
    if not message:
        raise SystemExit("Provide a Codex message as arguments or stdin.")

    repo = _repo_root()
    output_path = (repo / args.output_last_message).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    codex_args = [
        "exec",
        "--color",
        "always",
        "-s",
        args.sandbox,
        "-C",
        str(repo),
        "--output-last-message",
        str(output_path),
        message,
    ]
    cmd = _codex_command(codex_args)

    print("user")
    print(message)
    print()
    print("$ codex " + " ".join(codex_args))
    completed = subprocess.run(cmd, cwd=repo)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    if not output_path.exists():
        raise SystemExit(f"Codex did not write final message to {output_path}")

    if not args.live_cognee:
        activate_demo_mode()

    response = asyncio.run(
        check_codex_session(
            CodexSessionCheckRequest(
                transcript=output_path.read_text(encoding="utf-8"),
                session_id=args.session_id,
                actor="codex-agent",
                event_type="agent_memory_write",
                source_label="hindsight-codex-sidecar",
                notify_telegram=args.notify_telegram,
                telegram_chat_id=args.telegram_chat_id,
            )
        )
    )

    record = response.ingest.record
    print()
    print("hindsight")
    print(f"Outcome: {record.outcome}")
    print(f"Classification: {record.classification or 'none'}")
    print(f"Recommended control: {record.recommended_control or 'none'}")
    print(f"Can remember: {'yes' if response.can_remember else 'no'}")
    if record.primary_evidence_labels:
        print("Primary evidence:")
        for label in record.primary_evidence_labels:
            print(f"- {label}")
    if response.notification is not None:
        print(f"Telegram notification: {'posted' if response.notification.posted else response.notification.error}")


if __name__ == "__main__":
    main()