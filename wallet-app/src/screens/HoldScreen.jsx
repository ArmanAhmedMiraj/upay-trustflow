import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { errorText } from '../i18n.js'
import { formatRemaining, formatTaka, formatWhen, parseApiTime } from '../format.js'
import ReportSheet from '../components/ReportSheet.jsx'

const HOLD_MS = 30 * 60 * 1000

/** A transfer waiting in escrow: a live countdown, a cancel button, and what happens next. */
export default function HoldScreen({ txn, t, lang, onBack, onBalance }) {
  const [now, setNow] = useState(Date.now())
  const [status, setStatus] = useState(txn.status ?? 'held')
  const [balance, setBalance] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [reporting, setReporting] = useState(false)
  const [reported, setReported] = useState(false)

  const releaseAt = parseApiTime(txn.release_at)
  const remaining = releaseAt ? releaseAt.getTime() - now : 0
  const name = txn.counterparty_name ?? ''

  const refresh = useCallback(async () => {
    try {
      const found = (await api.transactions(50)).transactions.find((x) => x.id === txn.id)
      if (found) setStatus(found.status)
    } catch {
      /* try again on the next tick */
    }
  }, [txn.id])

  // tick every second while the hold is running
  useEffect(() => {
    if (status !== 'held') return undefined
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [status])

  // when the clock reaches zero, ask the server what happened (it releases the money on the next request)
  useEffect(() => {
    if (status !== 'held' || remaining > 0) return undefined
    refresh()
    const id = setInterval(refresh, 3000)
    return () => clearInterval(id)
  }, [status, remaining, refresh])

  async function cancel() {
    setBusy(true)
    setError('')
    try {
      const r = await api.cancelHold(txn.id)
      setStatus('cancelled')
      setBalance(r.balance)
      onBalance?.(r.balance)
    } catch (e) {
      setError(errorText(e, t))
      refresh()
    } finally {
      setBusy(false)
    }
  }

  const progress = Math.min(1, Math.max(0, 1 - remaining / HOLD_MS))
  const amount = formatTaka(txn.amount, lang)

  return (
    <div className={`screen flow hold ${status}`}>
      <header className="flow-head">
        <button className="link" onClick={onBack}>‹ {t('back')}</button>
        <h2>{status === 'held' ? t('holdTitle') : ''}</h2>
        <span />
      </header>

      {status === 'held' && (
        <>
          <div className="countdown" role="timer" aria-label={t('timeLeft')}>
            <small>{t('timeLeft')}</small>
            <strong>{formatRemaining(remaining)}</strong>
            <div className="meter-bar"><div className="meter-fill" style={{ width: `${progress * 100}%` }} /></div>
          </div>
          <p>{t('holdBody', { amount, name })}</p>
          {releaseAt && <p className="muted">{t('willRelease')} {formatWhen(txn.release_at, lang, new Date(), { today: t('today'), yesterday: t('yesterday') })}. {t('analystMayReview')}</p>}
          {error && <p className="error" role="alert">{error}</p>}
          <div className="flow-actions">
            <button className="primary" onClick={cancel} disabled={busy}>{busy ? t('working') : t('cancelHold')}</button>
            {txn.counterparty_phone && <button className="primary ghost" onClick={() => setReporting(true)} disabled={reported}>{reported ? '✓ ' + t('reportSent') : t('reportNumber')}</button>}
          </div>
        </>
      )}

      {status === 'cancelled' && (
        <div className="outcome good">
          <div className="big-check" aria-hidden="true">✓</div>
          <p>{t('moneyBack')}</p>
          {balance !== null && <p className="muted">{t('balance')}: {formatTaka(balance, lang)}</p>}
          {txn.counterparty_phone && <button className="primary ghost" onClick={() => setReporting(true)} disabled={reported}>{reported ? '✓ ' + t('reportSent') : t('reportNumber')}</button>}
          <button className="primary" onClick={onBack}>{t('done')}</button>
        </div>
      )}
      {status === 'completed' && (
        <div className="outcome"><p>{t('holdReleased')}</p><button className="primary" onClick={onBack}>{t('done')}</button></div>
      )}
      {status === 'rejected' && (
        <div className="outcome good"><p>{t('holdRejected')}</p><button className="primary" onClick={onBack}>{t('done')}</button></div>
      )}

      {reporting && <ReportSheet t={t} defaultPhone={txn.counterparty_phone} onClose={() => setReporting(false)} onDone={() => { setReporting(false); setReported(true) }} />}
    </div>
  )
}
