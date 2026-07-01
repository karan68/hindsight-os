// Typed client for the Hindsight OS backend.
// Base URL is overridable so the same UI can point at a remote/Cognee Cloud-backed
// instance later without code changes.
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export type Classification =
  | 'conflict'
  | 'confirmation'
  | 'duplicate'
  | 'stale_assumption'
  | 'unrelated'
  | 'insufficient_evidence'

export type Mode = 'demo' | 'cognee'

export interface OpEvent {
  op: string
  params: Record<string, unknown>
  status: 'ok' | 'error'
  duration_ms: number
  detail: string
  raw: string | null
  ts: string
}

export interface MemoryItem {
  id: string
  label: string
  text: string
  node_sets: string[]
  status: 'active' | 'obsolete' | 'forgotten'
  source: string
}

export interface EvidenceItem {
  id: string
  label: string
  snippet: string
  node_sets: string[]
  score: number | null
  data_id: string | null
  chunk_index: number | null
  status: string
  is_target: boolean
  raw: string | null
}

export interface WarningCard {
  id: string
  proposal: string
  classification: Classification
  confidence: number
  summary: string
  recommended_action: 'warn' | 'allow' | 'ask_human' | 'remember_new_info'
  evidence: EvidenceItem[]
  limits: string
  session_id: string | null
  qa_id: string | null
  mode: Mode
  reasoning: string
  conflicting_memories: string[]
  raw_context: string
  reasoning_path: string[]
  graph_nodes: string[]
  vector_cited: string[]
  graph_cited: string[]
  retrieval_note: string
  manipulation_risk: number
  manipulation_tactic: string
  is_poisoning: boolean
  threat_id: string
  threat_rationale: string
  recommended_control: 'allow' | 'warn' | 'quarantine'
  ops: OpEvent[]
  latency_ms: number
}

export interface SeedResponse {
  dataset: string
  mode: Mode
  items: MemoryItem[]
  lifecycle: string[]
}

export interface FeedbackResponse {
  warning_id: string
  feedback_score: number
  improve_status: 'queued' | 'completed' | 'demo_recorded' | 'skipped' | 'blocked_quarantined'
  recall_after_feedback: string
  lifecycle: string[]
  mode: Mode
  blocked: boolean
  threat_id: string
  ops: OpEvent[]
}

export interface AskResponse {
  question: string
  answer: string
  evidence: EvidenceItem[]
  mode: Mode
  ops: OpEvent[]
  latency_ms: number
}

export interface LedgerEntry {
  id: string
  ts: string
  proposal: string
  classification: string
  cited: string[]
  feedback: 'useful' | 'wrong' | 'quarantine'
  feedback_score: number
  improve_status: string
  answer: string
  mode: Mode
  blocked: boolean
}

export interface ForgetResponse {
  data_id: string
  removed: string[]
  preserved: string[]
  recall_after_forget: string
  lifecycle: string[]
  mode: Mode
  before: EvidenceItem[]
  after: EvidenceItem[]
  graph_before: Record<string, number>
  graph_after: Record<string, number>
  ops: OpEvent[]
}

export interface GraphNode {
  id: string
  label: string
  type: string
  group: string
  node_sets: string[]
  content_hash: string
}

export interface GraphEdge {
  source: string
  target: string
  rel: string
}

export interface GraphSnapshot {
  mode: Mode
  nodes: GraphNode[]
  edges: GraphEdge[]
  node_count: number
  edge_count: number
  truncated: boolean
  ops: OpEvent[]
}

export interface DemoState {
  dataset: string
  mode: Mode
  seeded: boolean
  memories: MemoryItem[]
  latest_warning: WarningCard | null
  lifecycle: string[]
  ledger: LedgerEntry[]
  llm_model: string
  llm_provider: string
  llm_endpoint: string
  embedding_model: string
  embedding_provider: string
  embedding_dims: string
  structured_framework: string
  cognee_version: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`${response.status} ${response.statusText}: ${detail}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  getState: () => request<DemoState>('/state'),
  getGraph: () => request<GraphSnapshot>('/graph'),
  seed: () => request<SeedResponse>('/seed', { method: 'POST' }),
  checkProposal: (proposal: string) =>
    request<WarningCard>('/proposal/check', {
      method: 'POST',
      body: JSON.stringify({ proposal }),
    }),
  ask: (question: string) =>
    request<AskResponse>('/ask', {
      method: 'POST',
      body: JSON.stringify({ question }),
    }),
  sendFeedback: (warningId: string, useful: boolean) =>
    request<FeedbackResponse>(`/warning/${warningId}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ useful }),
    }),
  forget: (dataId: string) =>
    request<ForgetResponse>(`/memory/${dataId}/forget`, { method: 'POST' }),
}
