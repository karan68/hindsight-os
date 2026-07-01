from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models import AskRequest, DemoState, FeedbackRequest, GraphSnapshot, ProposalRequest
from app.service import (
    ask_memory,
    check_proposal,
    forget_obsolete,
    graph_snapshot,
    seed_demo,
    submit_feedback,
    warm_recall,
)
from app.state import load_state
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


@app.post("/ask")
async def ask(request: AskRequest):
    return await ask_memory(request.question)


@app.post("/warning/{warning_id}/feedback")
async def warning_feedback(warning_id: str, request: FeedbackRequest):
    return await submit_feedback(warning_id, request.useful)


@app.post("/memory/{data_id}/forget")
async def memory_forget(data_id: str):
    return await forget_obsolete(data_id)
