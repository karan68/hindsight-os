import { useState } from 'react'
import type { OpEvent } from '../api'

function paramStr(params: Record<string, unknown>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== '' && v !== null && v !== undefined)
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
  return parts.join(' ')
}

// The "receipts": real Cognee/LLM calls with measured latencies and raw payloads.
export function OpsConsole({
  ops,
  title = 'cognee ops · live trace',
  idle = false,
  busy = false,
}: {
  ops: OpEvent[]
  title?: string
  idle?: boolean
  busy?: boolean
}) {
  const [open, setOpen] = useState<number | null>(null)
  if ((!ops || ops.length === 0) && !idle) return null
  const total = ops.reduce((acc, op) => acc + op.duration_ms, 0)

  return (
    <div className="ops">
      <div className="ops-head">
        <span className="ops-title">
          <span className={`ops-led${busy ? ' busy' : ''}`} />
          {title}
        </span>
        <span className="ops-count">
          {ops.length === 0
            ? busy
              ? 'running…'
              : 'idle'
            : `${ops.length} call${ops.length === 1 ? '' : 's'} · ${total}ms`}
        </span>
      </div>
      <div className="ops-list">
        {ops.length === 0 ? (
          <div className="ops-idle">
            {busy
              ? '› executing against Cognee…'
              : '› awaiting a proposal — run a check to stream the live recall + classify trace'}
          </div>
        ) : (
          ops.map((op, i) => {
            const params = paramStr(op.params)
            const expandable = Boolean(op.raw)
            return (
              <div key={i} className={`op ${op.status}`}>
                <button
                  className="op-line"
                  onClick={() => expandable && setOpen(open === i ? null : i)}
                  data-expandable={expandable}
                >
                  <span className={`op-dot ${op.status}`} />
                  <span className="op-ts">{op.ts}</span>
                  <span className="op-name">{op.op}</span>
                  {params && <span className="op-params">{params}</span>}
                  {op.detail && <span className="op-detail">→ {op.detail}</span>}
                  <span className="op-ms">{op.duration_ms}ms</span>
                  {expandable && <span className="op-caret">{open === i ? '▾' : '▸'}</span>}
                </button>
                {open === i && op.raw && <pre className="op-raw">{op.raw}</pre>}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
