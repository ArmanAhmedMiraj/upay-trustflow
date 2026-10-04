// A simple map of Dhaka: every agent is a dot coloured by status; recommended new-agent spots are green rings.
const W = 420
const H = 320
const BOX = { minLat: 23.69, maxLat: 23.89, minLng: 90.25, maxLng: 90.45 }
const COLOR = { red: '#c62828', yellow: '#e0a100', green: '#12805c' }

const project = (lat, lng) => ({
  x: ((lng - BOX.minLng) / (BOX.maxLng - BOX.minLng)) * W,
  y: H - ((lat - BOX.minLat) / (BOX.maxLat - BOX.minLat)) * H,
})

export default function AgentMap({ agents, selected, onSelect, spots = [] }) {
  return (
    <svg className="agent-map" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Map of agents in Dhaka">
      <rect width={W} height={H} rx="12" className="map-bg" />
      {spots.map((s, i) => {
        const { x, y } = project(s.lat, s.lng)
        return (
          <g key={i} className="spot">
            <circle cx={x} cy={y} r="16" />
            <text x={x} y={y + 4} textAnchor="middle">+</text>
            <title>{`Add an agent near ${s.area}`}</title>
          </g>
        )
      })}
      {agents.map((a) => {
        const { x, y } = project(a.lat, a.lng)
        return (
          <circle key={a.agent_id} cx={x} cy={y} r={selected === a.agent_id ? 7 : 4.5} fill={COLOR[a.status] ?? '#8a93a6'}
            className={`dot ${selected === a.agent_id ? 'on' : ''}`} onClick={() => onSelect?.(a.agent_id)} data-testid={`dot-${a.agent_id}`}>
            <title>{`${a.name} · ${a.area}`}</title>
          </circle>
        )
      })}
    </svg>
  )
}
