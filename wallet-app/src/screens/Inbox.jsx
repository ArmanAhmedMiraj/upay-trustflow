import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { errorText } from '../i18n.js'
import { formatWhen } from '../format.js'
import ReportSheet from '../components/ReportSheet.jsx'

/** The SMS inbox. Messages that are not from "upay" are flagged: scammers write fake "money received" texts. */
export default function Inbox({ t, lang, onBack }) {
  const [messages, setMessages] = useState(null)
  const [error, setError] = useState('')
  const [reportPhone, setReportPhone] = useState(null)
  const [flash, setFlash] = useState('')

  useEffect(() => {
    api.inbox().then((r) => setMessages(r.messages)).catch((e) => setError(errorText(e, t)))
  }, [t])

  const words = { today: t('today'), yesterday: t('yesterday') }
  return (
    <div className="screen flow">
      <header className="flow-head">
        <button className="link" onClick={onBack}>‹ {t('back')}</button>
        <h2>{t('inboxTitle')}</h2>
        <span />
      </header>
      {flash && <p className="flash" role="status">{flash}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {messages === null && !error && <p className="muted">{t('working')}</p>}
      {messages && messages.length === 0 && <p className="muted">{t('noMessages')}</p>}
      <ul className="sms-list">
        {(messages ?? []).map((m) => (
          <li key={m.id} className={`sms ${m.official ? 'official' : 'unofficial'}`}>
            <div className="sms-head">
              <strong>{m.from}</strong>
              <span className={`tag ${m.official ? 'rule' : 'warn'}`}>{m.official ? '✓ ' + t('officialUpay') : '⚠ ' + t('notFromUpay')}</span>
            </div>
            <p>{m.text}</p>
            <small>{formatWhen(m.created_at, lang, new Date(), words)}</small>
            {!m.official && (
              <>
                <p className="sms-warning">{t('notFromUpayHelp')}</p>
                <button className="primary ghost danger-text" onClick={() => setReportPhone(m.from)}>{t('reportNumber')}</button>
              </>
            )}
          </li>
        ))}
      </ul>
      {reportPhone && <ReportSheet t={t} defaultPhone={reportPhone} onClose={() => setReportPhone(null)}
        onDone={() => { setReportPhone(null); setFlash(t('reportSent')) }} />}
    </div>
  )
}
