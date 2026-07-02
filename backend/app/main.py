from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.codex_integration import CodexSessionCheckRequest, CodexSessionCheckResponse, check_codex_session
from app.github_integration import GitHubPrCheckRequest, GitHubPrCheckResponse, check_github_pr
from app.models import AskRequest, DemoState, FeedbackRequest, GraphSnapshot, ProposalRequest
from app.service import (
    activate_demo_mode,
    ask_memory,
    check_proposal,
    forget_obsolete,
    graph_snapshot,
    ops_preflight,
    seed_demo,
    submit_feedback,
    warm_recall,
)
from app.simulator import (
    SimulatorRunRequest,
    SimulatorRunResponse,
    SimulatorScenario,
    list_simulator_scenarios,
    run_simulator,
)
from app.state import load_state
from app.telegram_integration import TelegramLocalTestRequest, TelegramProcessResponse, process_telegram_update
from app.workstream import (
    WorkstreamEvent,
    WorkstreamIngestResponse,
    WorkstreamRecord,
    ingest_workstream_event,
    list_workstream_events,
)

# override=True so backend/.env wins over any pre-existing shell env vars
# (e.g. a global Ollama LLM_MODEL) that would otherwise leak into Cognee.
load_dotenv(override=True)

app = FastAPI(title="Hindsight OS", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _warmup() -> None:
    # Keep startup fast. The first proposal check awaits warm_recall() before
    # retrieval, so the cold-vector outlier cannot leak into a verdict.
    return None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ops/preflight")
async def preflight():
    return await ops_preflight()


@app.post("/ops/demo-mode", response_model=DemoState)
def demo_mode():
    return activate_demo_mode()


@app.get("/live-chat")
@app.get("/live-chat/")
def live_chat_console():
    return FileResponse(Path(__file__).resolve().parent / "static" / "live_chat.html")


@app.post("/seed")
async def seed():
    return await seed_demo()


@app.get("/state", response_model=DemoState)
def state() -> DemoState:
    return load_state()


@app.get("/graph", response_model=GraphSnapshot)
async def graph() -> GraphSnapshot:
    return await graph_snapshot()


@app.post("/proposal/check")
async def proposal_check(request: ProposalRequest):
    return await check_proposal(request)


@app.post("/events/ingest", response_model=WorkstreamIngestResponse)
async def event_ingest(request: WorkstreamEvent):
    return await ingest_workstream_event(request)


@app.get("/events", response_model=list[WorkstreamRecord])
def events():
    return list_workstream_events()


@app.post("/integrations/github/pr/check", response_model=GitHubPrCheckResponse)
async def github_pr_check(request: GitHubPrCheckRequest):
    return await check_github_pr(request)


@app.post("/integrations/telegram/update/test", response_model=TelegramProcessResponse)
async def telegram_update_test(request: TelegramLocalTestRequest):
    return await process_telegram_update(request.update, post_message=request.post_message)


@app.post("/integrations/codex/session/check", response_model=CodexSessionCheckResponse)
async def codex_session_check(request: CodexSessionCheckRequest):
    return await check_codex_session(request)


@app.get("/simulator/scenarios", response_model=list[SimulatorScenario])
def simulator_scenarios():
    return list_simulator_scenarios()


@app.post("/simulator/run", response_model=SimulatorRunResponse)
async def simulator_run(request: SimulatorRunRequest):
    return await run_simulator(request)


@app.post("/ask")
async def ask(request: AskRequest):
    return await ask_memory(request.question)


@app.post("/warning/{warning_id}/feedback")
async def warning_feedback(warning_id: str, request: FeedbackRequest):
    return await submit_feedback(warning_id, request.useful)


@app.post("/memory/{data_id}/forget")
async def memory_forget(data_id: str):
    return await forget_obsolete(data_id)
