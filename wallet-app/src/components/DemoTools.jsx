import { useState } from 'react'
import { api } from '../api.js'
import { errorText } from '../i18n.js'
import { isValidPhone } from '../format.js'
import Sheet from './Sheet.jsx'

const FRAUD_WALLETS = [
  { label: 'Jamal (fraud wallet 1)', phone: '01711999999' },
  { label: 'Mitu (fraud wallet 2)', phone: '01711999998' },
]

/** Presenter's toolbox: plants a scammer's fake SMS, and skips the 30-minute wait. */
export default function DemoTools({ t, onClose, onChanged }) {
  const [amount, setAmount] = useState('5000')
  const [from, setFrom] = useState(FRAUD_WALLETS[0].phone)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function run(action, ok) {
    setError('')
    setMessage('')
    setBusy(true)
    try {
      const result = await action()
      setMessage(ok(result))
      onChanged?.()
    } catch (e) {
      setError(errorText(e, t))
    } finally {
      setBusy(false)
    }
  }

  function drop() {
    const value = Number(amount)
    if (!isValidPhone(from)) return setError(t('errInvalidPhone'))
    if (!Number.isInteger(value) || value < 10 || value > 50000) return setError(t('errInvalidAmount'))
    run(() => api.fakeSms(value, from), () => t('smsDropped'))
  }

  return (
    <Sheet title={t('demoTools')} onClose={onClose} closeLabel={t('close')}>
      <section className="tool">
        <h3>{t('fakeSmsTitle')}</h3>
        <p className="muted">{t('fakeSmsHelp')}</p>
        <label>
          {t('amount')}
          <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, '').slice(0, 5))} inputMode="numeric" />
        </label>
        <label>
          {t('fromNumber')}
          <input value={from} onChange={(e) => setFrom(e.target.value.replace(/\D/g, '').slice(0, 11))} inputMode="numeric" />
        </label>
        <div className="quick">
          {FRAUD_WALLETS.map((w) => <button type="button" key={w.phone} className="chip" onClick={() => setFrom(w.phone)}>{w.label}</button>)}
        </div>
        <button className="primary" disabled={busy} onClick={drop}>{t('dropSms')}</button>
      </section>
      <section className="tool">
        <h3>{t('skipWait')}</h3>
        <p className="muted">{t('skipWaitHelp')}</p>
        <button className="primary secondary" disabled={busy} onClick={() => run(() => api.releaseHoldsNow(), (r) => t('holdsReleased', { n: r.released }))}>{t('skipWait')}</button>
      </section>
      {message && <p className="flash" role="status">{message}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </Sheet>
  )
}
