import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { errorText, makeT } from '../i18n.js'
import { formatPhone, formatTaka } from '../format.js'

const t = makeT('en')

const SIDES = {
  sender: 'Sender behaviour',
  recipient: 'Recipient account',
  pair: 'Sender-recipient link',
}
const TIERS = {
  low: ['Low', 'Allow the transfer'],
  note: ['Note', 'Allow, with a gentle note'],
  high: ['High', 'Ask safety-check questions'],
  very_high: ['Very high', 'Hold for 30 minutes'],
}
const EMPTY_FILTERS = { sender: '', recipient: '', name: '', since: '', until: '' }
const pts = (v) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}`
const dhaka = (iso) => new Date(`${iso}Z`).toLocaleString('en-GB', {
  timeZone: 'Asia/Dhaka', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
})

/**
 * The analyst's Risk Lab: a log of REAL transfers. Each one is scored by the graded-risk model at the moment it happens;
 * nothing is pre-filled. Pick a transfer to see how every signal moved its score.
 */
export default function RiskLab() {
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [options, setOptions] = useState({ senders: [], recipients: [], total: 0 })
  const [entries, setEntries] = useState(null)
  const [selected, setSelected] = useState(null)
  const [muted, setMuted] = useState([])
  const [result, setResult] = useState(null)
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [explainError, setExplainError] = useState('')
  const [showAll, setShowAll] = useState(false)
  const filtersRef = useRef(filters)
  const ticket = useRef(0)
  filtersRef.current = filters

  const load = useCallback(() => {
    const f = filtersRef.current
    const params = new URLSearchParams()
    Object.entries(f).forEach(([k, v]) => v && params.set(k, v))
    Promise.all([api.labTransactions(params.toString()), api.labFilters()])
      .then(([list, opts]) => { setEntries(list.entries); setOptions(opts); setError('') })
      .catch((e) => setError(errorText(e, t)))
  }, [])

  useEffect(() => { load() }, [load, filters])
  useEffect(() => {                                   // new transfers show up by themselves
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [load])
  useEffect(() => { api.labReport().then(setReport).catch(() => {}) }, [])

  useEffect(() => {
    if (!selected) return undefined
    const mine = ++ticket.current
    api.labExplain(selected.id, { mute_sides: muted })
      .then((r) => { if (mine === ticket.current) { setResult(r); setExplainError('') } })
      .catch((e) => { if (mine === ticket.current) { setResult(null); setExplainError(errorText(e, t)) } })
    return () => { ticket.current += 1 }
  }, [selected, muted])

  const setFilter = (k, v) => setFilters((f) => ({ ...f, [k]: v }))
  const choose = (entry) => { setSelected(entry); setMuted([]); setResult(null); setExplainError('') }
  const toggleSide = (s) => setMuted((m) => (m.includes(s) ? m.filter((x) => x !== s) : [...m, s]))
  const filtered = Object.values(filters).some(Boolean)
  const hasFilterRows = useMemo(() => entries !== null && entries.length > 0, [entries])

  return (
    <section className="lab">
      <div className="lab-intro">
        <h2>Risk Lab: every real transfer, scored</h2>
        <p>
          Each transfer made in the wallet is scored by the AI the moment it happens and listed here. Nothing is pre-filled:
          until someone sends money, this list is empty. Pick a transfer to see how each of the 31 signals pushed its risk.
        </p>
      </div>

      <form className="lab-panel lab-filters" onSubmit={(e) => e.preventDefault()} aria-label="Filter transfers">
        <label>Sender number
          <select value={filters.sender} onChange={(e) => setFilter('sender', e.target.value)}>
            <option value="">All senders</option>
            {options.senders.map((o) => <option key={o.phone} value={o.phone}>{formatPhone(o.phone)} · {o.name}</option>)}
          </select>
        </label>
        <label>Recipient number
          <select value={filters.recipient} onChange={(e) => setFilter('recipient', e.target.value)}>
            <option value="">All recipients</option>
            {options.recipients.map((o) => <option key={o.phone} value={o.phone}>{formatPhone(o.phone)} · {o.name}</option>)}
          </select>
        </label>
        <label>Registered name
          <input type="search" value={filters.name} onChange={(e) => setFilter('name', e.target.value)} placeholder="Sender or recipient name" />
        </label>
        <label>From (Bangladesh time)
          <input type="datetime-local" value={filters.since} onChange={(e) => setFilter('since', e.target.value)} />
        </label>
        <label>To (Bangladesh time)
          <input type="datetime-local" value={filters.until} onChange={(e) => setFilter('until', e.target.value)} />
        </label>
        <div className="lab-filter-actions">
          <button type="button" className="lab-chip" onClick={() => setFilters(EMPTY_FILTERS)} disabled={!filtered}>Clear filters</button>
          <button type="button" className="lab-chip" onClick={load}>Refresh</button>
        </div>
      </form>

      {error && <p className="error" role="alert">{error}</p>}

      <div className="lab-panel lab-log">
        <h3>Transfers <small>{entries === null ? '' : `${entries.length} shown of ${options.total} recorded`}</small></h3>
        {entries === null && !error && <p className="muted" role="status">Loading…</p>}
        {entries !== null && options.total === 0 && (
          <p className="lab-empty" role="status">
            <strong>No transactions yet.</strong> Log in as a demo customer, choose Send money and make a transfer: it will be scored
            and appear here within a few seconds.
          </p>
        )}
        {entries !== null && options.total > 0 && !hasFilterRows && <p className="lab-empty" role="status">No transfers match these filters.</p>}
        {hasFilterRows && (
          <div className="lab-table-wrap">
            <table className="lab-table" aria-label="Real transfers">
              <thead>
                <tr><th>Time (Dhaka)</th><th>Sender</th><th>Recipient</th><th>Amount</th><th>Risk</th><th>Outcome</th></tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.id} className={selected?.id === e.id ? 'on' : ''}>
                    <td>
                      <button type="button" className="lab-rowbtn" aria-pressed={selected?.id === e.id} onClick={() => choose(e)}
                        aria-label={`Open transfer ${e.id}: ${e.sender.name} to ${e.recipient.name}`}>{dhaka(e.created_at)}</button>
                    </td>
                    <td>{e.sender.name}<small>{formatPhone(e.sender.phone)}</small></td>
                    <td>{e.recipient.name}<small>{formatPhone(e.recipient.phone)}</small></td>
                    <td>{formatTaka(e.amount, 'en')}</td>
                    <td>{e.risk_pct === null ? '—' : <span className={`lab-pill tier-${e.tier}`}>{e.risk_pct.toFixed(1)}% · {TIERS[e.tier][0]}</span>}</td>
                    <td>{e.status === 'held' ? 'Held' : 'Sent'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selected && (
        <div className="lab-panel lab-result" aria-live="polite">
          <h3>
            {selected.sender.name} → {selected.recipient.name}{' '}
            <small>{formatTaka(selected.amount, 'en')} · {formatPhone(selected.sender.phone)} → {formatPhone(selected.recipient.phone)}</small>
          </h3>
          {explainError && <p className="error" role="alert">{explainError}</p>}
          {!result && !explainError && <p className="muted">Explaining…</p>}
          {result && <Result result={result} muted={muted} toggleSide={toggleSide} showAll={showAll} setShowAll={setShowAll} />}
        </div>
      )}

      {report && <Evidence report={report} />}
    </section>
  )
}

function Result({ result, muted, toggleSide, showAll, setShowAll }) {
  const [label, action] = TIERS[result.tier]
  const th = result.tier_thresholds_pct
  const rows = useMemo(() => {
    const live = result.contributions.filter((c) => Math.abs(c.points) >= 0.05 || c.present)
    return showAll ? result.contributions : live.slice(0, 10)
  }, [result, showAll])
  const maxAbs = Math.max(1, ...result.contributions.map((c) => Math.abs(c.points)))
  const sideMax = Math.max(1, ...Object.values(result.sides).map(Math.abs))
  const c = result.combination

  return (
    <>
      <div className={`lab-score tier-${result.tier}`}>
        <div className="lab-big" aria-label={`Risk ${result.risk_pct} percent`}>{result.risk_pct.toFixed(1)}<span>%</span></div>
        <div>
          <strong>{label} risk</strong>
          <p>{action}</p>
          <small>{result.signals_present} of 31 signals present</small>
        </div>
      </div>
      <div className="lab-meter" role="img" aria-label={`Risk meter at ${result.risk_pct} percent. Note from ${th.note} percent, safety check from ${th.high} percent, hold from ${th.very_high} percent.`}>
        <i style={{ width: `${Math.min(100, result.risk_pct)}%` }} />
        {['note', 'high', 'very_high'].map((k) => <b key={k} style={{ left: `${th[k]}%` }} title={`${TIERS[k][0]} from ${th[k]}%`} />)}
      </div>
      <p className="lab-note">Ticks mark where the tiers start: note {th.note}%, safety check {th.high}%, hold {th.very_high}%.</p>

      <h4>Who pushed the score</h4>
      <p className="lab-note">Start from the average transfer ({result.baseline_pct.toFixed(1)}%). Each group adds or removes points; calm, normal signals can take points away.</p>
      <ul className="lab-sides">
        {Object.entries(result.sides).map(([s, v]) => (
          <li key={s}>
            <span>{SIDES[s]}</span>
            <Bar value={v} max={sideMax} />
            <b className={v > 0.05 ? 'up' : v < -0.05 ? 'down' : ''}>{pts(v)}</b>
          </li>
        ))}
      </ul>

      <h4>Test the combination</h4>
      <p className="lab-note">What would the model say if only one group of signals were real and the rest looked normal?</p>
      <div className="lab-combo">
        <div><small>Typical transfer</small><b>{c.typical_transfer_pct.toFixed(1)}%</b></div>
        <div><small>Sender signals only</small><b>{c.sender_signals_only_pct.toFixed(1)}%</b></div>
        <div><small>Recipient + link only</small><b>{c.recipient_signals_only_pct.toFixed(1)}%</b></div>
        <div className="all"><small>All together</small><b>{c.all_signals_pct.toFixed(1)}%</b></div>
      </div>
      <p className="lab-note">
        {c.extra_from_combining_points > 1
          ? `Putting them together adds ${c.extra_from_combining_points.toFixed(1)} points more than the two parts add up to: the signals strengthen each other.`
          : 'The groups add up about as expected here: no extra effect from combining them.'}
      </p>

      <h4>What if the model could not see…</h4>
      <div className="lab-mutes" role="group" aria-label="Hide a group of signals">
        {Object.entries(SIDES).map(([s, l]) => (
          <button key={s} className={`lab-chip ${muted.includes(s) ? 'on' : ''}`} aria-pressed={muted.includes(s)} onClick={() => toggleSide(s)}>
            {muted.includes(s) ? 'Hidden: ' : ''}{l}
          </button>
        ))}
      </div>
      {muted.length > 0 && <p className="lab-note">Those signals are treated as normal. Compare the percentage above with the full picture.</p>}

      <h4>Signal by signal</h4>
      <ul className="lab-signals">
        {rows.map((r) => (
          <li key={r.signal} className={r.muted ? 'muted-row' : ''}>
            <div className="lab-sig-head">
              <span className={`lab-tag ${r.side}`}>{SIDES[r.side]}</span>
              <strong>{r.label}</strong>
              <b className={r.points > 0.05 ? 'up' : r.points < -0.05 ? 'down' : ''}>{r.points > 0.05 ? '▲ ' : r.points < -0.05 ? '▼ ' : ''}{pts(r.points)} pts</b>
            </div>
            <Bar value={r.points} max={maxAbs} />
            <small>{r.muted ? 'Hidden from the model (treated as normal)' : r.text}</small>
          </li>
        ))}
      </ul>
      <button className="link" onClick={() => setShowAll(!showAll)}>{showAll ? 'Show only the strongest signals' : `Show all ${result.contributions.length} signals`}</button>
    </>
  )
}

function Bar({ value, max }) {
  const w = Math.min(50, (Math.abs(value) / max) * 50)
  return (
    <span className="lab-bar" aria-hidden="true">
      <i className={value >= 0 ? 'up' : 'down'} style={value >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }} />
    </span>
  )
}

function Evidence({ report }) {
  const sides = report.which_sides_are_needed
  const order = ['sender signals only', 'recipient signals only', 'sender + recipient (no link signals)', 'all three sides']
  return (
    <details className="lab-panel lab-evidence">
      <summary>Evidence: why the model needs both sides</summary>
      <p className="lab-note">
        Measured on {report.data.test.toLocaleString()} synthetic test transfers ({report.data.scams_in_test.toLocaleString()} scams) that the model never saw in training.
        Higher PR-AUC is better; 1.0 is perfect.
      </p>
      <table>
        <thead><tr><th>Model looks at</th><th>Signals</th><th>PR-AUC</th><th>Scams caught at the hold tier</th></tr></thead>
        <tbody>
          {order.map((k) => (
            <tr key={k}><td>{k}</td><td>{sides[k].signals}</td><td>{sides[k].pr_auc.toFixed(2)}</td><td>{(sides[k].caught_at_hold_tier * 100).toFixed(0)}%</td></tr>
          ))}
        </tbody>
      </table>
      <ul className="lab-note">
        <li>Only {report.score_spread.scams_scoring_99_or_more_pct}% of scams score 99% or more; the middle half of scams score between {report.score_spread.scam_score_percentiles['25']}% and {report.score_spread.scam_score_percentiles['75']}%.</li>
        <li>Genuine transfers disturbed at the hold tier: {report.headline.genuine_disturbed_pct_at_hold}%. Calibration error: {report.headline.calibration_error}.</li>
        <li>Data is synthetic, so these are prototype numbers, not production performance.</li>
      </ul>
    </details>
  )
}
