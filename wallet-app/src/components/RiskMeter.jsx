import { toBanglaDigits } from '../format.js'

export const TIER_LABEL = { low: 'tierLow', note: 'tierNote', high: 'tierHigh', very_high: 'tierVeryHigh' }

/** The live security-risk meter: a bar, a big percentage and a plain-word level. */
export default function RiskMeter({ pct, tier, t, lang }) {
  const shown = lang === 'bn' ? toBanglaDigits(pct) : String(pct)
  return (
    <div className={`meter ${tier}`} role="meter" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={t('securityRisk')}>
      <div className="meter-top">
        <span>{t('securityRisk')}</span>
        <strong>{shown}%</strong>
      </div>
      <div className="meter-bar"><div className="meter-fill" style={{ width: `${Math.max(2, pct)}%` }} /></div>
      <div className="meter-level">{t(TIER_LABEL[tier] ?? 'tierLow')}</div>
    </div>
  )
}
