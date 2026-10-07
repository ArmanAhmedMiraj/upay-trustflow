import { useEffect, useRef } from 'react'

/**
 * The forecast calendar: one button per day the model can cover (about two months, with two festival rushes).
 * Tapping a day shows the forecast as it would have been made on that morning. Paydays and festival rushes are marked.
 */
export default function DayStrip({ days, selected, onPick, label = 'Pick a day', paydayText = 'Payday', festivalText = 'Festival' }) {
  const on = useRef(null)
  useEffect(() => { on.current?.scrollIntoView?.({ block: 'nearest', inline: 'center' }) }, [selected])
  if (!days?.length) return null
  return (
    <div className="daystrip" role="group" aria-label={label}>
      {days.map((d) => {
        const kind = d.festival_rush ? 'festival' : d.payday ? 'payday' : ''
        const text = `${d.weekday} ${d.day_of_month}${kind === 'festival' ? `, ${festivalText}` : kind === 'payday' ? `, ${paydayText}` : ''}`
        return (
          <button key={d.day} type="button" ref={selected === d.day ? on : null} aria-pressed={selected === d.day} aria-label={text}
            className={`day ${kind} ${selected === d.day ? 'on' : ''}`} onClick={() => onPick(d.day)}>
            <small>{d.weekday}</small>
            <strong>{d.day_of_month}</strong>
            <em>{kind === 'festival' ? festivalText : kind === 'payday' ? paydayText : ' '}</em>
          </button>
        )
      })}
    </div>
  )
}
