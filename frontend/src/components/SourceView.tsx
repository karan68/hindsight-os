// The "source of record" behind each memory — a formal mock of the original
// artifact Cognee ingested (Jira ticket, Slack thread, GitHub ADR/PR, Google Doc
// RFC, A/B experiment result, wiki standard). Front-end only; illustrative of the
// ingestion connectors described in the roadmap.

type SourceKind = 'github' | 'jira' | 'wiki' | 'experiment' | 'slack' | 'gdoc'

interface Field {
  label: string
  value: string
}

interface Metric {
  name: string
  control: string
  variant: string
  delta: string
  bad?: boolean
}

interface ChatMessage {
  author: string
  initial: string
  time: string
  text: string
}

interface SourceArtifact {
  kind: SourceKind
  brand: string
  location: string
  title: string
  badge?: string
  fields?: Field[]
  body?: string[]
  breadcrumb?: string[]
  updated?: string
  metrics?: Metric[]
  decision?: string
  messages?: ChatMessage[]
  outcome?: string
}

const ARTIFACTS: Record<string, SourceArtifact> = {
  'adr-021': {
    kind: 'github',
    brand: 'GitHub',
    location: 'docs/adr/ADR-021-service-source-of-truth.md',
    title: 'ADR-021 · Service Source of Truth',
    badge: 'PR #482 · merged',
    fields: [
      { label: 'Status', value: 'Accepted' },
      { label: 'Author', value: '@priya' },
      { label: 'Reviewers', value: '@sam · @lena' },
    ],
    body: [
      '# ADR-021: Service Source of Truth',
      '## Status',
      'Accepted',
      '## Context',
      'Teams were tempted to add read replicas in other stores to cut Spanner cost, creating a second place the same entity could be written.',
      '## Decision',
      'Each user-facing service keeps its source of truth in Spanner (regionally replicated). Caches (Memcache, CDN) are non-authoritative and must be regenerable from Spanner. A service must NOT introduce a second authoritative store for the same entity.',
      '## Consequences',
      'Consistency stays simple; caches are disposable and can be rebuilt at any time.',
    ],
  },
  'rel-policy-09': {
    kind: 'jira',
    brand: 'Jira',
    location: 'INC-19',
    title: 'Checkout P1 — no-canary launch caused an SLO breach',
    badge: 'P1',
    fields: [
      { label: 'Type', value: 'Incident · Postmortem' },
      { label: 'Status', value: 'Done' },
      { label: 'Reporter', value: '@sre-oncall' },
      { label: 'Resolution', value: 'Fixed' },
    ],
    body: [
      'Impact: 22 minutes of elevated 5xx on checkout after a config was deployed straight to 100% with no canary.',
      'Root cause: the rollout skipped canary stages and there was no automated rollback on SLO regression.',
      'Action items:',
      '• Enforce canary at 1% then 10% then 100%, with automated rollback on any SLO regression.',
      '• No production pushes during the Fri 16:00 – Mon 09:00 freeze window.',
    ],
  },
  'priv-014': {
    kind: 'wiki',
    brand: 'Wiki',
    location: 'privacy / standards',
    title: 'PII Logging Restriction',
    breadcrumb: ['Privacy', 'Standards', 'PII Logging'],
    updated: 'Updated 2026-05-02 · Owner: Privacy',
    badge: 'Mandatory',
    body: [
      'User PII — email, full name, postal address, raw IP — must never be written to application logs, traces, or analytics events.',
      'Use the hashed user_id instead. Log retention is 30 days.',
      'Basis:',
      '• GDPR / CCPA obligations.',
      '• Incident INC-31 (a plaintext-email log leak).',
    ],
  },
  'exp-208': {
    kind: 'experiment',
    brand: 'Experiment platform',
    location: 'EXP-208',
    title: 'Infinite scroll vs pagination — results page',
    badge: 'Concluded · reverted',
    fields: [
      { label: 'Owner', value: '@diego (PM)' },
      { label: 'Duration', value: '14 days' },
      { label: 'Exposure', value: '50 / 50' },
    ],
    metrics: [
      { name: 'Task completion', control: '78.4%', variant: '74.1%', delta: '−4.3 pp', bad: true },
      { name: 'p95 latency (low-end)', control: '1.9 s', variant: '2.7 s', delta: '+0.8 s', bad: true },
      { name: 'Scroll depth', control: '—', variant: '+18%', delta: '+18%' },
    ],
    decision: 'Rolled back. Keep pagination on the results page.',
  },
  'dep-policy-03': {
    kind: 'wiki',
    brand: 'Wiki',
    location: 'security / standards',
    title: 'Third-Party Dependency Policy',
    breadcrumb: ['Security', 'Standards', 'Dependencies'],
    updated: 'Updated 2026-04-18 · Owner: Security',
    badge: 'Enforced',
    body: [
      'New third-party dependencies must pass OSS review (license plus security scan) before use.',
      'Add dependencies only through the locked, vendored manifest. Builds must never pull "latest" from public registries at build time.',
      'Rationale:',
      '• Software supply-chain risk (e.g. XZ-style maintainer attacks).',
      '• Reproducible, auditable builds.',
    ],
  },
  'brainstorm-localstorage': {
    kind: 'slack',
    brand: 'Slack',
    location: '#eng-decisions',
    title: 'localStorage for session/profile state?',
    messages: [
      {
        author: 'Rohan',
        initial: 'R',
        time: '10:02',
        text: 'Idea: what if we store session + profile state in client-side localStorage to cut Spanner cost?',
      },
      {
        author: 'Priya',
        initial: 'P',
        time: '10:09',
        text: 'Tempting, but that makes the client authoritative — no server-side source of truth, and it is hard to audit.',
      },
      {
        author: 'Lena',
        initial: 'L',
        time: '10:12',
        text: 'It also breaks multi-device. I would keep Spanner as the source of truth and put Memcache in front.',
      },
      {
        author: 'Rohan',
        initial: 'R',
        time: '10:15',
        text: 'Fair. Parking this one.',
      },
    ],
    outcome: 'Outcome: not adopted · superseded by ADR-021.',
  },
  'api-conv-02': {
    kind: 'gdoc',
    brand: 'Google Docs',
    location: 'RFC',
    title: 'RFC: Service API & RPC Conventions',
    updated: 'Authors: @platform · Last edited 2026-05-10',
    badge: 'Accepted',
    body: [
      'Internal service-to-service traffic uses gRPC with deadlines, retries, and the standard auth interceptor.',
      'The public edge is REST/JSON behind the API gateway.',
      'Services must not reach across boundaries into another service\u2019s database.',
    ],
  },
}

export function sourceBrand(memoryId: string): string {
  return ARTIFACTS[memoryId]?.brand ?? 'document'
}

function BodyLines({ lines }: { lines: string[] }) {
  return (
    <div className="src-body">
      {lines.map((ln, i) => {
        if (ln.startsWith('## ')) return <h5 key={i} className="src-h2">{ln.slice(3)}</h5>
        if (ln.startsWith('# ')) return <h4 key={i} className="src-h1">{ln.slice(2)}</h4>
        if (ln.startsWith('\u2022 ')) return <p key={i} className="src-li">{ln.slice(2)}</p>
        if (ln.endsWith(':')) return <p key={i} className="src-strong">{ln}</p>
        return <p key={i} className="src-p">{ln}</p>
      })}
    </div>
  )
}

function Fields({ fields }: { fields: Field[] }) {
  return (
    <div className="src-fields">
      {fields.map((f) => (
        <div key={f.label} className="src-field">
          <span className="src-field-label">{f.label}</span>
          <span className="src-field-value">{f.value}</span>
        </div>
      ))}
    </div>
  )
}

export function SourceView({ memoryId }: { memoryId: string }) {
  const a = ARTIFACTS[memoryId]
  if (!a) {
    return <div className="empty">No original source artifact is attached to this memory.</div>
  }

  return (
    <div className={`src-card src-${a.kind}`}>
      <div className="src-head">
        <span className="src-brand-dot" />
        <span className="src-brand">{a.brand}</span>
        <span className="src-loc">{a.location}</span>
        {a.badge && <span className="src-badge">{a.badge}</span>}
      </div>

      {a.breadcrumb && (
        <div className="src-breadcrumb">
          {a.breadcrumb.map((b, i) => (
            <span key={b}>
              {i > 0 && <span className="src-crumb-sep">/</span>}
              {b}
            </span>
          ))}
        </div>
      )}

      <h4 className="src-title">{a.title}</h4>
      {a.updated && <p className="src-updated">{a.updated}</p>}
      {a.fields && <Fields fields={a.fields} />}

      {a.messages ? (
        <div className="src-thread">
          {a.messages.map((m, i) => (
            <div key={i} className="src-msg">
              <span className="src-avatar">{m.initial}</span>
              <div className="src-msg-main">
                <p className="src-msg-head">
                  <span className="src-msg-author">{m.author}</span>
                  <span className="src-msg-time">{m.time}</span>
                </p>
                <p className="src-msg-text">{m.text}</p>
              </div>
            </div>
          ))}
          {a.outcome && <p className="src-outcome">{a.outcome}</p>}
        </div>
      ) : null}

      {a.metrics && (
        <table className="src-metrics">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Control</th>
              <th>Variant</th>
              <th>&#916;</th>
            </tr>
          </thead>
          <tbody>
            {a.metrics.map((m) => (
              <tr key={m.name}>
                <td>{m.name}</td>
                <td>{m.control}</td>
                <td>{m.variant}</td>
                <td className={m.bad ? 'src-delta bad' : 'src-delta'}>{m.delta}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {a.body && <BodyLines lines={a.body} />}
      {a.decision && <p className="src-decision">{a.decision}</p>}
    </div>
  )
}
