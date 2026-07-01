from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from pydantic import BaseModel, Field

from app.workstream import WorkstreamEvent, WorkstreamIngestResponse, ingest_workstream_event


class TelegramPostResult(BaseModel):
    attempted: bool = False
    posted: bool = False
    chat_id: str = ""
    message_id: int | None = None
    error: str = ""


class TelegramProcessResponse(BaseModel):
    accepted: bool
    reason: str = ""
    update_id: int | None = None
    chat_id: str = ""
    reply_text: str = ""
    post: TelegramPostResult = Field(default_factory=TelegramPostResult)
    ingest: WorkstreamIngestResponse | None = None


class TelegramLocalTestRequest(BaseModel):
    update: dict[str, Any]
    post_message: bool = False


_BOT_MENTION = re.compile(r"@[A-Za-z0-9_]+")


def _bot_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _clean_text(text: str) -> str:
    text = text or ""
    text = _BOT_MENTION.sub(
        lambda match: "@Hindsight" if "hindsight" in match.group(0).lower() else match.group(0),
        text,
    )
    return " ".join(text.split()).strip()


def _message_from_update(update: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
        value = update.get(key)
        if isinstance(value, dict):
            return value
    return None


def _actor(message: dict[str, Any]) -> str:
    sender = message.get("from") or message.get("sender_chat") or {}
    username = sender.get("username")
    if username:
        return f"@{username}"
    first = sender.get("first_name") or sender.get("title")
    user_id = sender.get("id")
    if first and user_id:
        return f"{first} ({user_id})"
    return str(user_id or "unknown")


def _event_to_workstream(update: dict[str, Any], message: dict[str, Any]) -> WorkstreamEvent:
    chat = message.get("chat") or {}
    text = _clean_text(str(message.get("text") or message.get("caption") or ""))
    chat_id = str(chat.get("id") or "")
    message_id = str(message.get("message_id") or "")
    update_id = str(update.get("update_id") or "")
    return WorkstreamEvent(
        source="telegram",
        event_type="message",
        actor=_actor(message),
        content=text,
        metadata={
            "update_id": update.get("update_id"),
            "message_id": message.get("message_id"),
            "chat_id": chat_id,
            "chat_type": chat.get("type"),
            "chat_title": chat.get("title"),
        },
        event_id=f"telegram-{update_id or chat_id + '-' + message_id}",
    )


def _format_reply(response: WorkstreamIngestResponse) -> str:
    record = response.record
    warning = response.warning
    if warning is None:
        return (
            "Hindsight OS checked this message and did not find a memory-changing signal. "
            f"Outcome: {record.outcome}."
        )

    primary = record.primary_evidence_labels or record.evidence_labels[:3]
    evidence = "\n".join(f"- {label}" for label in primary) or "- none"
    control = record.recommended_control or "ask_human"
    classification = record.classification or "unknown"
    threat = ""
    if warning.is_poisoning:
        threat = f"\nThreat: {warning.manipulation_tactic} ({warning.threat_id or 'memory poisoning risk'})"

    return (
        f"Hindsight OS: {classification}\n"
        f"Recommended control: {control}{threat}\n"
        f"\n{warning.summary}\n\n"
        f"Primary evidence:\n{evidence}"
    )[:3900]


def send_telegram_message(chat_id: str, text: str, reply_to_message_id: int | None = None) -> TelegramPostResult:
    token = _bot_token()
    result = TelegramPostResult(attempted=bool(token), chat_id=chat_id)
    if not token:
        result.error = "TELEGRAM_BOT_TOKEN is not configured"
        return result

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
        payload["allow_sending_without_reply"] = True

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        result.error = str(exc)
        return result

    if body.get("ok"):
        result.posted = True
        result.message_id = (body.get("result") or {}).get("message_id")
    else:
        result.error = str(body.get("description") or body.get("error_code") or "unknown Telegram API error")
    return result


def get_telegram_updates(offset: int | None, *, timeout: int = 25) -> list[dict[str, Any]]:
    token = _bot_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    params = {
        "timeout": str(timeout),
        "allowed_updates": json.dumps(["message", "edited_message", "channel_post"]),
    }
    if offset is not None:
        params["offset"] = str(offset)
    url = f"https://api.telegram.org/bot{token}/getUpdates?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout + 10) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(str(body.get("description") or body))
    return list(body.get("result") or [])


async def process_telegram_update(update: dict[str, Any], *, post_message: bool = True) -> TelegramProcessResponse:
    message = _message_from_update(update)
    if message is None:
        return TelegramProcessResponse(accepted=False, reason="unsupported Telegram update", update_id=update.get("update_id"))

    text = str(message.get("text") or message.get("caption") or "")
    if not text.strip():
        return TelegramProcessResponse(accepted=False, reason="Telegram message has no text", update_id=update.get("update_id"))

    event = _event_to_workstream(update, message)
    response = await ingest_workstream_event(event)
    lowered = text.lower()
    should_reply = response.record.outcome != "ignored_low_risk" or "/hindsight" in lowered or "@hindsight" in lowered
    reply_text = _format_reply(response) if should_reply else ""

    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    message_id = message.get("message_id")
    post = TelegramPostResult(chat_id=chat_id)
    if should_reply and post_message:
        post = send_telegram_message(chat_id, reply_text, message_id if isinstance(message_id, int) else None)

    return TelegramProcessResponse(
        accepted=True,
        reason="processed",
        update_id=update.get("update_id"),
        chat_id=chat_id,
        reply_text=reply_text,
        post=post,
        ingest=response,
    )