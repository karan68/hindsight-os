import { useEffect, useRef, useState } from 'react'
import type { GraphNode, GraphSnapshot } from '../api'

const SVGNS = 'http://www.w3.org/2000/svg'

const TYPE_COLORS: Record<string, string> = {
  Entity: '#ff6b58',
  EntityType: '#e0b24e',
  NodeSet: '#46c98c',
  TextSummary: '#5ad1c8',
  DocumentChunk: '#c98a5a',
  TextDocument: '#9aa4b2',
  memory: '#ff6b58',
  node_set: '#46c98c',
  node: '#7d8694',
}

function colorFor(node: GraphNode): string {
  return TYPE_COLORS[node.type] ?? TYPE_COLORS[node.group] ?? '#8a7f6f'
}

function radiusFor(node: GraphNode): number {
  if (node.type === 'NodeSet' || node.type === 'node_set') return 8
  if (node.type === 'TextDocument' || node.type === 'memory') return 7
  if (node.type === 'EntityType') return 6
  return 4.5
}

type SimNode = GraphNode & {
  x: number
  y: number
  vx: number
  vy: number
  fx: number | null
  fy: number | null
  r: number
}

interface Detail {
  label: string
  type: string
  node_sets: string[]
  degree: number
}

const VB_W = 1000
const VB_H = 760

type SimRefs = {
  groupEls: SVGGElement[]
  keyOf: string[]
  neighbors: Set<number>[]
}

// Live, interactive force-directed graph over the REAL Cognee nodes/edges.
// Continuous physics (requestAnimationFrame), drag, wheel-zoom, pan, hover
// highlight, click-for-detail. Dependency-free, imperative SVG for 60fps.
// `highlight` is a list of memory node-set keys (sorted node_sets joined by '|')
// that should glow — used to tie a verdict's cited memories back to the graph.
export function GraphView({
  snapshot,
  highlight,
}: {
  snapshot: GraphSnapshot | null
  highlight?: string[]
}) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const simRef = useRef<SimRefs | null>(null)
  const cmdRef = useRef<{ seq: number; focus: number[] | null }>({ seq: 0, focus: null })
  const [detail, setDetail] = useState<Detail | null>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host || !snapshot || snapshot.nodes.length === 0) return

    const n = snapshot.nodes.length
    const nodes: SimNode[] = snapshot.nodes.map((nd, i) => {
      const a = (i / n) * Math.PI * 2
      return {
        ...nd,
        x: VB_W / 2 + Math.cos(a) * 240 + ((i * 37) % 40),
        y: VB_H / 2 + Math.sin(a) * 240 + ((i * 53) % 40),
        vx: 0,
        vy: 0,
        fx: null,
        fy: null,
        r: radiusFor(nd),
      }
    })
    const idx = new Map(nodes.map((nd, i) => [nd.id, i]))
    const keyOf = nodes.map((nd) => [...nd.node_sets].sort().join('|'))
    const edges = snapshot.edges
      .filter((e) => idx.has(e.source) && idx.has(e.target))
      .map((e) => ({ a: idx.get(e.source)!, b: idx.get(e.target)! }))
    const degree = new Array<number>(n).fill(0)
    const neighbors: Set<number>[] = nodes.map(() => new Set<number>())
    for (const e of edges) {
      degree[e.a]++
      degree[e.b]++
      neighbors[e.a].add(e.b)
      neighbors[e.b].add(e.a)
    }

    // ---- build SVG imperatively (avoids React reconciliation at 60fps) ----
    const svg = document.createElementNS(SVGNS, 'svg')
    svg.setAttribute('class', 'graph-svg')
    svg.setAttribute('viewBox', `0 0 ${VB_W} ${VB_H}`)
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet')
    const view = document.createElementNS(SVGNS, 'g')
    const gEdges = document.createElementNS(SVGNS, 'g')
    gEdges.setAttribute('class', 'graph-edges')
    const gNodes = document.createElementNS(SVGNS, 'g')
    gNodes.setAttribute('class', 'graph-nodes')
    view.appendChild(gEdges)
    view.appendChild(gNodes)
    svg.appendChild(view)

    const lineEls = edges.map(() => {
      const l = document.createElementNS(SVGNS, 'line')
      gEdges.appendChild(l)
      return l
    })
    const groupEls: SVGGElement[] = []
    nodes.forEach((nd) => {
      const g = document.createElementNS(SVGNS, 'g') as SVGGElement
      g.setAttribute('class', 'gnode')
      const c = document.createElementNS(SVGNS, 'circle')
      c.setAttribute('r', String(nd.r))
      c.setAttribute('fill', colorFor(nd))
      c.setAttribute('stroke', '#0c0f15')
      c.setAttribute('stroke-width', '0.8')
      g.appendChild(c)
      if (
        nd.type === 'NodeSet' ||
        nd.type === 'TextDocument' ||
        nd.type === 'EntityType' ||
        nd.type === 'memory'
      ) {
        const t = document.createElementNS(SVGNS, 'text')
        t.setAttribute('class', 'graph-label')
        t.setAttribute('x', String(nd.r + 3))
        t.setAttribute('y', '3')
        t.textContent = nd.label.length > 22 ? `${nd.label.slice(0, 21)}…` : nd.label
        g.appendChild(t)
      }
      gNodes.appendChild(g)
      groupEls.push(g)
    })

    host.innerHTML = ''
    host.appendChild(svg)
    simRef.current = { groupEls, keyOf, neighbors }

    // ---- pan / zoom ----
    let tx = 0
    let ty = 0
    let k = 1
    let ttx = 0
    let tty = 0
    let tk = 1
    let viewAnimating = false
    let autoFrame = true
    let userMoved = false
    const applyView = () => view.setAttribute('transform', `translate(${tx} ${ty}) scale(${k})`)
    applyView()
    // Frame the whole cluster so it fills the canvas (auto-fit until the user interacts).
    const fitView = () => {
      let minX = Infinity
      let minY = Infinity
      let maxX = -Infinity
      let maxY = -Infinity
      for (const nd of nodes) {
        if (nd.x < minX) minX = nd.x
        if (nd.y < minY) minY = nd.y
        if (nd.x > maxX) maxX = nd.x
        if (nd.y > maxY) maxY = nd.y
      }
      const bw = Math.max(1, maxX - minX)
      const bh = Math.max(1, maxY - minY)
      const pad = 80
      k = Math.min(3.2, Math.max(0.4, Math.min((VB_W - pad * 2) / bw, (VB_H - pad * 2) / bh)))
      tx = VB_W / 2 - k * ((minX + maxX) / 2)
      ty = VB_H / 2 - k * ((minY + maxY) / 2)
      applyView()
    }
    // Smoothly frame an arbitrary set of nodes — used to fly to the cited memories.
    const setTarget = (cx: number, cy: number, nk: number) => {
      tk = nk
      ttx = VB_W / 2 - nk * cx
      tty = VB_H / 2 - nk * cy
      viewAnimating = true
    }
    const applyFocus = (indices: number[]) => {
      let minX = Infinity
      let minY = Infinity
      let maxX = -Infinity
      let maxY = -Infinity
      for (const i of indices) {
        const nd = nodes[i]
        if (!nd) continue
        if (nd.x < minX) minX = nd.x
        if (nd.y < minY) minY = nd.y
        if (nd.x > maxX) maxX = nd.x
        if (nd.y > maxY) maxY = nd.y
      }
      if (minX === Infinity) return
      const bw = Math.max(60, maxX - minX)
      const bh = Math.max(60, maxY - minY)
      const pad = 90
      // Dramatic fly-in: always zoom in hard on the cited memory (floor 1.3, cap 2.8).
      const nk = Math.min(2.8, Math.max(1.3, Math.min((VB_W - pad * 2) / bw, (VB_H - pad * 2) / bh)))
      autoFrame = false
      userMoved = true
      setTarget((minX + maxX) / 2, (minY + maxY) / 2, nk)
    }
    const applyReset = () => {
      if (autoFrame) return
      let minX = Infinity
      let minY = Infinity
      let maxX = -Infinity
      let maxY = -Infinity
      for (const nd of nodes) {
        if (nd.x < minX) minX = nd.x
        if (nd.y < minY) minY = nd.y
        if (nd.x > maxX) maxX = nd.x
        if (nd.y > maxY) maxY = nd.y
      }
      const bw = Math.max(1, maxX - minX)
      const bh = Math.max(1, maxY - minY)
      const pad = 80
      const nk = Math.min(3.2, Math.max(0.4, Math.min((VB_W - pad * 2) / bw, (VB_H - pad * 2) / bh)))
      autoFrame = true
      userMoved = false
      setTarget((minX + maxX) / 2, (minY + maxY) / 2, nk)
    }
    let lastCmdSeq = -1
    const toUser = (cx: number, cy: number) => {
      const p = new DOMPoint(cx, cy).matrixTransform(svg.getScreenCTM()!.inverse())
      return { x: p.x, y: p.y }
    }
    const toGraph = (cx: number, cy: number) => {
      const p = new DOMPoint(cx, cy).matrixTransform(view.getScreenCTM()!.inverse())
      return { x: p.x, y: p.y }
    }

    let alpha = 1
    const reheat = (v = 0.6) => {
      alpha = Math.max(alpha, v)
    }

    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault()
      userMoved = true
      viewAnimating = false
      const gp = toGraph(ev.clientX, ev.clientY)
      const su = toUser(ev.clientX, ev.clientY)
      k = Math.min(4, Math.max(0.35, k * Math.exp(-ev.deltaY * 0.0016)))
      tx = su.x - k * gp.x
      ty = su.y - k * gp.y
      applyView()
    }
    svg.addEventListener('wheel', onWheel, { passive: false })

    let panning = false
    let panStart = { x: 0, y: 0 }
    let panOrig = { x: 0, y: 0 }
    const onSvgDown = (ev: PointerEvent) => {
      if (ev.target !== svg && ev.target !== view && ev.target !== gEdges) return
      userMoved = true
      viewAnimating = false
      panning = true
      panStart = toUser(ev.clientX, ev.clientY)
      panOrig = { x: tx, y: ty }
      svg.style.cursor = 'grabbing'
      svg.setPointerCapture(ev.pointerId)
    }
    const onSvgMove = (ev: PointerEvent) => {
      if (!panning) return
      const u = toUser(ev.clientX, ev.clientY)
      tx = panOrig.x + (u.x - panStart.x)
      ty = panOrig.y + (u.y - panStart.y)
      applyView()
    }
    const onSvgUp = (ev: PointerEvent) => {
      panning = false
      svg.style.cursor = ''
      try {
        svg.releasePointerCapture(ev.pointerId)
      } catch {
        /* noop */
      }
    }
    svg.addEventListener('pointerdown', onSvgDown)
    svg.addEventListener('pointermove', onSvgMove)
    svg.addEventListener('pointerup', onSvgUp)

    // ---- node drag / hover / click ----
    let dragIdx = -1
    const setHighlight = (hi: number | null) => {
      nodes.forEach((_, i) => {
        const on = hi === null || i === hi || neighbors[hi].has(i)
        groupEls[i].style.opacity = on ? '1' : '0.16'
      })
      lineEls.forEach((l, ei) => {
        const e = edges[ei]
        const on = hi === null || e.a === hi || e.b === hi
        l.style.opacity = hi === null ? '' : on ? '0.9' : '0.04'
      })
    }
    const cleanups: Array<() => void> = []
    groupEls.forEach((g, i) => {
      const down = (ev: PointerEvent) => {
        ev.stopPropagation()
        userMoved = true
        viewAnimating = false
        dragIdx = i
        const gp = toGraph(ev.clientX, ev.clientY)
        nodes[i].fx = gp.x
        nodes[i].fy = gp.y
        g.style.cursor = 'grabbing'
        reheat(0.85)
        try {
          g.setPointerCapture(ev.pointerId)
        } catch {
          /* noop */
        }
      }
      const move = (ev: PointerEvent) => {
        if (dragIdx !== i) return
        const gp = toGraph(ev.clientX, ev.clientY)
        nodes[i].fx = gp.x
        nodes[i].fy = gp.y
        reheat(0.5)
      }
      const up = (ev: PointerEvent) => {
        if (dragIdx === i) {
          nodes[i].fx = null
          nodes[i].fy = null
          dragIdx = -1
        }
        g.style.cursor = 'grab'
        try {
          g.releasePointerCapture(ev.pointerId)
        } catch {
          /* noop */
        }
      }
      const enter = () => {
        if (dragIdx === -1) setHighlight(i)
      }
      const leave = () => {
        if (dragIdx === -1) setHighlight(null)
      }
      const click = (ev: Event) => {
        ev.stopPropagation()
        setDetail({
          label: nodes[i].label,
          type: nodes[i].type,
          node_sets: nodes[i].node_sets,
          degree: degree[i],
        })
      }
      g.addEventListener('pointerdown', down)
      g.addEventListener('pointermove', move)
      g.addEventListener('pointerup', up)
      g.addEventListener('pointerenter', enter)
      g.addEventListener('pointerleave', leave)
      g.addEventListener('click', click)
      cleanups.push(() => {
        g.removeEventListener('pointerdown', down)
        g.removeEventListener('pointermove', move)
        g.removeEventListener('pointerup', up)
        g.removeEventListener('pointerenter', enter)
        g.removeEventListener('pointerleave', leave)
        g.removeEventListener('click', click)
      })
    })

    // ---- physics ----
    const SPRING = 70
    const REPULSE = 1700
    const CENTER = 0.016
    const DAMP = 0.86
    const cx = VB_W / 2
    const cy = VB_H / 2
    const step = () => {
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          let dx = nodes[i].x - nodes[j].x
          let dy = nodes[i].y - nodes[j].y
          const d2 = dx * dx + dy * dy + 0.01
          const d = Math.sqrt(d2)
          const f = (REPULSE / d2) * alpha
          dx = (f * dx) / d
          dy = (f * dy) / d
          nodes[i].vx += dx
          nodes[i].vy += dy
          nodes[j].vx -= dx
          nodes[j].vy -= dy
        }
      }
      for (const e of edges) {
        const A = nodes[e.a]
        const B = nodes[e.b]
        const dx = B.x - A.x
        const dy = B.y - A.y
        const d = Math.sqrt(dx * dx + dy * dy) + 0.01
        const f = (d - SPRING) * 0.04 * alpha
        const fx = (f * dx) / d
        const fy = (f * dy) / d
        A.vx += fx
        A.vy += fy
        B.vx -= fx
        B.vy -= fy
      }
      for (let i = 0; i < n; i++) {
        const nd = nodes[i]
        if (nd.fx != null) {
          nd.x = nd.fx
          nd.y = nd.fy as number
          nd.vx = 0
          nd.vy = 0
          continue
        }
        nd.vx += (cx - nd.x) * CENTER * alpha
        nd.vy += (cy - nd.y) * CENTER * alpha
        nd.x += Math.max(-22, Math.min(22, nd.vx))
        nd.y += Math.max(-22, Math.min(22, nd.vy))
        nd.vx *= DAMP
        nd.vy *= DAMP
      }
      alpha *= 0.985
    }
    const paint = () => {
      for (let i = 0; i < n; i++) {
        groupEls[i].setAttribute('transform', `translate(${nodes[i].x} ${nodes[i].y})`)
      }
      for (let ei = 0; ei < edges.length; ei++) {
        const e = edges[ei]
        const l = lineEls[ei]
        l.setAttribute('x1', String(nodes[e.a].x))
        l.setAttribute('y1', String(nodes[e.a].y))
        l.setAttribute('x2', String(nodes[e.b].x))
        l.setAttribute('y2', String(nodes[e.b].y))
      }
    }

    // pre-settle so the first frame is not an explosion
    for (let w = 0; w < 140; w++) step()
    alpha = 0.28
    paint()
    fitView()

    let raf = 0
    const loop = () => {
      try {
        // pick up focus/reset commands posted by the verdict highlight
        if (cmdRef.current.seq !== lastCmdSeq) {
          lastCmdSeq = cmdRef.current.seq
          const focus = cmdRef.current.focus
          if (focus && focus.length) applyFocus(focus)
          else applyReset()
        }
        if (alpha > 0.004 || dragIdx !== -1) {
          step()
          paint()
          if (autoFrame && !userMoved && alpha > 0.03) fitView()
        }
        if (viewAnimating) {
          tx += (ttx - tx) * 0.12
          ty += (tty - ty) * 0.12
          k += (tk - k) * 0.12
          if (Math.abs(ttx - tx) < 0.4 && Math.abs(tty - ty) < 0.4 && Math.abs(tk - k) < 0.0015) {
            tx = ttx
            ty = tty
            k = tk
            viewAnimating = false
          }
          applyView()
        }
      } catch {
        /* keep the animation loop alive across a transient bad frame */
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)

    return () => {
      cancelAnimationFrame(raf)
      svg.removeEventListener('wheel', onWheel)
      svg.removeEventListener('pointerdown', onSvgDown)
      svg.removeEventListener('pointermove', onSvgMove)
      svg.removeEventListener('pointerup', onSvgUp)
      cleanups.forEach((fn) => fn())
      host.innerHTML = ''
      simRef.current = null
    }
  }, [snapshot])

  // Tie verdicts back to the graph: glow the cited memory nodes (matched by their
  // node-set key) and softly emphasise their one-hop entity neighbourhood. Runs
  // as a separate effect so it never rebuilds or disturbs the live physics.
  useEffect(() => {
    const sim = simRef.current
    if (!sim) return
    const keys = new Set((highlight ?? []).filter(Boolean))
    const anchors = new Set<number>()
    if (keys.size > 0) {
      sim.keyOf.forEach((k, i) => {
        if (k && keys.has(k)) anchors.add(i)
      })
    }
    const near = new Set<number>()
    anchors.forEach((i) => {
      sim.neighbors[i].forEach((j) => {
        if (!anchors.has(j)) near.add(j)
      })
    })
    sim.groupEls.forEach((g, i) => {
      g.classList.toggle('hl', anchors.has(i))
      g.classList.toggle('hl-near', !anchors.has(i) && near.has(i))
    })
    // Post a focus command on the shared bus; the live physics loop flies the view to
    // the cited memory's own nodes (they cluster tightly). The 1-hop neighbourhood only
    // glows — including it would widen the frame back to the whole graph.
    cmdRef.current = {
      seq: cmdRef.current.seq + 1,
      focus: anchors.size > 0 ? [...anchors] : null,
    }
  }, [highlight, snapshot])

  if (!snapshot || snapshot.nodes.length === 0) {
    return <div className="empty">No graph nodes yet — seed the memory to build the Cognee graph.</div>
  }

  return (
    <div className="graph-canvas">
      <div className="graph-stage" ref={hostRef} />
      <div className="graph-legend">
        <span className="gl-item"><i className="gl-dot" style={{ background: '#9aa4b2' }} />memory</span>
        <span className="gl-item"><i className="gl-dot" style={{ background: '#ff6b58' }} />entity</span>
        <span className="gl-item"><i className="gl-dot" style={{ background: '#e0b24e' }} />type</span>
        <span className="gl-item"><i className="gl-dot" style={{ background: '#46c98c' }} />tag</span>
        <span className="gl-item"><i className="gl-dot" style={{ background: '#5ad1c8' }} />summary</span>
      </div>
      <div className="graph-hint">scroll: zoom · drag a node · drag background: pan · click: details</div>
      {detail && (
        <div className="graph-detail">
          <button className="gd-close" onClick={() => setDetail(null)} aria-label="close">
            ×
          </button>
          <div className="gd-type">{detail.type}</div>
          <div className="gd-label">{detail.label}</div>
          {detail.node_sets.length > 0 && (
            <div className="chips">
              {detail.node_sets.map((s) => (
                <span key={s} className="chip">
                  {s}
                </span>
              ))}
            </div>
          )}
          <div className="gd-degree">
            {detail.degree} connection{detail.degree === 1 ? '' : 's'} in the graph
          </div>
        </div>
      )}
    </div>
  )
}
