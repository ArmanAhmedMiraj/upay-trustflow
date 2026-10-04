import { useState } from 'react'
import { api } from '../api.js'
import { errorText } from '../i18n.js'
import { isValidPhone, isValidPin } from '../format.js'

const DEMO_ACCOUNTS = [
  { label: 'Rahim', phone: '01711000001', pin: '12345' },
  { label: 'Nusrat', phone: '01711000005', pin: '12345' },
  { label: 'Sumon', phone: '01711000006', pin: '12345' },
  { label: 'Agent Babul', phone: '01811000001', pin: '12345' },
  { label: 'Fraud analyst', phone: '01911000001', pin: '99999' },
]
const SHOW_DEMO = import.meta.env?.VITE_DEMO !== '0'

export default function Login({ t, lang, onToggleLang, onLoggedIn, notice }) {
  const [mode, setMode] = useState('login')
  const [phone, setPhone] = useState('')
  const [name, setName] = useState('')
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setError('')
    if (!isValidPhone(phone)) return setError(t('errInvalidPhone'))
    if (mode === 'register' && !name.trim()) return setError(t('errInvalidName'))
    if (!isValidPin(pin)) return setError(t('errInvalidPin'))
    setBusy(true)
    try {
      if (mode === 'register') await api.register(phone, name.trim(), pin)
      const result = await api.login(phone, pin)
      onLoggedIn(result.token, result.user)
    } catch (e) {
      setError(errorText(e, t))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="screen login">
      <button className="lang" onClick={onToggleLang} aria-label="Change language">{t('language')}</button>
      <div className="brand">
        <div className="logo" aria-hidden="true">u</div>
        <h1>{t('appName')}</h1>
        <p className="concept">{t('concept')}</p>
      </div>

      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={mode === 'login'} className={mode === 'login' ? 'on' : ''} onClick={() => { setMode('login'); setError('') }}>{t('login')}</button>
        <button role="tab" aria-selected={mode === 'register'} className={mode === 'register' ? 'on' : ''} onClick={() => { setMode('register'); setError('') }}>{t('register')}</button>
      </div>

      <form onSubmit={submit} noValidate>
        {mode === 'register' && (
          <label>
            {t('fullName')}
            <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
          </label>
        )}
        <label>
          {t('phone')}
          <input value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 11))} inputMode="numeric"
            placeholder={t('phonePlaceholder')} autoComplete="username" />
        </label>
        <label>
          {t('pin')}
          <input value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 5))} inputMode="numeric"
            type="password" autoComplete="current-password" />
        </label>
        {(error || notice) && <p className="error" role="alert">{error || notice}</p>}
        <button className="primary" type="submit" disabled={busy}>{busy ? t('working') : mode === 'login' ? t('login') : t('register')}</button>
      </form>

      {SHOW_DEMO && mode === 'login' && (
        <div className="demo">
          <span>{t('demoLogin')}</span>
          {DEMO_ACCOUNTS.map((a) => (
            <button key={a.phone} type="button" className="chip" onClick={() => { setPhone(a.phone); setPin(a.pin); setError('') }}>{a.label}</button>
          ))}
        </div>
      )}
    </div>
  )
}
