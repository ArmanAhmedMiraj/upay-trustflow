import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { errorText, makeT } from '../i18n.js'

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
const CREDIT_AGES = [[5, '5 minutes ago'], [60, '1 hour ago'], [1440, '1 day ago'], [2000, 'a day or more ago'], [10080, 'a week ago']]
const pts = (v) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}`
const hourText = (h) => `${String(Math.floor(h)).padStart(2, '0')}:00`

/** The analyst's Risk Lab: build a transfer from a sender, a recipient and the live details, and watch how each signal moves the score. */
export default function RiskLab() {
  const [accounts, setAccounts] = useState(null)
  const [report, setReport] = useState(null)
  const [senderId, setSenderId] = useState('')
  const [recipientId, setRecipientId] = useState('')
  const [tx, setTx] = useState(null)
  const [muted, setMuted] = useState([])
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [scenarioId, setScenarioId] = useState('')
  const ticket = useRef(0)

  useEffect(() => {
    api.labAccounts().then((a) => {
      setAccounts(a)
      const first = a.scenarios.find((s) => s.id === 'officer') ?? a.scenarios[0]
      applyScenario(first, a)
    }).catch((e) => setError(errorText(e, t)))
    api.labReport().then(setReport).catch(() => {})
  }, [])

  function applyScenario(s, a = accounts) {
    setScenarioId(s.id)
    setSenderId(s.sender)
    setRecipientId(s.recipient)
    setTx({ ...a.default_tx, ...s.tx })
    setMuted([])
  }

  useEffect(() => {
    if (!senderId || !recipientId || !tx) return undefined
    const mine = ++ticket.current
    const timer = setTimeout(() => {
      api.labScore({ sender_id: senderId, recipient_id: recipientId, tx, mute_sides: muted })
        .then((r) => { if (mine === ticket.current) { setResult(r); setError('') } })
        .catch((e) => { if (mine === ticket.current) setError(errorText(e, t)) })
    }, 200)
    return () => clearTimeout(timer)
  }, [senderId, recipientId, tx, muted])

  const setField = (k, v) => { setScenarioId(''); setTx((x) => ({ ...x, [k]: v })) }
  const toggleSide = (s) => setMuted((m) => (m.includes(s) ? m.filter((x) => x !== s) : [...m, s]))

  const sender = accounts?.senders.find((s) => s.id === senderId)
  const recipient = accounts?.recipients.find((r) => r.id === recipientId)
  const scenario = accounts?.scenarios.find((s) => s.id === scenarioId)

  if (!accounts) {
    return <section className="lab"><p className={error ? 'error' : 'muted'} role={error ? 'alert' : 'status'}>{error || 'Loading the Risk Lab…'}</p></section>
  }

  return (
    <section className="lab">
      <div className="lab-intro">
        <h2>How the AI scores a transfer</h2>
        <p>
          Pick a sender and a recipient, change the live details, and see how each of the 31 signals pushes the risk up or down.
          The model reads three groups at once: <strong>sender behaviour</strong>, the <strong>recipient account</strong> and the <strong>link</strong> between them.
        </p>
      </div>

      <div className="lab-presets" role="group" aria-label="Ready-made stories">
        {accounts.scenarios.map((s) => (
          <button key={s.id} className={`lab-chip ${s.id === scenarioId ? 'on' : ''}`} aria-pressed={s.id === scenarioId} onClick={() => applyScenario(s)}>{s.title}</button>
        ))}
      </div>
      {scenario && <p className="lab-shows"><strong>What this shows:</strong> {scenario.shows}</p>}
      {error && <p className="error" role="alert">{error}</p>}

      <div className="lab-grid">
        <div className="lab-panel lab-controls">
          <h3>1. Build the transfer</h3>
          <label>Sender
            <select value={senderId} onChange={(e) => { setScenarioId(''); setSenderId(e.target.value) }}>
              {accounts.senders.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          {sender && <p className="lab-note">{sender.bio}. District: {sender.district}.</p>}

          <label>Recipient
            <select value={recipientId} onChange={(e) => { setScenarioId(''); setRecipientId(e.target.value) }}>
              {accounts.recipients.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </label>
          {recipient && (
            <div className="lab-recipient">
              <p className="lab-note">{recipient.story}</p>
              <dl className="lab-facts">
                {Object.entries(recipient.facts).map(([k, v]) => (
                  <div key={k}><dt>{k}</dt><dd>{typeof v === 'boolean' ? (v ? 'yes' : 'no') : String(v)}</dd></div>
                ))}
              </dl>
            </div>
          )}

          <fieldset className="lab-fields">
            <legend>Live details of the payment</legend>
            <label>Amount (৳)
              <input type="number" min="1" max="1000000" step="100" value={tx.amount}
                onChange={(e) => setField('amount', Math.max(1, Number(e.target.value) || 1))} />
            </label>
            <label>Time of day: {hourText(tx.hour)}
              <input type="range" min="0" max="23" value={tx.hour} onChange={(e) => setField('hour', Number(e.target.value))} />
            </label>
            <label>Seconds on the confirm screen: {tx.hesitation_secs}
              <input type="range" min="1" max="60" value={tx.hesitation_secs} onChange={(e) => setField('hesitation_secs', Number(e.target.value))} />
            </label>
            <label>Times the amount was edited: {tx.amount_edits}
              <input type="range" min="0" max="5" value={tx.amount_edits} onChange={(e) => setField('amount_edits', Number(e.target.value))} />
            </label>
            <label>Sender last received money
              <select value={tx.mins_since_credit} onChange={(e) => setField('mins_since_credit', Number(e.target.value))}>
                {CREDIT_AGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label className="lab-check"><input type="checkbox" checked={!!tx.on_call} onChange={(e) => setField('on_call', e.target.checked ? 1 : 0)} /> Sender is on a phone call</label>
            <label className="lab-check"><input type="checkbox" checked={!!tx.new_device} onChange={(e) => setField('new_device', e.target.checked ? 1 : 0)} /> Sender logged in from a new device</label>
            <label className="lab-check"><input type="checkbox" checked={!!tx.sms_claim_mismatch} onChange={(e) => setField('sms_claim_mismatch', e.target.checked ? 1 : 0)} /> An SMS says money arrived, but the ledger shows none</label>
          </fieldset>
        </div>

        <div className="lab-panel lab-result" aria-live="polite">
          <h3>2. What the AI decides</h3>
          {!result ? <p className="muted">Scoring…</p> : <Result result={result} muted={muted} toggleSide={toggleSide} showAll={showAll} setShowAll={setShowAll} />}
        </div>
      </div>

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
