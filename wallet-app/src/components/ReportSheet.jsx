import { useState } from 'react'
import { api } from '../api.js'
import { errorText } from '../i18n.js'
import { isValidPhone } from '../format.js'
import Sheet from './Sheet.jsx'

export default function ReportSheet({ t, defaultPhone = '', onClose, onDone }) {
  const [phone, setPhone] = useState(defaultPhone)
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    if (!isValidPhone(phone)) return setError(t('errInvalidPhone'))
    setBusy(true)
    try {
      await api.report(phone, reason.trim())
      onDone()
    } catch (e) {
      setError(errorText(e, t))
      setBusy(false)
    }
  }

  return (
    <Sheet title={t('reportTitle')} onClose={onClose} closeLabel={t('close')}>
      <form onSubmit={submit} noValidate>
        <label>
          {t('phone')}
          <input value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 11))} inputMode="numeric" />
        </label>
        <label>
          {t('reportReason')}
          <input value={reason} onChange={(e) => setReason(e.target.value.slice(0, 200))} />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary danger" type="submit" disabled={busy}>{busy ? t('working') : t('reportNumber')}</button>
      </form>
    </Sheet>
  )
}
