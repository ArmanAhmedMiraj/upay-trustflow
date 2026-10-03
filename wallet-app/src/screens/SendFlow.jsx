import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { errorText } from '../i18n.js'
import { formatPhone, formatTaka, isValidPhone, isValidPin, newKey } from '../format.js'
import RiskPanel from '../components/RiskPanel.jsx'

const NEEDS_ACK = ['safety_check', 'warn_and_confirm', 'hold_30min']

/**
 * Send money, in four steps: details -> safety review (the live risk meter) -> PIN -> done.
 * The server checks the transfer again when the PIN is sent, so nothing here can be skipped.
 */
export default function SendFlow({ user, t, lang, onClose, onSent, onHeld }) {
  const [step, setStep] = useState('form')
  const [phone, setPhone] = useState('')
  const [amount, setAmount] = useState('')
  const [onCall, setOnCall] = useState(false)
  const [recipient, setRecipient] = useState(null)
  const [risk, setRisk] = useState(null)
  const [questions, setQuestions] = useState([])
  const [answers, setAnswers] = useState({})
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(null)
  const [recents, setRecents] = useState([])

  const startedAt = useRef(Date.now())      // how long the customer hesitates is one of Shield's signals
  const edits = useRef(0)                   // so is how often they change the amount
  const lastAmount = useRef(null)
  const key = useRef(newKey())              // one key per send, so a double tap cannot pay twice

  useEffect(() => {
    api.transactions(40)
      .then((r) => {
        const seen = new Map()
        for (const x of r.transactions) {
          if (x.kind === 'send_money' && x.direction === 'out' && x.counterparty_phone && !seen.has(x.counterparty_phone)) {
            seen.set(x.counterparty_phone, x.counterparty_name)
          }
        }
        setRecents([...seen].slice(0, 4).map(([p, n]) => ({ phone: p, name: n })))
      })
      .catch(() => {})
  }, [])

  const value = Number(amount)
  const behavior = () => ({
    hesitation_secs: Math.min(3600, Math.round((Date.now() - startedAt.current) / 100) / 10),
    amount_edits: edits.current,
    on_call: onCall,
  })
  const answerList = () => Object.entries(answers).map(([question_id, answer]) => ({ question_id, answer }))
  const needsAck = risk ? NEEDS_ACK.includes(risk.action) : false

  async function check(event) {
    event.preventDefault()
    setError('')
    if (!isValidPhone(phone)) return setError(t('errInvalidPhone'))
    if (phone === user.phone) return setError(t('errSelf'))
    if (!Number.isInteger(value) || value < 10 || value > 50000) return setError(t('errInvalidAmount'))
    if (lastAmount.current !== null && lastAmount.current !== value) edits.current += 1
    lastAmount.current = value
    setBusy(true)
    try {
      const r = await api.preview(phone, value, behavior(), undefined)
      setRecipient(r.recipient)
      setRisk(r.risk)
      setQuestions(r.risk.action === 'safety_check' ? r.risk.questions : [])
      setAnswers({})
      setStep('review')
    } catch (e) {
      setError(errorText(e, t))
    } finally {
      setBusy(false)
    }
  }

  async function answer(questionId, choice) {
    const next = { ...answers, [questionId]: choice }
    setAnswers(next)
    setBusy(true)
    setError('')
    try {
      const list = Object.entries(next).map(([question_id, a]) => ({ question_id, answer: a }))
      setRisk((await api.preview(phone, value, behavior(), list)).risk)
    } catch (e) {
      setError(errorText(e, t))
    } finally {
      setBusy(false)
    }
  }

  async function confirm(event) {
    event.preventDefault()
    setError('')
    if (!isValidPin(pin)) return setError(t('errInvalidPin'))
    setBusy(true)
    try {
      const list = answerList()
      const r = await api.send({
        recipient_phone: phone, amount: value, pin, idempotency_key: key.current, behavior: behavior(),
        acknowledged_risk: needsAck, safety_answers: list.length ? list : undefined,
      })
      if (r.transaction.status === 'held') {
        onHeld({ ...r.transaction, counterparty_name: recipient.name, counterparty_phone: recipient.phone }, r.balance)
      } else {
        setSent({ balance: r.balance })
        setStep('done')
        onSent(r.balance)
      }
    } catch (e) {
      if (e.code === 'risk_interruption' && e.risk) {
        setRisk(e.risk)                  // the server saw something different from the preview: show the new verdict
        setStep('review')
      } else {
        setError(errorText(e, t))
      }
      setPin('')
    } finally {
      setBusy(false)
    }
  }

  const header = (title, back) => (
    <header className="flow-head">
      {back ? <button className="link" onClick={back} aria-label={t('back')}>‹ {t('back')}</button> : <span />}
      <h2>{title}</h2>
      <button className="icon" onClick={onClose} aria-label={t('close')}>×</button>
    </header>
  )

  if (step === 'form') {
    return (
      <div className="screen flow">
        {header(t('sendTitle'))}
        <form onSubmit={check} noValidate>
          <label>
            {t('recipientPhone')}
            <input value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 11))} inputMode="numeric"
              placeholder={t('phonePlaceholder')} autoFocus />
          </label>
          {recents.length > 0 && (
            <div className="recents">
              <small>{t('recentRecipients')}</small>
              <div className="quick">
                {recents.map((r) => <button type="button" key={r.phone} className="chip" onClick={() => setPhone(r.phone)}>{r.name.split(' ')[0]}</button>)}
              </div>
            </div>
          )}
          <label>
            {t('amount')}
            <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, '').slice(0, 5))} inputMode="numeric" />
          </label>
          <label className="check">
            <input type="checkbox" checked={onCall} onChange={(e) => setOnCall(e.target.checked)} /> {t('onCall')}
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary" type="submit" disabled={busy}>{busy ? t('checking') : t('continue')}</button>
        </form>
      </div>
    )
  }

  if (step === 'review') {
    const label = risk.action === 'hold_30min' ? t('holdAndSend') : NEEDS_ACK.includes(risk.action) ? t('continueAnyway') : t('continue')
    return (
      <div className="screen flow">
        {header(t('sendTitle'), () => setStep('form'))}
        <div className="summary">
          <small>{t('to')}</small>
          <strong>{recipient.name}</strong>
          <span>{formatPhone(recipient.phone)}</span>
          <div className="summary-amount">{formatTaka(value, lang)}</div>
        </div>
        <RiskPanel risk={risk} questions={questions} answers={answers} onAnswer={answer} busy={busy} t={t} lang={lang} />
        {error && <p className="error" role="alert">{error}</p>}
        <div className="flow-actions">
          <button className={`primary ${risk.action === 'hold_30min' ? 'danger' : ''}`} onClick={() => { setError(''); setStep('pin') }} disabled={busy}>{label}</button>
          <button className="primary ghost" onClick={onClose}>{t('cancelTransfer')}</button>
        </div>
      </div>
    )
  }

  if (step === 'pin') {
    return (
      <div className="screen flow">
        {header(t('enterPin'), () => setStep('review'))}
        <div className="summary compact">
          <strong>{recipient.name}</strong>
          <div className="summary-amount">{formatTaka(value, lang)}</div>
        </div>
        <form onSubmit={confirm} noValidate>
          <label>
            {t('pin')}
            <input value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 5))} inputMode="numeric" type="password" autoFocus />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary" type="submit" disabled={busy}>{busy ? t('working') : risk.action === 'hold_30min' ? t('holdAndSend') : t('sendNow')}</button>
        </form>
      </div>
    )
  }

  return (
    <div className="screen flow done">
      <div className="big-check" aria-hidden="true">✓</div>
      <h2>{t('sentOk')}</h2>
      <p>{t('sentOkFull', { amount: formatTaka(value, lang), name: recipient.name })}</p>
      <p className="muted">{t('balance')}: {formatTaka(sent.balance, lang)}</p>
      <button className="primary" onClick={onClose}>{t('done')}</button>
    </div>
  )
}
