// Two small charts for one agent: the cash customers may take out hour by hour, and the agent's cash balance over 48 hours.
const W = 560
const PAD = { l: 44, r: 8, t: 8, b: 22 }

function scale(values, lo, hi, size) {
  const span = hi - lo || 1
  return (v) => size - ((v - lo) / span) * size
}

const k = (n) => (Math.abs(n) >= 1000 ? `${Math.round(n / 1000)}k` : String(Math.round(n)))

export default function ForecastChart({ data, labels }) {
  const n = data.hours.length
  const innerW = W - PAD.l - PAD.r
  const step = innerW / n
  const x = (i) => PAD.l + i * step
  const label = (i) => {
    const h = data.hours[i]
    return h === 0 ? '12am' : h === 12 ? '12pm' : h < 12 ? `${h}am` : `${h - 12}pm`
  }

  // top chart: demand
  const H1 = 130
  const maxDemand = Math.max(...data.p90_out, 1)
  const y1 = scale(null, 0, maxDemand * 1.1, H1 - PAD.t - PAD.b)
  // bottom chart: cash path
  const H2 = 130
  const lo = Math.min(0, ...data.cash_path_plan)
  const hi = Math.max(data.cash_now, ...data.cash_path_plan) * 1.05
  const y2 = scale(null, lo, hi, H2 - PAD.t - PAD.b)
  const path = data.cash_path_plan.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i) + step / 2},${PAD.t + y2(v)}`).join(' ')
  const p90 = data.p90_out.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i) + step / 2},${PAD.t + y1(v)}`).join(' ')
  const zeroY = PAD.t + y2(0)
  const ticks = [0, 6, 12, 18, 24, 30, 36, 42].filter((i) => i < n)

  return (
    <div className="forecast">
      <h4>{labels.demand}</h4>
      <svg viewBox={`0 0 ${W} ${H1}`} role="img" aria-label={labels.demand}>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={PAD.l} x2={W - PAD.r} y1={PAD.t + y1(maxDemand * 1.1 * f)} y2={PAD.t + y1(maxDemand * 1.1 * f)} className="grid" />
            <text x={PAD.l - 4} y={PAD.t + y1(maxDemand * 1.1 * f) + 3} textAnchor="end" className="axis">{k(maxDemand * 1.1 * f)}</text>
          </g>
        ))}
        {data.p50_out.map((v, i) => (
          <rect key={i} x={x(i) + 1} width={Math.max(step - 2, 1)} y={PAD.t + y1(v)} height={H1 - PAD.t - PAD.b - y1(v)} className="bar-normal" />
        ))}
        <path d={p90} className="line-busy" fill="none" />
        {ticks.map((i) => <text key={i} x={x(i)} y={H1 - 6} className="axis">{label(i)}</text>)}
      </svg>
      <p className="legend"><span className="sw normal" /> {labels.normal} <span className="sw busy" /> {labels.busy}</p>

      <h4>{labels.cash}</h4>
      <svg viewBox={`0 0 ${W} ${H2}`} role="img" aria-label={labels.cash}>
        {lo < 0 && <rect x={PAD.l} y={zeroY} width={innerW} height={H2 - PAD.b - zeroY} className="below-zero" />}
        {[lo, (lo + hi) / 2, hi].map((v, i) => (
          <g key={i}>
            <line x1={PAD.l} x2={W - PAD.r} y1={PAD.t + y2(v)} y2={PAD.t + y2(v)} className="grid" />
            <text x={PAD.l - 4} y={PAD.t + y2(v) + 3} textAnchor="end" className="axis">{k(v)}</text>
          </g>
        ))}
        <line x1={PAD.l} x2={W - PAD.r} y1={zeroY} y2={zeroY} className="zero" />
        <path d={path} className="line-cash" fill="none" />
        {ticks.map((i) => <text key={i} x={x(i)} y={H2 - 6} className="axis">{label(i)}</text>)}
      </svg>
    </div>
  )
}
