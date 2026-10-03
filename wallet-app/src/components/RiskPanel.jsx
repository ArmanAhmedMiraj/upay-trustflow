import RiskMeter from './RiskMeter.jsx'
import { toBanglaDigits } from '../format.js'

/** The warning text: first line is the headline, the rest is the explanation. */
export function WarningText({ bn, en, lang }) {
  const text = (lang === 'bn' ? bn : en) || bn || en
  if (!text) return null
  const [headline, ...rest] = text.split('\n')
  return (
    <div className="warning-text">
      <strong>{headline}</strong>
      {rest.length > 0 && <p>{rest.join(' ')}</p>}
    </div>
  )
}

/** Everything Shield tells the customer about one transfer. */
export default function RiskPanel({ risk, questions, answers, onAnswer, busy, t, lang }) {
  if (!risk.shield_available) return <p className="notice info">{t('shieldOff')}</p>
  if (risk.tier === 'low') return <p className="notice good">✓ {t('noRiskSigns')}</p>

  const showQuestions = questions.length > 0
  const num = (n) => (lang === 'bn' ? toBanglaDigits(n) : n)
  return (
    <div className={`risk-panel ${risk.tier}`}>
      <RiskMeter pct={risk.risk_pct} tier={risk.tier} t={t} lang={lang} />
      {risk.risk_before_pct != null && risk.risk_before_pct !== risk.risk_pct && (
        <p className="risk-change">{t('riskWas')} {num(risk.risk_before_pct)}% → {t('riskNow')} <strong>{num(risk.risk_pct)}%</strong></p>
      )}
      <WarningText bn={risk.message_bn} en={risk.message_en} lang={lang} />

      {showQuestions && (
        <div className="questions" aria-busy={busy}>
          <h3>{t('answerQuestions')}</h3>
          {questions.map((q) => (
            <fieldset key={q.id}>
              <legend>{lang === 'bn' ? q.bn : q.en}</legend>
              <div className="answer-row">
                {['yes', 'no', 'not_sure'].map((a) => (
                  <button key={a} type="button" disabled={busy} className={`answer ${answers[q.id] === a ? 'on' : ''}`}
                    aria-pressed={answers[q.id] === a} onClick={() => onAnswer(q.id, a)}>
                    {t(a === 'not_sure' ? 'notSure' : a)}
                  </button>
                ))}
              </div>
            </fieldset>
          ))}
        </div>
      )}

      {risk.reasons?.length > 0 && (
        <details className="why">
          <summary>{t('whyShown')}</summary>
          <ul>
            {risk.reasons.map((r, i) => (
              <li key={i}>
                <span className={`tag ${r.source}`}>{r.source === 'rule' ? t('verifiedFact') : t('learnedSignal')}</span> {r.text}
              </li>
            ))}
          </ul>
          {lang === 'bn' && <small>{t('reasonsEnglish')}</small>}
        </details>
      )}
    </div>
  )
}
