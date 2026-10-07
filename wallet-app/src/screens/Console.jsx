import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { errorText, makeT } from '../i18n.js'
import { formatPhone, formatRemaining, formatTaka, formatWhen, parseApiTime } from '../format.js'
import AgentsTab from './AgentsTab.jsx'
import RiskLab from './RiskLab.jsx'

export const SCAM_NAMES = {
  return_by_mistake: "Return money 'sent by mistake'",
  fake_officer: 'Fake upay / bank / police officer',
  prize_fee: 'Prize or loan fee',
  emergency_relative: 'Relative emergency (new number)',
  advance_payment: 'Advance payment (shop, job, visa)',
}
const OUTCOME_NAMES = {
  walked_away: ['Saw the warning and did not send', 'good'],
  cancelled: ['Held, then cancelled by the customer', 'good'],
  rejected: ['Held, then stopped by an analyst', 'good'],
  on_hold: ['Still on hold', 'wait'],
  released_after_hold: ['Released after the hold ended', 'bad'],
  sent_after_warning: ['Sent anyway after the warning', 'bad'],
}
const pct = (x, digits = 0) => `${(x * 100).toFixed(digits)}%`
const t = makeT('en')                       // the console is in English; errors use the same plain sentences as the app
const words = { today: 'Today', yesterday: 'Yesterday' }

/** The fraud analyst's desktop view: cases waiting for a decision, and the impact dashboard. */
export default function Console({ user, onLogout, onDemoReset }) {
  const [tab, setTab] = useState('cases')
  const [confirmReset, setConfirmReset] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [error, setError] = useState('')

  async function reset() {
    if (!confirmReset) return setConfirmReset(true)
    setResetting(true)
    try {
      await api.resetDemo()
      onDemoReset()
    } catch (e) {
      setError(errorText(e, t))
      setResetting(false)
      setConfirmReset(false)
    }
  }

  return (
    <div className="console">
      <header className="console-head">
        <div>
          <h1>upay Shield · Analyst console</h1>
          <small>Signed in as {user.name}</small>
        </div>
        <nav className="console-tabs" role="tablist">
          <button role="tab" aria-selected={tab === 'cases'} className={tab === 'cases' ? 'on' : ''} onClick={() => setTab('cases')}>Cases</button>
          <button role="tab" aria-selected={tab === 'impact'} className={tab === 'impact' ? 'on' : ''} onClick={() => setTab('impact')}>Impact</button>
          <button role="tab" aria-selected={tab === 'agents'} className={tab === 'agents' ? 'on' : ''} onClick={() => setTab('agents')}>Agents</button>
          <button role="tab" aria-selected={tab === 'lab'} className={tab === 'lab' ? 'on' : ''} onClick={() => setTab('lab')}>Risk Lab</button>
        </nav>
        <div className="console-actions">
          <button className="lang dark" onClick={reset} disabled={resetting}>
            {resetting ? 'Resetting…' : confirmReset ? 'Click again to wipe and reset' : 'Reset demo'}
          </button>
          <button className="lang dark" onClick={onLogout}>Log out</button>
        </div>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {tab === 'cases' ? <Cases /> : tab === 'impact' ? <Impact /> : tab === 'lab' ? <RiskLab /> : <AgentsTab />}
    </div>
  )
}

// ------------------------------------------------------------------ cases
function Cases() {
  const [status, setStatus] = useState('held')
  const [cases, setCases] = useState(null)
  const [error, setError] = useState('')
  const [notes, setNotes] = useState({})
  const [busy, setBusy] = useState(null)
  const [actionError, setActionError] = useState('')
  const [now, setNow] = useState(Date.now())

  const load = useCallback(async () => {
    try {
      setCases((await api.analystCases(status, 100)).cases)
      setError('')
    } catch (e) {
      setError(errorText(e, t))
    }
  }, [status])

  useEffect(() => {
    load()
    const refresh = setInterval(load, 5000)       // new cases appear by themselves while presenting
    const clock = setInterval(() => setNow(Date.now()), 1000)
    return () => { clearInterval(refresh); clearInterval(clock) }
  }, [load])

  async function decide(id, approve) {
    setBusy(id)
    setActionError('')
    try {
      await (approve ? api.approve(id, notes[id]) : api.reject(id, notes[id]))
      await load()
    } catch (e) {
      setActionError(errorText(e, t))          // kept on screen even though the list reloads
      load()
    } finally {
      setBusy(null)
    }
  }

  return (
    <section>
      <div className="toolbar">
        <h2>{status === 'held' ? 'Waiting for your decision' : 'All flagged transfers'}</h2>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Show">
          <option value="held">Waiting for review</option>
          <option value="all">All</option>
        </select>
        <button className="lang dark" onClick={load}>↻ Refresh</button>
      </div>
      {(actionError || error) && <p className="error" role="alert">{actionError || error}</p>}
      {cases === null && !error && <p className="muted">Loading…</p>}
      {cases && cases.length === 0 && <p className="muted empty">No cases right now. Held transfers appear here automatically.</p>}
      <div className="cases">
        {(cases ?? []).map((c) => {
          const left = c.release_at ? parseApiTime(c.release_at).getTime() - now : 0
          return (
            <article key={c.id} className={`case ${c.risk_tier}`}>
              <header>
                <strong>Case #{c.id}</strong>
                <span className={`badge ${c.status}`}>{c.status === 'held' ? 'Waiting' : c.status}</span>
                <small>{formatWhen(c.created_at, 'en', new Date(), words)}</small>
                {c.status === 'held' && <small className="timer">releases automatically in {formatRemaining(left)}</small>}
              </header>
              <div className="case-body">
                <div className="case-parties">
                  <div><small>From</small><strong>{c.sender.name}</strong><span>{formatPhone(c.sender.phone)}</span></div>
                  <div className="arrow" aria-hidden="true">→</div>
                  <div><small>To</small><strong>{c.recipient.name}</strong><span>{formatPhone(c.recipient.phone)}</span></div>
                  <div className="case-amount">{formatTaka(c.amount)}</div>
                </div>
                <div className="case-risk">
                  <div className="meter-top"><span>Security risk</span><strong>{c.risk_pct}%</strong></div>
                  <div className={`meter ${c.risk_tier}`}><div className="meter-bar"><div className="meter-fill" style={{ width: `${c.risk_pct}%` }} /></div></div>
                  <small>{SCAM_NAMES[c.scam_type] ?? 'Pattern not classified'}</small>
                </div>
              </div>
              <ul className="case-reasons">
                {c.reasons.slice(0, 5).map((r, i) => (
                  <li key={i}><span className={`tag ${r.source}`}>{r.source === 'rule' ? 'Verified fact' : 'Pattern'}</span> {r.text}</li>
                ))}
              </ul>
              {c.status === 'held' ? (
                <div className="case-actions">
                  <input placeholder="Note (optional)" value={notes[c.id] ?? ''} aria-label={`Note for case ${c.id}`}
                    onChange={(e) => setNotes((n) => ({ ...n, [c.id]: e.target.value }))} />
                  <button className="primary secondary" disabled={busy === c.id} onClick={() => decide(c.id, true)}>Approve: pay the recipient now</button>
                  <button className="primary danger" disabled={busy === c.id} onClick={() => decide(c.id, false)}>Reject: refund the customer</button>
                </div>
              ) : c.review_note ? <p className="muted">Note: {c.review_note}</p> : null}
            </article>
          )
        })}
      </div>
    </section>
  )
}

// ------------------------------------------------------------------ impact
function Impact() {
  const [hours, setHours] = useState(168)
  const [data, setData] = useState(null)
  const [report, setReport] = useState(undefined)
  const [error, setError] = useState('')

  useEffect(() => {
    api.modelReport().then((r) => setReport(r.report)).catch(() => setReport(null))
  }, [])
  useEffect(() => {
    let alive = true
    const load = () => api.impact(hours).then((r) => alive && (setData(r), setError(''))).catch((e) => alive && setError(errorText(e, t)))
    load()
    const id = setInterval(load, 5000)
    return () => { alive = false; clearInterval(id) }
  }, [hours])

  if (error) return <p className="error" role="alert">{error}</p>
  if (!data) return <p className="muted">Loading…</p>
  const flagged = data.flagged
  return (
    <section className="impact">
      <div className="toolbar">
        <h2>What Shield did, from real activity in this wallet</h2>
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Period">
          <option value={24}>Last 24 hours</option>
          <option value={168}>Last 7 days</option>
          <option value={24 * 30}>Last 30 days</option>
        </select>
      </div>

      <div className="kpis">
        <Kpi label="Transfers checked" value={data.checks.toLocaleString('en')} />
        <Kpi label="Interrupted (warning or hold)" value={pct(data.friction_rate, 1)} note={`${flagged} of ${data.checks}`} />
        <Kpi label="Kept back from flagged wallets" value={formatTaka(data.kept_back_bdt)} tone="good" note="not sent, cancelled or rejected" />
        <Kpi label="Customers who heeded the warning" value={flagged ? pct(data.heeded_rate) : '–'} tone="good" note={`${data.heeded} of ${flagged} flagged`} />
        <Kpi label="On hold right now" value={formatTaka(data.on_hold_bdt)} note={`${data.open_cases} case(s)`} tone="wait" />
        <Kpi label="Went through after a warning" value={formatTaka(data.released_bdt)} tone="bad" note="released or sent anyway" />
        <Kpi label="Numbers reported by customers" value={String(data.reports)} note={`${data.reported_wallets} wallet(s)`} />
        <Kpi label="Shield available" value={pct(data.shield_available_rate, 1)} note="the wallet never stops if it is down" />
      </div>

      <div className="panels">
        <div className="panel">
          <h3>What happened to flagged transfers</h3>
          {flagged === 0 && <p className="muted">No flagged transfers in this period yet.</p>}
          {Object.entries(OUTCOME_NAMES).map(([key, [label, tone]]) => {
            const o = data.outcomes[key]
            return (
              <div className="bar-row" key={key}>
                <span>{label}</span>
                <div className="bar"><div className={`bar-fill ${tone}`} style={{ width: `${flagged ? (o.count / flagged) * 100 : 0}%` }} /></div>
                <strong>{o.count} · {formatTaka(o.bdt)}</strong>
              </div>
            )
          })}
        </div>
        <div className="panel">
          <h3>How risky were the checks?</h3>
          {[['low', 'Low'], ['note', 'Check carefully'], ['high', 'High'], ['very_high', 'Very high']].map(([k, label]) => (
            <div className="bar-row" key={k}>
              <span>{label}</span>
              <div className="bar"><div className={`bar-fill tier-${k}`} style={{ width: `${data.checks ? (data.tiers[k] / data.checks) * 100 : 0}%` }} /></div>
              <strong>{data.tiers[k]}</strong>
            </div>
          ))}
        </div>
      </div>

      {report && <ModelReport report={report} />}
      {report === null && <p className="muted">The offline evaluation file was not found.</p>}
    </section>
  )
}

function Kpi({ label, value, note, tone = '' }) {
  return (
    <div className={`kpi ${tone}`}>
      <small>{label}</small>
      <strong>{value}</strong>
      {note && <span>{note}</span>}
    </div>
  )
}

function ModelReport({ report }) {
  const r = report
  return (
    <div className="panel wide-panel">
      <h3>Offline evaluation: synthetic test period where the truth is known</h3>
      <p className="muted">
        {r.test_transfers.toLocaleString('en')} unseen transfers, {r.test_fraud.toLocaleString('en')} of them fraud. These numbers prove the method,
        not performance on real upay data.
      </p>
      <div className="kpis small">
        <Kpi label="Fraud caught (by count)" value={pct(r.fraud_caught_pct, 1)} tone="good" />
        <Kpi label="Fraud caught (by ৳ value)" value={pct(r.fraud_value_caught_pct, 1)} tone="good" />
        <Kpi label="Genuine transfers disturbed" value={pct(r.genuine_disturbed_pct, 2)} />
        <Kpi label="Warnings that were real fraud" value={pct(r.precision, 0)} />
      </div>
      <div className="panels">
        <div>
          <h4>AI against simple rules (fraud caught while disturbing 2% of genuine transfers)</h4>
          {[['rules_only_baseline', 'Simple rules'], ['logistic_regression_baseline', 'Logistic regression'], ['lightgbm_raw', 'LightGBM'], ['full_system_with_rules', 'Full system']].map(([k, label]) => (
            <div className="bar-row" key={k}>
              <span>{label}</span>
              <div className="bar"><div className={`bar-fill ${k === 'rules_only_baseline' ? 'bad' : 'good'}`} style={{ width: pct(r.ranking[k].recall_at_2pct_friction) }} /></div>
              <strong>{pct(r.ranking[k].recall_at_2pct_friction)}</strong>
            </div>
          ))}
          <h4>Fraud caught by scam type</h4>
          {Object.entries(r.by_scam_type).map(([k, v]) => (
            <div className="bar-row" key={k}>
              <span>{SCAM_NAMES[k] ?? k}</span>
              <div className="bar"><div className="bar-fill good" style={{ width: pct(v) }} /></div>
              <strong>{pct(v)}</strong>
            </div>
          ))}
        </div>
        <div>
          <h4>Money impact if customers heed the warning (test period)</h4>
          <table className="plain">
            <thead><tr><th>Customers who heed</th><th>Fraud ৳ stopped</th><th>Net benefit</th></tr></thead>
            <tbody>
              {Object.entries(r.impact_by_heeding_rate).map(([rate, v]) => (
                <tr key={rate}><td>{pct(Number(rate))}</td><td>{formatTaka(Math.round(v.fraud_bdt_stopped))}</td><td>{formatTaka(Math.round(v.net_benefit_bdt))}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted">The share of customers who heed a warning is an assumption, so three values are shown. The live figure above is measured.</p>
          <h4>If fraudsters adapt (fraud caught at the safety-check level)</h4>
          {Object.entries(r.evasion).map(([k, v]) => (
            <div className="bar-row" key={k}>
              <span>{k.replaceAll('_', ' ')}</span>
              <div className="bar"><div className={`bar-fill ${v > 0.5 ? 'good' : 'bad'}`} style={{ width: pct(v) }} /></div>
              <strong>{pct(v)}</strong>
            </div>
          ))}
          <p className="muted">Scoring takes about {r.latency_ms} ms per transfer.</p>
        </div>
      </div>
    </div>
  )
}
