// Formatting helpers: taka amounts, phone numbers and times, the way Bangladeshis read them.

const BD_PHONE = /^01[3-9]\d{8}$/

export function isValidPhone(phone) {
  return BD_PHONE.test(phone)
}

export function isValidPin(pin) {
  return /^\d{5}$/.test(pin)
}

/** 1234567 -> "12,34,567": Bangladesh groups the last three digits, then pairs (lakh, crore). Browser-independent. */
export function groupLakh(n) {
  const sign = n < 0 ? '-' : ''
  const digits = String(Math.abs(Math.trunc(n)))
  if (digits.length <= 3) return sign + digits
  const head = digits.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',')
  return `${sign}${head},${digits.slice(-3)}`
}

/** 123456 -> "৳1,23,456". In Bangla mode the digits are Bangla too: "৳১,২৩,৪৫৬". */
export function formatTaka(amount, lang = 'en') {
  const text = groupLakh(amount)
  return '৳' + (lang === 'bn' ? toBanglaDigits(text) : text)
}

const BN_DIGITS = '০১২৩৪৫৬৭৮৯'
export function toBanglaDigits(text) {
  return String(text).replace(/\d/g, (d) => BN_DIGITS[Number(d)])
}

/** The API sends UTC times without a "Z"; this reads them as UTC. */
export function parseApiTime(iso) {
  if (!iso) return null
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z')
}

const dayFormat = (lang) =>
  new Intl.DateTimeFormat(lang === 'bn' ? 'bn-BD' : 'en-GB', { timeZone: 'Asia/Dhaka', day: 'numeric', month: 'short' })
const hourFormat = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Dhaka', hour: 'numeric', hour12: false })
const minuteFormat = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Dhaka', minute: '2-digit' })

/** "3:45 pm" in English, "বিকেল ৩:৪৫" in Bangla. Built by hand so every browser prints the same thing. */
function clockText(d, lang) {
  const h24 = Number(hourFormat.format(d)) % 24
  const minutes = minuteFormat.format(d).padStart(2, '0')
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12
  if (lang !== 'bn') return `${h12}:${minutes} ${h24 < 12 ? 'am' : 'pm'}`
  // everyday usage: ভোর 4-6, সকাল 6-12, দুপুর 12-3, বিকেল 3-6, সন্ধ্যা 6-8, রাত 8 pm-4 am
  const part = h24 < 4 ? 'রাত' : h24 < 6 ? 'ভোর' : h24 < 12 ? 'সকাল' : h24 < 15 ? 'দুপুর' : h24 < 18 ? 'বিকেল' : h24 < 20 ? 'সন্ধ্যা' : 'রাত'
  return `${part} ${toBanglaDigits(`${h12}:${minutes}`)}`
}
const dayKey = (d) =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Dhaka' }).format(d) // 2026-10-04

/** "Today, 3:45 pm", "Yesterday, 11:02 am" or "2 Oct, 6:30 pm", always in Bangladesh time. */
export function formatWhen(iso, lang = 'en', now = new Date(), words = { today: 'Today', yesterday: 'Yesterday' }) {
  const d = parseApiTime(iso)
  if (!d) return ''
  const time = clockText(d, lang)
  const yesterday = new Date(now.getTime() - 24 * 3600 * 1000)
  if (dayKey(d) === dayKey(now)) return `${words.today}, ${time}`
  if (dayKey(d) === dayKey(yesterday)) return `${words.yesterday}, ${time}`
  return `${dayFormat(lang).format(d)}, ${time}`
}

/** 01711000001 -> "01711 000001" */
export function formatPhone(phone) {
  return phone && phone.length === 11 ? `${phone.slice(0, 5)} ${phone.slice(5)}` : phone
}

/** Time left until a hold ends, as "29:41" (or "0:00" once it is over). */
export function formatCountdown(releaseIso, now = new Date()) {
  const end = parseApiTime(releaseIso)
  if (!end) return '0:00'
  const left = Math.max(0, Math.round((end.getTime() - now.getTime()) / 1000))
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`
}

export function secondsLeft(releaseIso, now = new Date()) {
  const end = parseApiTime(releaseIso)
  return end ? Math.max(0, Math.round((end.getTime() - now.getTime()) / 1000)) : 0
}

/** 1625000 ms -> "27:05". Never negative. */
export function formatRemaining(ms) {
  const total = Math.max(0, Math.ceil(ms / 1000))
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

/** A fresh key for one send attempt, so a double tap or a retry can never move money twice. */
export function newKey() {
  return globalThis.crypto?.randomUUID?.() ?? `k-${Date.now()}-${Math.random().toString(16).slice(2)}`
}
