from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.workstream import WorkstreamEvent, WorkstreamIngestResponse, ingest_workstream_event


class SlackPostResult(BaseModel):
    attempted: bool = False
    posted: bool = False
    channel: str = ""
    thread_ts: str | None = None
    ts: str | None = None
    error: str = ""


class SlackProcessResponse(BaseModel):
    accepted: bool
    reason: str = ""
    event_id: str = ""
    event_type: str = ""
    channel: str = ""
    thread_ts: str | None = None
    reply_text: str = ""
    post: SlackPostResult = Field(default_factory=SlackPostResult)
    ingest: WorkstreamIngestResponse | None = None


class SlackEventAck(BaseModel):
    ok: bool = True
    accepted: bool = True
    reason: str = ""
    signature_verified: bool = False
    retry_ignored: bool = False


class SlackLocalTestRequest(BaseModel):
    payload: dict[str, Any]
    post_message: bool = False


class SlackSignatureError(RuntimeError):
    pass


_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")


def verify_slack_signature(headers: Mapping[str, str], body: bytes) -> bool:
    secret = os.getenv("SLACK_SIGNING_SECRET", "").strip()
    if not secret:
        if os.getenv("HINDSIGHT_SLACK_ALLOW_UNSIGNED", "").lower() in {"1", "true", "yes"}:
            return False
        raise SlackSignatureError("SLACK_SIGNING_SECRET is not configured")

    timestamp = headers.get("x-slack-request-timestamp") or headers.get("X-Slack-Request-Timestamp")
    signature = headers.get("x-slack-signature") or headers.get("X-Slack-Signature")
    if not timestamp or not signature:
        raise SlackSignatureError("missing Slack signature headers")

    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise SlackSignatureError("invalid Slack timestamp") from exc

    if abs(time.time() - timestamp_int) > 60 * 5:
        raise SlackSignatureError("stale Slack request timestamp")

    basestring = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    if not hmac.compare_digest(expected, signature):
        raise SlackSignatureError("invalid Slack request signature")
    return True


def parse_slack_payload(body: bytes) -> dict[str, Any]:
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Slack request body is not valid JSON") from exc


def _clean_text(text: str) -> str:
    text = _MENTION_RE.sub("@Hindsight", text or "")
    return " ".join(text.split()).strip()


def _event_id(payload: dict[str, Any], event: dict[str, Any]) -> str:
    if payload.get("event_id"):
        return f"slack-{payload['event_id']}"
    team = payload.get("team_id") or "team"
    channel = event.get("channel") or "channel"
    ts = event.get("event_ts") or event.get("ts") or "event"
    return f"slack-{team}-{channel}-{ts}"


def _event_to_workstream(payload: dict[str, Any], event: dict[str, Any]) -> WorkstreamEvent:
    text = _clean_text(str(event.get("text") or ""))
    event_type = str(event.get("type") or "message")
    actor = str(event.get("user") or event.get("username") or event.get("bot_id") or "unknown")
    channel = str(event.get("channel") or "")
    ts = str(event.get("ts") or event.get("event_ts") or "")
    thread_ts = str(event.get("thread_ts") or ts or "")
    return WorkstreamEvent(
        source="slack",
        event_type=event_type,
        actor=actor,
        content=text,
        metadata={
            "team_id": payload.get("team_id"),
            "api_app_id": payload.get("api_app_id"),
            "channel": channel,
            "channel_type": event.get("channel_type"),
            "ts": ts,
            "thread_ts": thread_ts,
            "event_id": payload.get("event_id"),
            "event_time": payload.get("event_time"),
        },
        event_id=_event_id(payload, event),
    )


def _format_reply(response: WorkstreamIngestResponse) -> str:
    record = response.record
    warning = response.warning
    if warning is None:
        return (
            "Hindsight OS checked this request and did not find a memory-changing signal. "
            f"Outcome: `{record.outcome}`."
        )

    primary = record.primary_evidence_labels or record.evidence_labels[:3]
    evidence = "\n".join(f"• {label}" for label in primary) or "• none"
    control = record.recommended_control or "ask_human"
    classification = record.classification or "unknown"
    threat = ""
    if warning.is_poisoning:
        threat = f"\nThreat: `{warning.manipulation_tactic}` ({warning.threat_id or 'memory poisoning risk'})"

    return (
        f"*Hindsight OS: {classification}*\n"
        f"Recommended control: `{control}`{threat}\n"
        f"> {warning.summary}\n\n"
        f"*Primary evidence*\n{evidence}"
    )[:3900]


def _post_message(channel: str, text: str, thread_ts: str | None) -> SlackPostResult:
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    result = SlackPostResult(attempted=bool(token), channel=channel, thread_ts=thread_ts)
    if not token:
        result.error = "SLACK_BOT_TOKEN is not configured"
        return result

    payload: dict[str, Any] = {
        "channel": channel,
        "text": text,
        "unfurl_links": False,
        "unfurl_media": False,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    request = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
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
        result.ts = str(body.get("ts") or "")
    else:
        result.error = str(body.get("error") or "unknown Slack API error")
    return result


async def process_slack_event_payload(
    payload: dict[str, Any], *, post_message: bool = True
) -> SlackProcessResponse:
    if payload.get("type") == "url_verification":
        return SlackProcessResponse(accepted=True, reason="url_verification", event_type="url_verification")

    if payload.get("type") != "event_callback":
        return SlackProcessResponse(accepted=False, reason="unsupported Slack payload type")

    event = payload.get("event") or {}
    event_type = str(event.get("type") or "")
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return SlackProcessResponse(accepted=False, reason="bot message ignored", event_type=event_type)
    if event_type not in {"app_mention", "message"}:
        return SlackProcessResponse(accepted=False, reason="unsupported Slack event type", event_type=event_type)

    channel = str(event.get("channel") or "")
    ts = str(event.get("ts") or event.get("event_ts") or "")
    thread_ts = str(event.get("thread_ts") or ts or "")
    workstream_event = _event_to_workstream(payload, event)
    response = await ingest_workstream_event(workstream_event)

    should_reply = event_type == "app_mention" or response.record.outcome != "ignored_low_risk"
    reply_text = _format_reply(response) if should_reply else ""
    post_result = SlackPostResult(channel=channel, thread_ts=thread_ts)
    if should_reply and post_message:
        post_result = _post_message(channel, reply_text, thread_ts)

    return SlackProcessResponse(
        accepted=True,
        reason="processed",
        event_id=workstream_event.event_id or "",
        event_type=event_type,
        channel=channel,
        thread_ts=thread_ts or None,
        reply_text=reply_text,
        post=post_result,
        ingest=response,
    )