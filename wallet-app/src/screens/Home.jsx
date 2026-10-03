import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { errorText } from '../i18n.js'
import { formatTaka } from '../format.js'
import CashOutSheet from '../components/CashOutSheet.jsx'
import DemoTools from '../components/DemoTools.jsx'
import ReportSheet from '../components/ReportSheet.jsx'
import Sheet from '../components/Sheet.jsx'
import TxnRow from '../components/TxnRow.jsx'

const SHOW_DEMO = import.meta.env?.VITE_DEMO !== '0'

export default function Home({ user, setUser, t, lang, onToggleLang, onLogout, go }) {
  const [hidden, setHidden] = useState(false)
  const [txns, setTxns] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [sheet, setSheet] = useState(null)       // 'add' | 'cashout' | 'report' | 'demo' | null
  const [flash, setFlash] = useState('')

  const load = useCallback(async () => {
    setLoadError('')
    try {
      setTxns((await api.transactions(15)).transactions)
    } catch (e) {
      setLoadError(errorText(e, t))
    }
  }, [t])

  useEffect(() => {
    load()
  }, [load])

  function say(message) {
    setFlash(message)
    setTimeout(() => setFlash(''), 3500)
  }
  function newBalance(balance, message) {
    setUser((u) => ({ ...u, balance }))
    setSheet(null)
    say(message)
    load()
  }
  async function refreshAll() {
    try {
      setUser((await api.me()).user)
    } catch {
      /* the balance will refresh on the next action */
    }
    load()
  }

  const tiles = [
    { key: 'send', icon: '➤', label: t('sendMoney'), run: () => go({ name: 'send' }) },
    { key: 'add', icon: '＋', label: t('addMoney'), run: () => setSheet('add') },
    { key: 'cash', icon: '₿', label: t('cashOut'), run: () => setSheet('cashout') },
    { key: 'history', icon: '☰', label: t('history'), run: () => go({ name: 'history' }) },
    { key: 'inbox', icon: '✉', label: t('inbox'), run: () => go({ name: 'inbox' }) },
    { key: 'report', icon: '⚑', label: t('reportNumber'), run: () => setSheet('report') },
  ]

  return (
    <div className="screen home">
      <header className="topbar">
        <div>
          <small>{t('hello')},</small>
          <strong>{user.name.split(' ')[0]}</strong>
        </div>
        <div className="topbar-actions">
          <button className="lang" onClick={onToggleLang} aria-label="Change language">{t('language')}</button>
          <button className="lang" onClick={onLogout}>{t('logout')}</button>
        </div>
      </header>

      <section className="balance-card" aria-label={t('balance')}>
        <small>{t('balance')}</small>
        <div className="balance-row">
          <strong data-testid="balance">{hidden ? '৳ ••••' : formatTaka(user.balance, lang)}</strong>
          <button className="lang" onClick={() => setHidden((h) => !h)}>{hidden ? t('showBalance') : t('hideBalance')}</button>
        </div>
      </section>

      {flash && <p className="flash" role="status">{flash}</p>}

      <nav className="actions" aria-label="Actions">
        {tiles.map((x) => (
          <button key={x.key} className="action" onClick={x.run}><span aria-hidden="true">{x.icon}</span>{x.label}</button>
        ))}
      </nav>

      <section className="activity">
        <div className="section-head">
          <h2>{t('recent')}</h2>
          <button className="link small" onClick={() => go({ name: 'history' })}>{t('seeAll')} ›</button>
        </div>
        {loadError && <p className="error" role="alert">{loadError} <button className="link" onClick={load}>↻</button></p>}
        {!loadError && txns === null && <p className="muted">{t('working')}</p>}
        {txns && txns.length === 0 && <p className="muted">{t('noActivity')}</p>}
        {txns && txns.length > 0 && (
          <ul className="txn-list">{txns.map((x) => <TxnRow key={x.id} txn={x} t={t} lang={lang} onOpen={(held) => go({ name: 'hold', txn: held })} />)}</ul>
        )}
      </section>

      {SHOW_DEMO && <button className="link demo-link" onClick={() => setSheet('demo')}>🛠 {t('demoTools')}</button>}

      {sheet === 'add' && <AddMoney t={t} lang={lang} onClose={() => setSheet(null)} onDone={(b) => newBalance(b, t('moneyAdded'))} />}
      {sheet === 'cashout' && <CashOutSheet t={t} lang={lang} onClose={() => setSheet(null)} onDone={(b) => newBalance(b, t('cashedOutOk'))} />}
      {sheet === 'report' && <ReportSheet t={t} onClose={() => setSheet(null)} onDone={() => { setSheet(null); say(t('reportSent')) }} />}
      {sheet === 'demo' && <DemoTools t={t} onClose={() => setSheet(null)} onChanged={refreshAll} />}
    </div>
  )
}

function AddMoney({ t, lang, onClose, onDone }) {
  const [amount, setAmount] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const value = Number(amount)
  const valid = Number.isInteger(value) && value >= 10 && value <= 50000

  async function submit(event) {
    event.preventDefault()
    if (!valid) return setError(t('errInvalidAmount'))
    setBusy(true)
    try {
      onDone((await api.addMoney(value)).balance)
    } catch (e) {
      setError(errorText(e, t))
      setBusy(false)
    }
  }

  return (
    <Sheet title={t('addMoneyTitle')} onClose={onClose} closeLabel={t('close')}>
      <form onSubmit={submit} noValidate>
        <p className="muted">{t('addMoneyHelp')}</p>
        <label>
          {t('amount')}
          <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoFocus />
        </label>
        <div className="quick">
          {[500, 1000, 5000].map((v) => (
            <button type="button" key={v} className="chip" onClick={() => setAmount(String(v))}>{formatTaka(v, lang)}</button>
          ))}
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" type="submit" disabled={busy}>{busy ? t('working') : t('confirm')}</button>
      </form>
    </Sheet>
  )
}
