import { useState } from 'react'
import { api } from '../api.js'
import { errorText } from '../i18n.js'
import { formatTaka, isValidPhone, isValidPin, newKey } from '../format.js'
import Sheet from './Sheet.jsx'

const DEMO_AGENTS = [
  { label: 'Agent Babul', phone: '01811000001' },
  { label: 'Agent Shiuli', phone: '01811000002' },
]
const SHOW_DEMO = import.meta.env?.VITE_DEMO !== '0'

export default function CashOutSheet({ t, lang, onClose, onDone }) {
  const [phone, setPhone] = useState('')
  const [amount, setAmount] = useState('')
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [key] = useState(newKey)
  const value = Number(amount)

  async function submit(event) {
    event.preventDefault()
    if (!isValidPhone(phone)) return setError(t('errInvalidPhone'))
    if (!Number.isInteger(value) || value < 10 || value > 50000) return setError(t('errInvalidAmount'))
    if (!isValidPin(pin)) return setError(t('errInvalidPin'))
    setBusy(true)
    try {
      onDone((await api.cashOut(phone, value, pin, key)).balance)
    } catch (e) {
      setError(errorText(e, t))
      setPin('')
      setBusy(false)
    }
  }

  return (
    <Sheet title={t('cashOutTitle')} onClose={onClose} closeLabel={t('close')}>
      <form onSubmit={submit} noValidate>
        <label>
          {t('agentPhone')}
          <input value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 11))} inputMode="numeric" />
        </label>
        {SHOW_DEMO && (
          <div className="quick">
            {DEMO_AGENTS.map((a) => <button type="button" key={a.phone} className="chip" onClick={() => setPhone(a.phone)}>{a.label}</button>)}
          </div>
        )}
        <label>
          {t('amount')}
          <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" />
        </label>
        <div className="quick">
          {[500, 1000, 2000].map((v) => <button type="button" key={v} className="chip" onClick={() => setAmount(String(v))}>{formatTaka(v, lang)}</button>)}
        </div>
        <label>
          {t('pin')}
          <input value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 5))} inputMode="numeric" type="password" />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" type="submit" disabled={busy}>{busy ? t('working') : t('confirm')}</button>
      </form>
    </Sheet>
  )
}
