# Hindsight OS

**An immune system for AI memory.** Hindsight OS remembers engineering decisions in Cognee, checks new proposals against that memory, blocks memory-poisoning attempts, learns from feedback, and proves what it forgets.

Most AI memory only grows. Hindsight OS asks the harder question: what happens when memory becomes stale, contradictory, or actively poisoned?

## What It Does

Hindsight OS is a decision-memory console for teams and agents. It uses Cognee as the persistent memory layer, then adds a conservative conflict classifier and a memory-integrity workflow on top.

The demo starts with 18 seeded engineering memories: ADRs, incidents, security standards, UX experiments, obsolete brainstorms, and service architecture notes. On a local Cognee run this builds a few hundred graph nodes and more than a thousand edges; exact extraction counts can vary between runs.

When a new proposal arrives, Hindsight OS:

1. Recalls semantically related evidence from Cognee (`CHUNKS`).
2. Retrieves relationship facts from Cognee graph context (`GRAPH_COMPLETION`).
3. Classifies the proposal as conflict, confirmation, stale assumption, unrelated, or insufficient evidence.
4. Runs a Sentinel check for memory-poisoning tactics.
5. Lets the operator grade the warning and runs Cognee `improve()`.
6. Lets the operator surgically `forget()` obsolete memory and shows before/after proof.

## The Honest Cognee Boundary

Cognee provides persistent graph-vector memory, recall, feedback-aware improvement, and forgetting. Hindsight OS adds the conflict classifier, poisoning policy, and product workflow.

| Capability | Cognee Provides | Hindsight OS Adds |
| --- | --- | --- |
| Persistent memory | `remember()` into graph/vector memory | decision corpus, node sets, provenance labels |
| Similarity recall | `recall(query_type=CHUNKS)` | evidence cards and cited-memory UX |
| Relationship recall | `recall(query_type=GRAPH_COMPLETION, only_context=True)` | extracted relationship facts in the verdict |
| Feedback learning | `session.add_feedback()` + `improve()` | trust ledger and operator workflow |
| Forgetting | `forget(data_id=..., dataset=...)` | before/after proof, preserved concept display |
| Conflict detection | retrieved evidence | app-level LLM classifier and Sentinel policy |

Important: this project does **not** claim that Cognee alone detects contradictions, or that graph traversal out-retrieves semantic similarity on this corpus. The UI frames recall honestly as **Similarity** (semantic hits) and **Relationships** (graph-derived facts).

## Why It Uses Cognee Deeply

This is not a `remember()` + `recall()` wrapper. The app exercises the core memory lifecycle:

- `remember(DataItem(...), dataset_name=..., node_set=...)` for structured seeded memories
- `recall(query_type=CHUNKS, top_k=...)` for semantic evidence retrieval
- `recall(query_type=GRAPH_COMPLETION, only_context=True, include_references=True, neighborhood_depth=2)` for relationship facts
- `recall(session_id=...)` to create a Cognee session Q&A entry
- `session.add_feedback(...)` to score a warning
- `improve(dataset=..., session_ids=..., feedback_alpha=...)` to enrich/reweight memory
- `recall(feedback_influence=...)` to show feedback-aware recall
- `forget(data_id=..., dataset=...)` to remove an obsolete memory item
- direct graph-engine reads for the live graph visualization and forget proof

## Demo Flow

1. **Check a decision**
   Pick an example proposal such as adding Redis as a second source of truth. Hindsight recalls Cognee evidence, classifies a conflict, and shows both Similarity hits and Relationship facts.

2. **Memory-poisoning defense**
   Try a simulated supply-chain override. Sentinel detects instruction-override / fabricated-approval style manipulation and blocks ingestion so the hostile text never reaches Cognee `improve()`.

3. **Trust ledger**
   Mark a warning useful. Hindsight writes a session Q&A, records feedback, runs `improve()`, and stores the result in the ledger.

4. **Forget with proof**
   Forget the obsolete client-side-storage brainstorm. The app calls Cognee `forget()`, then shows before/after recall and graph counts while preserving shared concepts used by other memories.

## Architecture

```text
frontend/   Vite + React + TypeScript  (http://localhost:5173)
backend/    FastAPI + Cognee SDK        (http://127.0.0.1:8000)

backend/app/
  main.py          FastAPI routes
  models.py        Pydantic contracts
  service.py       lifecycle orchestration + warmup guard
  cognee_client.py Cognee remember/recall/improve/forget calls
  classifier.py    deterministic fallback classifier
  seed_data.py     18 decision memories
  state.py         local demo state and runtime telemetry
```

## Runtime Modes

- **Cognee mode**: enabled when `LLM_API_KEY` is configured; runs real Cognee memory operations.
- **Demo mode**: deterministic fallback if Cognee/LLM calls are unavailable, so the UI can still be explored.

The default tested setup is Azure AI Foundry (`azure/gpt-5.4`) for structured LLM calls and local Ollama (`nomic-embed-text`) for embeddings.

## Setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- Ollama with `nomic-embed-text`
- An LLM key for live Cognee mode
- Cognee available to the backend (see `backend/requirements.txt`)

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# copy ../.env.example to backend/.env and fill in your provider values
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Seed the live Cognee memory once before a demo:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/seed
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Demo Reliability Notes

- The first proposal check waits for recall warmup so Cognee's cold vector path does not produce a one-off under-retrieval.
- Seeding is real graph extraction and can take several minutes with 18 memories.
- `backend/.env`, Cognee databases, virtualenvs, node_modules, dist, and local app state are ignored.

## Security Notes

- Never commit `backend/.env`.
- Sentinel blocks poisoned content from entering `improve()`; it logs the quarantine decision instead.
- The app demonstrates memory-integrity controls; it is not a full enterprise access-control system.

## License

Hackathon demo project.
