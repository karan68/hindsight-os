# Hindsight OS Workstream Product Plan

This plan intentionally keeps the existing `http://localhost:5173/` UI unchanged as the backup demo. The new product direction is a memory-integrity layer for real workstreams: GitHub PRs, Telegram chats, Codex/agent sessions, and later Jira.

## Product Principle

Hindsight should not inspect every message deeply. It should protect memory-changing and decision-changing moments.

The architecture is tiered:

1. Observe event metadata and content from an integration.
2. Run a cheap local screening policy.
3. Only send candidate memory-risk events to Cognee recall and Hindsight classification.
4. Warn or quarantine in the integration surface itself.
5. Keep audit, graph, trust ledger, improve, and forget controls in the operations console.

## Phase 0: Verify Integration Surfaces

Goal: prove each real integration can send or receive one event before building product behavior.

Tests before moving on:

- GitHub: read one PR and post one test comment without leaking tokens.
- Telegram: receive one bot message and reply from local long polling.
- Codex: capture one real session message through a confirmed API, log, wrapper, or export path.

Do not claim an integration is real until its gate passes.

## Phase 1: Core Workstream Event Pipeline

Goal: one backend contract for all integrations.

Implemented first slice:

- `POST /events/ingest`
- `GET /events`
- `WorkstreamEvent` typed contract
- cheap screening policy
- deep Cognee/Hindsight check only for memory-risk events
- local event audit file ignored by git

Tests before moving on:

- Low-risk event returns `ignored_low_risk` and does not call Cognee.
- High-risk GitHub/Slack/Codex event returns a normal `WarningCard` shape.
- Existing proposal UI route still works.
- Existing frontend files remain untouched.

## Phase 2: Local Simulator

Goal: replay realistic Telegram, GitHub, and Codex payloads without external API risk.

Current local routes:

- `GET /simulator/scenarios`
- `POST /simulator/run`

The simulator replays fixed workstream payloads through the same `/events/ingest` pipeline and grades each result against an explicit expectation. It covers low-risk Telegram noise, low-signal reactions, a GitHub source-of-truth conflict, a Telegram authority-spoof claim, and a Codex memory-write claim.

Tests before moving on:

- Telegram authority-spoof text is checked and can be quarantined.
- GitHub PR touching protected paths is checked.
- Codex memory-write claim is checked.
- Casual chat/reaction events are skipped.

## Phase 3: GitHub Integration

Goal: PR warnings where the risk happens.

Minimum behavior:

- Read PR title, body, changed files, and a small diff summary.
- Send a `github` event to `/events/ingest`.
- Post or update one Hindsight PR comment with verdict, evidence, and action.
- Show only the strongest primary evidence in the PR comment; keep the full retrieved set in the event record.

Current local route:

- `POST /integrations/github/pr/check`
- Reads the PR and changed-file patches through the authenticated GitHub CLI.
- Sends title, body, changed files, and a bounded diff summary into the workstream pipeline.
- Posts or updates one marked PR comment.

Tests before moving on:

- Conflict PR gets one stable comment, not repeated spam.
- Safe PR does not get a scary warning.
- API failures degrade cleanly.
- Secrets stay out of logs and git.

## Phase 4: Telegram Integration

Goal: free local chat warnings without a public tunnel.

Minimum behavior:

- Listen through Telegram Bot API long polling.
- Send a `telegram` event to `/events/ingest`.
- Reply to the message with warning, evidence, and recommended control.

Current local routes:

- `POST /integrations/telegram/update/test`
- `python -m app.telegram_polling`
- Uses outbound long polling, so it works from localhost without ngrok or Socket Mode.
- Posts replies through Telegram `sendMessage` when `TELEGRAM_BOT_TOKEN` is configured.

Required live Telegram configuration:

- `TELEGRAM_BOT_TOKEN`: create with BotFather. Do not commit it.

Tests before moving on:

- Bot replies only when invoked.
- Repeated updates are idempotent by event id.
- Authority-spoof and instruction-override examples are warned or quarantined.
- Casual messages are skipped.

## Phase 5: Codex / Agent Session Integration

Goal: protect the point where agent output may become memory.

Minimum behavior depends on what Phase 0 proves. Valid paths are an official API, a transcript export, a local wrapper, or a manual selected-transcript send.

Tests before moving on:

- One real session event reaches `/events/ingest`.
- A memory-write claim is checked before it is trusted.
- Quarantined content is not sent into Cognee `improve()`.

## Phase 6: Product Console

Goal: operational view, not the main warning surface.

The console should show:

- live workstream events
- source and actor
- screening decision
- warning or quarantine verdict
- Cognee evidence
- trust ledger
- graph/proof links
- memory surgery controls

Warnings stay in GitHub, Telegram, and Codex. Governance and audit live in the console.

Current local surface:

- `GET /live-chat`
- Standalone backend-served chat console; does not modify the `localhost:5173` backup UI.
- Sends chat messages as `live_chat` workstream events.
- Pops a warning panel/toast only when `/events/ingest` returns a warning or quarantine outcome.

## Phase 7: Rehearsal Gate

Run the full script twice:

1. Seed trusted memory.
2. Trigger a GitHub PR conflict.
3. Trigger a Telegram authority-spoof warning.
4. Trigger a Codex memory-write claim.
5. Show all events in the console.
6. Mark a warning useful and verify ledger/improve behavior.
7. Forget an obsolete memory and show proof.

If any real integration fails, use the local simulator with the same payload contract and state clearly which adapter is simulated.