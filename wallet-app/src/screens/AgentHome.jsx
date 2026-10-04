import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { errorText } from '../i18n.js'
import { formatTaka, formatWhen } from '../format.js'
import ForecastChart from '../components/ForecastChart.jsx'

const SCENARIOS = [['normal', 'scenarioNormal'], ['payday', 'scenarioPayday'], ['festival', 'scenarioFestival']]
const SHOW_DEMO = import.meta.env?.VITE_DEMO !== '0'
const STATUS_TEXT = { red: 'statusRed', yellow: 'statusYellow', green: 'statusGreen' }

/** The agent's phone screen: how much cash they will need, when it runs out, and one tap to ask upay for a refill. */
export default function AgentHome({ user, t, lang, onToggleLang, onLogout }) {
  const [scenario, setScenario] = useState('festival')
  const [data, setData] = useState(null)
  const [requests, setRequests] = useState([])
  const [error, setError] = useState('')
  const [flash, setFlash] = useState('')
  const [busy, setBusy] = useState(false)

  const loadRequests = useCallback(() => api.agentRefillRequests().then((r) => setRequests(r.requests)).catch(() => {}), [])

  useEffect(() => {
    setData(null)
    setError('')
    api.agentForecast(scenario).then(setData).catch((e) => setError(errorText(e, t)))
  }, [scenario, t])

  useEffect(() => {
    loadRequests()
    const id = setInterval(loadRequests, 5000)
    return () => clearInterval(id)
  }, [loadRequests])

  async function ask() {
    setBusy(true)
    setError('')
    try {
      await api.agentRefillRequest(scenario)
      setFlash(t('requestSent'))
      setTimeout(() => setFlash(''), 3500)
      loadRequests()
    } catch (e) {
      setError(errorText(e, t))
    } finally {
      setBusy(false)
    }
  }

  const words = { today: t('today'), yesterday: t('yesterday') }
  const statusLabel = { open: 'reqOpen', dispatched: 'reqDispatched' }
  return (
    <div className="screen home agent-home">
      <header className="topbar">
        <div><small>{t('hello')},</small><strong>{user.name}</strong></div>
        <div className="topbar-actions">
          <button className="lang" onClick={onToggleLang} aria-label="Change language">{t('language')}</button>
          <button className="lang" onClick={onLogout}>{t('logout')}</button>
        </div>
      </header>

      {SHOW_DEMO && (
        <div>
          <small className="muted">{t('demoDay')}</small>
          <div className="scenario-switch" role="group" aria-label={t('demoDay')}>
            {SCENARIOS.map(([key, label]) => (
              <button key={key} className={scenario === key ? 'on' : ''} aria-pressed={scenario === key} onClick={() => setScenario(key)}>{t(label)}</button>
            ))}
          </div>
        </div>
      )}

      {error && <p className="error" role="alert">{error}</p>}
      {flash && <p className="flash" role="status">{flash}</p>}
      {!data && !error && <p className="muted">{t('working')}</p>}

      {data && (
        <>
          <section className={`status-card ${data.status}`} aria-label={t('agentTitle')}>
            <small>{t('agentTitle')} · {data.area}</small>
            <strong>{t(STATUS_TEXT[data.status])}</strong>
            {data.runout_label && <span>{t('runsOutAt')}: {lang === 'bn' ? data.runout_label_bn : data.runout_label}</span>}
          </section>

          <div className="figures">
            <div><small>{t('cashOnHand')}</small><strong>{formatTaka(data.cash_now, lang)}</strong></div>
            <div><small>{t('cashNeeded')}</small><strong>{formatTaka(data.need_cash_24h, lang)}</strong></div>
            <div><small>{t('addCash')}</small><strong>{data.refill_cash ? formatTaka(data.refill_cash, lang) : t('allGood')}</strong></div>
            <div><small>{t('addFloat')}</small><strong>{data.refill_float ? formatTaka(data.refill_float, lang) : t('allGood')}</strong></div>
          </div>

          <p className="briefing" lang={lang}>{lang === 'bn' ? data.briefing_bn : data.briefing_en}</p>

          {data.refill_cash > 0 || data.refill_float > 0
            ? <button className="primary" onClick={ask} disabled={busy}>{busy ? t('working') : t('requestRefill')}</button>
            : <p className="notice good">✓ {t('nothingNeeded')}</p>}

          <ForecastChart data={data} labels={{ demand: t('hourlyDemand'), normal: t('normalDemand'), busy: t('busyDemand'), cash: t('cashPath') }} />

          <section className="activity">
            <h2>{t('myRequests')}</h2>
            {requests.length === 0 && <p className="muted">{t('noRequests')}</p>}
            <ul className="txn-list">
              {requests.map((r) => (
                <li key={r.id} className="txn">
                  <div className={`avatar ${r.status === 'open' ? 'out' : 'in'}`} aria-hidden="true">{r.status === 'open' ? '…' : '✓'}</div>
                  <div className="txn-main">
                    <strong>{formatTaka(r.cash_bdt, lang)}</strong>
                    <small>{formatWhen(r.created_at, lang, new Date(), words)}<span className={`badge ${r.status === 'open' ? 'held' : 'status-green'}`}>{t(statusLabel[r.status])}</span></small>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}
