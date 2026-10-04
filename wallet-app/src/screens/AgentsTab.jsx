import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { errorText, makeT } from '../i18n.js'
import { formatTaka, formatWhen } from '../format.js'
import AgentMap from '../components/AgentMap.jsx'
import ForecastChart from '../components/ForecastChart.jsx'

const t = makeT('en')
const SCENARIOS = [['normal', 'A normal day'], ['payday', 'Payday week'], ['festival', 'Festival rush']]
const DOT = { red: 'Will run short', yellow: 'Could run short', green: 'Fine' }
const pct = (x, d = 1) => `${(x * 100).toFixed(d)}%`

/** Operations view of Module 2: who needs cash, when, how much, and where another agent would help. */
export default function AgentsTab() {
  const [scenario, setScenario] = useState('festival')
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [coverage, setCoverage] = useState(null)
  const [report, setReport] = useState(null)
  const [requests, setRequests] = useState([])
  const [showAll, setShowAll] = useState(false)
  const [error, setError] = useState('')

  const loadRequests = useCallback(() => api.opsRefillRequests().then((r) => setRequests(r.requests)).catch(() => {}), [])

  useEffect(() => {
    api.opsCoverage().then(setCoverage).catch((e) => setError(errorText(e, t)))
    api.opsLiquidityReport().then(setReport).catch(() => {})
    loadRequests()
    const id = setInterval(loadRequests, 5000)
    return () => clearInterval(id)
  }, [loadRequests])

  useEffect(() => {
    setData(null)
    setError('')
    api.opsAgents(scenario).then((r) => { setData(r); setSelected((s) => s ?? r.agents[0]?.agent_id ?? null) }).catch((e) => setError(errorText(e, t)))
  }, [scenario])

  useEffect(() => {
    if (selected === null) return
    api.opsAgent(selected, scenario).then(setDetail).catch((e) => setError(errorText(e, t)))
  }, [selected, scenario])

  async function dispatch(id) {
    try {
      await api.dispatchRefill(id)
      loadRequests()
    } catch (e) {
      setError(errorText(e, t))
      loadRequests()
    }
  }

  const rows = data ? (showAll ? data.agents : data.agents.slice(0, 10)) : []
  const open = requests.filter((r) => r.status === 'open')

  return (
    <section className="agents-tab">
      <div className="toolbar">
        <h2>Agent cash: how much, when, and where</h2>
        <div className="scenario-switch" role="group" aria-label="Day">
          {SCENARIOS.map(([key, label]) => (
            <button key={key} className={scenario === key ? 'on' : ''} aria-pressed={scenario === key} onClick={() => setScenario(key)}>{label}</button>
          ))}
        </div>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {!data && !error && <p className="muted">Loading the forecast…</p>}

      {data && (
        <>
          <p className="muted calendar">
            {data.calendar.weekday}, day {data.calendar.day_of_month} of the month
            {data.calendar.payday && ' · payday window'}{data.calendar.festival_rush && ' · festival rush'}
            {!data.calendar.festival_rush && data.calendar.days_to_festival < 10 && ` · festival in ${data.calendar.days_to_festival} days`}
          </p>
          <div className="kpis">
            <div className="kpi bad"><small>Will run short within 24 hours</small><strong>{data.counts.red}</strong><span>of {data.agents.length} agents</span></div>
            <div className="kpi wait"><small>Could run short if busier</small><strong>{data.counts.yellow}</strong><span>watch list</span></div>
            <div className="kpi good"><small>Enough cash</small><strong>{data.counts.green}</strong><span>no action needed</span></div>
            <div className="kpi"><small>Cash to deliver today</small><strong>{formatTaka(data.total_refill_cash)}</strong><span>to avoid turning customers away</span></div>
          </div>

          <div className="panels agents-grid">
            <div className="panel">
              <h3>Map of agents</h3>
              <AgentMap agents={data.agents} selected={selected} onSelect={setSelected} spots={coverage?.recommendations ?? []} />
              <p className="legend"><span className="dot-key red" /> will run short <span className="dot-key yellow" /> could <span className="dot-key green" /> fine <span className="spot-key">+</span> add an agent here</p>
            </div>
            <div className="panel">
              <h3>Who needs cash first</h3>
              <table className="plain agents-table">
                <thead><tr><th>Agent</th><th>Area</th><th>Cash now</th><th>Runs out</th><th>Add</th></tr></thead>
                <tbody>
                  {rows.map((a) => (
                    <tr key={a.agent_id} className={selected === a.agent_id ? 'on' : ''} onClick={() => setSelected(a.agent_id)} tabIndex={0}
                      onKeyDown={(e) => e.key === 'Enter' && setSelected(a.agent_id)}>
                      <td><span className={`dot-key ${a.status}`} title={DOT[a.status]} /> {a.name}</td>
                      <td>{a.area}</td>
                      <td>{formatTaka(a.cash_now)}</td>
                      <td>{a.runout_label ?? '–'}</td>
                      <td><strong>{a.refill_cash ? formatTaka(a.refill_cash) : '–'}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.agents.length > 10 && <button className="link small" onClick={() => setShowAll((v) => !v)}>{showAll ? 'Show fewer' : `Show all ${data.agents.length}`}</button>}
            </div>
          </div>

          {detail && (
            <div className="panel wide-panel agent-detail">
              <h3>{detail.name} · {detail.area} <span className={`badge status-${detail.status}`}>{DOT[detail.status]}</span></h3>
              <div className="kpis small">
                <div className="kpi"><small>Cash on hand</small><strong>{formatTaka(detail.cash_now)}</strong></div>
                <div className="kpi"><small>Needed, next 24 hours</small><strong>{formatTaka(detail.need_cash_24h)}</strong></div>
                <div className="kpi bad"><small>Cash runs out</small><strong>{detail.runout_label ?? 'Not expected'}</strong></div>
                <div className="kpi good"><small>Recommended top-up</small><strong>{formatTaka(detail.refill_cash)}</strong></div>
              </div>
              <ForecastChart data={detail} labels={{ demand: 'Cash customers may take out, hour by hour', normal: 'Normal day', busy: 'Busy-day line', cash: 'Cash balance over 48 hours if nothing is added' }} />
              <div className="briefings">
                <div><small>Message to the agent (English)</small><p>{detail.briefing_en}</p></div>
                <div><small>এজেন্টকে বার্তা (বাংলা)</small><p lang="bn">{detail.briefing_bn}</p></div>
              </div>
            </div>
          )}

          <div className="panels">
            <div className="panel">
              <h3>Refill requests from agents</h3>
              {requests.length === 0 && <p className="muted">No requests yet. Agents send them from their phone.</p>}
              {requests.slice(0, 6).map((r) => (
                <div key={r.id} className="request">
                  <div><strong>{r.agent?.name}</strong> asks for {formatTaka(r.cash_bdt)}{r.needed_by && <small> · needed by {r.needed_by}</small>}</div>
                  {r.status === 'open'
                    ? <button className="primary secondary" onClick={() => dispatch(r.id)}>Dispatch</button>
                    : <span className="badge status-green">Dispatched</span>}
                </div>
              ))}
              {open.length > 0 && <small className="muted">{open.length} waiting</small>}
            </div>
            <div className="panel">
              <h3>Where another agent would help most</h3>
              {(coverage?.recommendations ?? []).map((c) => (
                <div key={c.area} className="spot-row">
                  <strong>{c.area}</strong> <span className="badge">{c.times_city_median}× busier than typical</span>
                  <p>{c.reason}</p>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
      {report && <Evidence report={report} />}
    </section>
  )
}

function Evidence({ report }) {
  const q = report.quality
  const p = report.policy
  const row = (key, label) => {
    const s = p[key]
    return { label, missed: s.unmet_bdt / s.demand_bdt, cash: s.avg_cash_held, topups: s.topups_bdt, types: s.by_day_type }
  }
  const rows = [row('guess_from_last_week_plus_20pct', 'Refill from last week + 20%'), row('guess_with_same_average_cash', 'Refill from last week, same average cash'), row('forecast_driven', 'Refill from the forecast')]
  const dayTypes = [['normal', 'Normal days'], ['payday', 'Payday'], ['festival', 'Festival rush']]
  return (
    <div className="panel wide-panel evidence">
      <h3>Does the forecast work? Tested on days the model never saw</h3>
      <p className="muted">Simulated agents; days {report.test_days[0]} to {report.test_days[1]}. These results prove the method, not performance on real upay data.</p>
      <div className="kpis small">
        <div className="kpi good"><small>Busy-day line covered</small><strong>{pct(q.p90_coverage_cash_out)}</strong><span>of hours (target 90%)</span></div>
        <div className="kpi good"><small>Rush-hour coverage</small><strong>{pct(q.p90_coverage_festival_hours)}</strong><span>during the festival</span></div>
        <div className="kpi"><small>Forecast error</small><strong>{Math.round((1 - q.pinball_p50_model / q.pinball_p50_same_hour_last_week) * 100)}% lower</strong><span>than copying last week</span></div>
        <div className="kpi"><small>Agents simulated</small><strong>{report.agents}</strong><span>across 12 areas of Dhaka</span></div>
      </div>
      <table className="plain">
        <thead><tr><th>Refill method</th><th>Customers turned away</th><th>Average cash on hand</th>{dayTypes.map(([, l]) => <th key={l}>{l}</th>)}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <td>{r.label}</td><td><strong>{pct(r.missed, 2)}</strong></td><td>{formatTaka(Math.round(r.cash))}</td>
              {dayTypes.map(([k]) => <td key={k}>{pct(r.types[k].missed_share)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        The gain comes from rush days: copying last week works on quiet days but fails when demand jumps. The cost is honest too: the forecast method moves about
        {' '}{Math.round((p.forecast_driven.topups_bdt / p.guess_from_last_week_plus_20pct.topups_bdt - 1) * 100)}% more cash through refills.
        Safety setting: plan {Math.round(p.plan_mix * 100)}% of the way from a normal day to a busy day.
      </p>
      <h4>The safety dial: more cash on hand, fewer customers turned away</h4>
      {p.tradeoff.map((t2) => (
        <div className="bar-row" key={t2.mix}>
          <span>{Math.round(t2.mix * 100)}% of the way to a busy day</span>
          <div className="bar"><div className="bar-fill bad" style={{ width: `${Math.min(100, t2.missed_share * 1000)}%` }} /></div>
          <strong>{pct(t2.missed_share, 2)} missed · {formatTaka(Math.round(t2.avg_cash_held))} cash</strong>
        </div>
      ))}
    </div>
  )
}
