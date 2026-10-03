import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { errorText } from '../i18n.js'
import TxnRow from '../components/TxnRow.jsx'

export default function History({ t, lang, onBack, onOpenHold }) {
  const [txns, setTxns] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.transactions(60).then((r) => setTxns(r.transactions)).catch((e) => setError(errorText(e, t)))
  }, [t])

  return (
    <div className="screen flow">
      <header className="flow-head">
        <button className="link" onClick={onBack}>‹ {t('back')}</button>
        <h2>{t('history')}</h2>
        <span />
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {txns === null && !error && <p className="muted">{t('working')}</p>}
      {txns && txns.length === 0 && <p className="muted">{t('noActivity')}</p>}
      {txns && txns.length > 0 && <ul className="txn-list">{txns.map((x) => <TxnRow key={x.id} txn={x} t={t} lang={lang} onOpen={onOpenHold} />)}</ul>}
    </div>
  )
}
