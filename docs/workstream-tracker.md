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
- [ ] Record the exact expected demo script.

### 2. Cognee Reliability Pass

- [x] Add `/ops/preflight` to report state/Cognee graph readiness.
- [x] Add `/ops/demo-mode` to force deterministic demo mode without touching Cognee data.
- [x] Ensure demo-mode checks do not call live Cognee even if `LLM_API_KEY` is configured.
- [ ] Kill duplicate/orphan Python processes before live Cognee work.
- [ ] Pre-seed once and warm recall for a live `mode=cognee` demo.
- [ ] Run one GitHub/Telegram/live-chat conflict in `mode=cognee`.
- [ ] If graph remains empty or slow, use `/ops/demo-mode` for external demo and call out live Cognee limitation honestly.

### 3. Codex / Agent Session Integration

- [x] Verify local Codex CLI exists (`codex.ps1`). No stable transcript export/API was proven.
- [x] Add manual/wrapper transcript adapter:
  - `POST /integrations/codex/session/check`
  - `python -m app.codex_session --file transcript.txt`
- [x] Send one real Codex CLI transcript into the adapter via `codex exec --output-last-message`.
- [x] Show memory-write conflict blocked/warned: `classification=conflict`, `can_remember=false`.
- [x] Document proof in `docs/codex-live-proof.md`.
- [ ] Ensure quarantined content does not enter `improve()` when live Sentinel flags poisoning.

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

## Recommended Next Step

Record the exact demo script next, then move to Codex / agent-session integration.