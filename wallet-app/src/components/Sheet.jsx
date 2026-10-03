// A panel that slides up from the bottom of the phone.
export default function Sheet({ title, onClose, closeLabel = 'Close', children }) {
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <h2>{title}</h2>
          <button className="icon" onClick={onClose} aria-label={closeLabel}>×</button>
        </div>
        {children}
      </div>
    </div>
  )
}
