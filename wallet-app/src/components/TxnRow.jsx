import { formatTaka, formatWhen } from '../format.js'

export function describe(txn, t) {
  const who = txn.counterparty_name ?? ''
  if (txn.kind === 'add_money') return t('addedMoney')
  if (txn.kind === 'cash_out') return `${t('cashedOut')} ${who}`.trim()
  return txn.direction === 'out' ? `${t('sent')} ${who}`.trim() : `${t('received')} ${who}`.trim()
}

const STATUS_LABEL = { held: 'statusHeld', cancelled: 'statusCancelled', rejected: 'statusRejected' }

export default function TxnRow({ txn, t, lang, onOpen }) {
  const out = txn.direction === 'out'
  const done = txn.status === 'completed'
  const statusKey = STATUS_LABEL[txn.status]
  const clickable = txn.status === 'held' && onOpen
  const open = clickable ? { role: 'button', tabIndex: 0, onClick: () => onOpen(txn), onKeyDown: (e) => (e.key === 'Enter' || e.key === ' ') && onOpen(txn) } : {}
  return (
    <li className={`txn ${done ? '' : txn.status} ${clickable ? 'clickable' : ''}`} {...open}>
      <div className={`avatar ${out ? 'out' : 'in'}`} aria-hidden="true">{out ? '↑' : '↓'}</div>
      <div className="txn-main">
        <strong>{describe(txn, t)}</strong>
        <small>
          {formatWhen(txn.created_at, lang, new Date(), { today: t('today'), yesterday: t('yesterday') })}
          {statusKey && <span className={`badge ${txn.status}`}>{t(statusKey)}</span>}
          {clickable && <span className="manage">{t('tapToManage')} ›</span>}
        </small>
      </div>
      <div className={`txn-amount ${out ? 'neg' : 'pos'} ${done ? '' : 'faded'}`}>
        {out ? '−' : '+'}{formatTaka(txn.amount, lang)}
      </div>
    </li>
  )
}
