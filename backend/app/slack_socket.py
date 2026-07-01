from __future__ import annotations

import asyncio
import os
import threading

from dotenv import load_dotenv

from app.slack_integration import process_slack_event_payload


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def _process_payload(payload: dict) -> None:
    try:
        result = asyncio.run(process_slack_event_payload(payload, post_message=True))
        status = result.ingest.record.outcome if result.ingest else result.reason
        print(f"[slack-socket] processed {result.event_id or result.event_type}: {status}")
    except Exception as exc:
        print(f"[slack-socket] processing failed: {type(exc).__name__}: {exc}")


def run() -> None:
    load_dotenv(override=True)
    app_token = _require_env("SLACK_APP_TOKEN")
    bot_token = _require_env("SLACK_BOT_TOKEN")

    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.response import SocketModeResponse
    from slack_sdk.web import WebClient

    client = SocketModeClient(app_token=app_token, web_client=WebClient(token=bot_token))

    def handle_socket_mode_request(socket_client: SocketModeClient, request) -> None:
        socket_client.send_socket_mode_response(
            SocketModeResponse(envelope_id=request.envelope_id)
        )
        if request.type != "events_api":
            print(f"[slack-socket] ignored request type {request.type}")
            return
        thread = threading.Thread(target=_process_payload, args=(request.payload,), daemon=True)
        thread.start()

    client.socket_mode_request_listeners.append(handle_socket_mode_request)
    client.connect()
    print("[slack-socket] connected. Mention the bot with @Hindsight in Slack.")
    threading.Event().wait()


if __name__ == "__main__":
    run()