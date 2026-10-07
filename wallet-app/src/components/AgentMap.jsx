import { useRef, useState } from 'react'

// A map of Dhaka that can be zoomed and dragged: every agent is a dot coloured by status, areas are labelled with the
// (estimated) number of upay users nearby, and recommended new-agent spots are green rings.
const W = 420
const H = 320
const BOX = { minLat: 23.69, maxLat: 23.89, minLng: 90.25, maxLng: 90.45 }
const COLOR = { red: '#c62828', yellow: '#e0a100', green: '#12805c' }
const MIN_ZOOM = 1
const MAX_ZOOM = 8

const project = (lat, lng) => ({
  x: ((lng - BOX.minLng) / (BOX.maxLng - BOX.minLng)) * W,
  y: H - ((lat - BOX.minLat) / (BOX.maxLat - BOX.minLat)) * H,
})
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

export default function AgentMap({ agents, selected, onSelect, spots = [] }) {
  const [view, setView] = useState({ zoom: 1, cx: W / 2, cy: H / 2 })
  const drag = useRef(null)
  const vw = W / view.zoom
  const vh = H / view.zoom
  const x0 = clamp(view.cx - vw / 2, 0, W - vw)
  const y0 = clamp(view.cy - vh / 2, 0, H - vh)

  const zoomBy = (factor, at) => setView((v) => {
    const zoom = clamp(v.zoom * factor, MIN_ZOOM, MAX_ZOOM)
    return { zoom, cx: at?.x ?? v.cx, cy: at?.y ?? v.cy }
  })
  const reset = () => setView({ zoom: 1, cx: W / 2, cy: H / 2 })

  // one label per area: where its agents are, and the estimated users nearby
  const areas = {}
  for (const a of agents) {
    const g = (areas[a.area] ??= { area: a.area, lat: 0, lng: 0, n: 0, users: 0 })
    g.lat += a.lat; g.lng += a.lng; g.n += 1; g.users += a.nearby_users_est ?? 0
  }

  const onPointerDown = (e) => { drag.current = { x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy, moved: false }; e.currentTarget.setPointerCapture?.(e.pointerId) }
  const onPointerMove = (e) => {
    const d = drag.current
    if (!d) return
    const rect = e.currentTarget.getBoundingClientRect()
    const dx = ((e.clientX - d.x) / rect.width) * vw
    const dy = ((e.clientY - d.y) / rect.height) * vh
    if (Math.abs(dx) + Math.abs(dy) > 1) d.moved = true
    setView((v) => ({ ...v, cx: d.cx - dx, cy: d.cy - dy }))
  }
  const onPointerUp = () => { drag.current = null }
  const onWheel = (e) => {
    e.preventDefault?.()
    const rect = e.currentTarget.getBoundingClientRect()
    const at = { x: x0 + ((e.clientX - rect.left) / rect.width) * vw, y: y0 + ((e.clientY - rect.top) / rect.height) * vh }
    zoomBy(e.deltaY < 0 ? 1.25 : 0.8, at)
  }
  const r = (base) => base / Math.sqrt(view.zoom)              // dots stay a readable size as the map is zoomed

  return (
    <div className="agent-map-wrap">
      <div className="map-controls" role="group" aria-label="Map zoom">
        <button type="button" onClick={() => zoomBy(1.5)} aria-label="Zoom in" disabled={view.zoom >= MAX_ZOOM}>+</button>
        <button type="button" onClick={() => zoomBy(1 / 1.5)} aria-label="Zoom out" disabled={view.zoom <= MIN_ZOOM}>−</button>
        <button type="button" onClick={reset} aria-label="Reset map" disabled={view.zoom === 1}>Reset</button>
        <small aria-live="polite">{view.zoom.toFixed(1)}×, drag to move, scroll to zoom</small>
      </div>
      <svg className="agent-map" viewBox={`${x0} ${y0} ${vw} ${vh}`} role="img" aria-label="Map of agents in Dhaka"
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={onPointerUp} onWheel={onWheel}
        style={{ touchAction: 'none', cursor: drag.current ? 'grabbing' : 'grab' }} data-testid="agent-map" data-zoom={view.zoom}>
        <rect x="0" y="0" width={W} height={H} rx="12" className="map-bg" />
        {Object.values(areas).map((g) => {
          const { x, y } = project(g.lat / g.n, g.lng / g.n)
          return (
            <text key={g.area} x={x} y={y - r(10)} textAnchor="middle" className="map-label" fontSize={r(8)}>
              {g.area}{g.users ? ` · ~${Math.round(g.users / 100) / 10}k users` : ''}
            </text>
          )
        })}
        {spots.map((s, i) => {
          const { x, y } = project(s.lat, s.lng)
          return (
            <g key={i} className="spot">
              <circle cx={x} cy={y} r={r(16)} />
              <text x={x} y={y + r(4)} textAnchor="middle" fontSize={r(14)}>+</text>
              <title>{`Add an agent near ${s.area}`}</title>
            </g>
          )
        })}
        {agents.map((a) => {
          const { x, y } = project(a.lat, a.lng)
          return (
            <circle key={a.agent_id} cx={x} cy={y} r={r(selected === a.agent_id ? 7 : 4.5)} fill={COLOR[a.status] ?? '#8a93a6'}
              className={`dot ${selected === a.agent_id ? 'on' : ''}`} onClick={() => { if (!drag.current?.moved) onSelect?.(a.agent_id) }} data-testid={`dot-${a.agent_id}`}>
              <title>{`${a.name} · ${a.area}${a.nearby_users_est ? ` · about ${a.nearby_users_est.toLocaleString('en')} upay users nearby (estimate)` : ''}`}</title>
            </circle>
          )
        })}
      </svg>
    </div>
  )
}
