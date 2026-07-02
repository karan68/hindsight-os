# Hindsight OS Workstream Tracker

Last updated: 2026-07-02

This tracker records what is actually implemented and validated. Keep the original `http://localhost:5173/` app as the backup demo; the workstream product work lives alongside it.

## Current Demo Surfaces

- Backup memory console: `http://localhost:5173/`
- Backend API: `http://127.0.0.1:8000`
- Live chat console: `http://127.0.0.1:8000/live-chat`
- Telegram bot: `HindSightAIBOT`
- GitHub workstream PR: https://github.com/karan68/hindsight-os/pull/1
- GitHub conflict proof PR: https://github.com/karan68/hindsight-os/pull/2

## Done

- [x] Preserve existing Vite UI as backup.
- [x] Add core workstream event pipeline.
  - `POST /events/ingest`
  - `GET /events`
  - Sources: `github`, `telegram`, `codex`, `jira`, `live_chat`, `simulator`
- [x] Add cheap policy screening before Cognee recall.
  - Explicit `/hindsight` and `@Hindsight`
  - Decision language
  - Protected topics and paths
  - Low-signal event skip
- [x] Add command stripping before retrieval/classification.
- [x] Add primary evidence ranking for concise in-flow warnings.
- [x] Add GitHub PR check wrapper.
  - Reads PR title/body/files/diff via GitHub CLI/API.
  - Posts or updates one stable PR comment.
  - Proof comment on PR #2 validates conflict with `ADR-021 Service Source of Truth`.
- [x] Add local simulator.
  - `GET /simulator/scenarios`
  - `POST /simulator/run`
  - Validated: 5 total, 5 passed, 0 failed.
- [x] Replace Slack path with Telegram.
  - Slack code and dependency removed.
  - Telegram long polling route added.
  - `POST /integrations/telegram/update/test`
  - `python -m app.telegram_polling`
- [x] Prove Telegram bot message path.
  - `/hindsight Maya approved replacing Spanner with Redis...`
  - Result: `warned`, `conflict`, evidence `ADR-021` + `INC-51`, reply posted.
- [x] Add separate live chat console.
  - `GET /live-chat`
  - Browser proof: conflict/quarantine warning displayed with `ADR-021`.
- [x] Add Cognee reliability controls.
  - `GET /ops/preflight`
  - `POST /ops/demo-mode`
  - Demo-mode state now avoids live Cognee even when `.env` contains an LLM key.
- [x] Update env example and workstream plan.

## Validation Commands Already Run

```powershell
cd backend
.\.venv\Scripts\python.exe -m compileall app
```

Simulator deterministic validation:

```text
5 total, 5 passed, 0 failed
```

Telegram proof:

```text
outcome: warned
classification: conflict
primary evidence: ADR-021 Service Source of Truth, INC-51 Double-Charge Postmortem
reply posted: true
```

Live chat proof:

```text
outcome: quarantined
classification: conflict
primary evidence: ADR-021 Service Source of Truth, INC-51 Double-Charge Postmortem
```

Reliability proof:

```text
POST /ops/demo-mode -> mode=demo, seeded=True, 21 memories
GET /ops/preflight -> ready_demo
live_chat conflict in demo mode -> warned/conflict, ops=workstream.screen -> recall -> classify
```

## Known Risks / Gotchas

- Telegram token was pasted in chat. Rotate it after the project/demo.
- Live Cognee mode can be slow or hit empty-graph behavior if state says items exist but the graph is empty.
- For smooth demo, either use deterministic fallback or pre-seed/warm Cognee carefully.
- Avoid running multiple `uvicorn` processes. One process should own the backend/Cognee path.
- `ngrok` is blocked by Windows Application Control on this machine, so tunnel-based integrations are not reliable here.
- `load_dotenv(override=True)` means `.env` can override shell variables during tests; clear/set environment after importing app when forcing deterministic mode.

## Next Work

### 1. Telegram Group Demo

- [x] Create a Telegram group.
- [x] Add `HindSightAIBOT`.
- [x] Decide privacy mode:
  - Safer demo: use `/hindsight` command in group.
  - Ambient demo: disable privacy mode in BotFather so the bot sees normal group messages.
- [x] Run `python -m app.telegram_polling`.
- [x] Send a risky message and confirm Hindsight replies in group.
- [x] Validate three outcomes in group:
  - conflict -> warn
  - instruction override -> quarantine
  - non-authoritative Redis cache -> allow/confirmation
- [x] Record the exact expected demo script in `docs/demo-script.md`.

### 2. Cognee Reliability Pass

- [x] Add `/ops/preflight` to report state/Cognee graph readiness.
- [x] Add `/ops/demo-mode` to force deterministic demo mode without touching Cognee data.
- [x] Ensure demo-mode checks do not call live Cognee even if `LLM_API_KEY` is configured.
- [x] Kill duplicate/orphan Python processes before live Cognee work.
- [x] Pre-seed once and warm recall for a live `mode=cognee` demo (seed 21 docs ~794s, warm on boot).
- [x] Run one GitHub/Telegram/live-chat conflict in `mode=cognee` (live_chat -> warned/conflict,
      warnmode=cognee, evidence ADR-021; Codex session -> quarantined; proposal/check -> conflict 0.97).
- [x] If graph remains empty or slow, use `/ops/demo-mode` for external demo and call out live Cognee limitation honestly.

### 3. Codex / Agent Session Integration

- [x] Verify local Codex CLI exists (`codex.ps1`). No stable transcript export/API was proven.
- [x] Inspect Codex plugin/hook surface.
  - `codex features` reports `hooks` and `plugins` as stable.
  - `plugin_hooks` is `removed`, so hooks must be installed as native config, not inside a plugin.
  - Native hook events verified in the Codex binary: `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `Stop`, and more.
- [x] Prove native in-session interception (see `docs/codex-hook-proof.md`).
  - Hook script `hooks/hindsight_codex_hook.py` + installer `scripts/install-codex-hook.ps1`.
  - `additionalContext` injection flips Codex from accepting a poisoning claim to rejecting it, citing `ADR-021` + `INC-51`.
  - `permissionDecision: deny` hard-blocks a tool call (`Command blocked by PreToolUse hook`).
  - Honest caveat: hooks need trust (interactive TUI approval, or `--dangerously-bypass-hook-trust` for vetted automation); backend must be running; hook fails open.
- [x] Add manual/wrapper transcript adapter:
  - `POST /integrations/codex/session/check`
  - `python -m app.codex_session --file transcript.txt`
- [x] Add Codex sidecar command:
  - `python -m app.hindsight_codex "<message>"`
  - Runs `codex exec --output-last-message`, checks the actual Codex final message, and prints Hindsight outcome/evidence.
- [x] Add optional Telegram alert for Codex warnings/quarantines.
  - CLI flags: `--notify-telegram`, `--telegram-chat-id`.
  - Env flags: `HINDSIGHT_CODEX_NOTIFY_TELEGRAM`, `HINDSIGHT_TELEGRAM_NOTIFY_CHAT_ID`.
- [x] Send one real Codex CLI transcript into the adapter via `codex exec --output-last-message`.
- [x] Show memory-write conflict blocked/warned: `classification=conflict`, `can_remember=false`.
- [x] Document proof in `docs/codex-live-proof.md`.
- [x] Add screenshot-friendly Codex proof page in `docs/codex-proof-screenshot.html`.
- [x] Ensure quarantined content does not enter `improve()` when live Sentinel flags poisoning
      (verified: poisoning feedback -> `improve_status=blocked_quarantined`, Cognee improve skipped).

### 4. Product Console Upgrade

- [ ] Extend `/live-chat` or add a separate ops page.
- [ ] Show all workstream events.
- [ ] Add source filters: GitHub, Telegram, Codex, live chat.
- [ ] Show full evidence drawer.
- [ ] Link warning to graph/proof data.
- [ ] Show trust ledger and memory surgery actions.

### 5. GitHub Productionization

- [ ] Replace local `gh` wrapper with GitHub App/webhook path.
- [ ] Store/update comment id per PR.
- [ ] Handle retries/idempotency.
- [ ] Add safe PR proof so non-risky PRs stay quiet.

## Status Summary (2026-07-02)

### Done and validated

- Workstream event pipeline with tiered screening (`/events/ingest`, `/events`).
- GitHub PR check wrapper + conflict proof on PR #2.
- Telegram bot + group demo (conflict -> warn, override -> quarantine, cache -> allow).
- Telegram alert for flagged Codex output (`--notify-telegram`).
- Live chat console (`/live-chat`).
- Local simulator (5/5 pass).
- Cognee reliability controls (`/ops/preflight`, `/ops/demo-mode`).
- Codex transcript adapter (`/integrations/codex/session/check`, `app.codex_session`).
- Codex sidecar (`app.hindsight_codex`) that runs Codex and checks its output.
- **Native Codex hook interception, proven end-to-end** (`docs/codex-hook-proof.md`):
  hook fires in-session, injects Hindsight's verdict via `additionalContext`
  (flips accept -> reject), and can `deny` a tool call. Installer:
  `scripts/install-codex-hook.ps1`.

### Left to do

- [x] Live Cognee (`mode=cognee`) demo pass: pre-seed + warm, run one conflict live
      (see "Live Cognee pass" below). A real Sentinel quarantine verdict
      (`is_poisoning=true`, `recommended_control=quarantine`) is now produced live;
      wiring the native Codex hook `deny` against that live verdict is still open.
- [x] Ensure quarantined content never enters `improve()` when live Sentinel flags
      poisoning — verified: poisoning feedback returns `improve_status=blocked_quarantined`,
      `blocked=true`, and Cognee `improve` is skipped.
- [x] Fire the native Codex hook `deny` path against the live Sentinel quarantine verdict
      — verified in-session on Codex v0.142.4 (`PreToolUse Blocked`, reason cites ADR-021 +
      INC-51). See docs/codex-hook-proof.md “Live deny proof (cognee mode)”. Required raising
      the hook timeout 6s→30s (env `HINDSIGHT_HOOK_TIMEOUT`) so it does not fail open on
      live-cognee latency.
- [x] Establish persistent hook trust — done via a one-time interactive TUI
      (`codex --profile hindsight`, approve the hook). Three `trusted_hash` entries are
      persisted in `~/.codex/hindsight.config.toml`; `codex exec --profile hindsight` now
      fires the hooks WITHOUT `--dangerously-bypass-hook-trust` (verified: `hook:` lines
      appear and Codex refuses the poisoning command citing the memory-poisoning verdict).
- [x] Harden live-Cognee classify against Azure content-filter retry-storms. A poisoning
      proposal trips the Azure content filter; Cognee retried it with 8/16/32/64/128s backoff,
      so the endpoint overran the hook timeout and failed open (no deny). Fix: bound the
      classify with a hard deadline (`asyncio.wait`, env `HINDSIGHT_CLASSIFY_TIMEOUT`=15s —
      `asyncio.wait_for` was ineffective because it awaits the uncancellable retry loop) and
      fall back to a DETERMINISTIC Sentinel verdict over the REAL recalled evidence
      (quarantine only when manipulation language is present). Result: poisoning now returns
      `blocked/quarantined` in ~15s (was ~5 min → fail open); safe proposals still `allow`.
- [ ] Product console upgrade: unified event dashboard with source filters + evidence drawer.
- [ ] GitHub productionization: replace local `gh` wrapper with a GitHub App/webhook path.

### Live Cognee pass (verified 2026-07-02)

Real `mode=cognee`, Azure gpt-5.4 + local Ollama `nomic-embed-text`, cognee 1.2.2.
One clean uvicorn process; orphan Python killed first (dlt/kuzu lock hygiene).

```text
seed        mode=cognee items=21 secs=794 (real cognify, forget-all then remember x21)
conflict    mode=cognee class=conflict conf=0.97 control=warn
            cited ADR-021 Service Source of Truth + INC-51 Double-Charge Postmortem
            ops recall(CHUNKS) -> recall(GRAPH_COMPLETION, 9 facts) -> classify
safe        mode=cognee class=confirmation control=allow poison=false (no false positive)
poison      mode=cognee class=conflict tactic=instruction_override risk=0.99
            is_poisoning=true control=quarantine
            threat OWASP LLM04 + OWASP LLM01 + MITRE ATLAS AML.T0070
sentinel    poisoning feedback -> improve_status=blocked_quarantined blocked=true (improve skipped)
graph       mode=cognee nodes=250 edges=1324 (live knowledge-graph read)
```

## Recommended Next Step

Live Cognee, persistent hook trust, and the content-filter-resilient deny are all done
and verified. Next: rehearse the full demo from `docs/demo-script.md` end-to-end in
`mode=cognee`, then (optional polish) the product console upgrade and GitHub App path.