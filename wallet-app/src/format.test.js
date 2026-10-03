import { describe, expect, it } from 'vitest'
import { formatPhone, formatRemaining, formatTaka, groupLakh, newKey, formatWhen, isValidPhone, isValidPin, parseApiTime, toBanglaDigits } from './format.js'

describe('amounts', () => {
  it('groups digits the Bangladeshi way (lakhs)', () => {
    expect(formatTaka(1234, 'en')).toBe('৳1,234')
    expect(formatTaka(123456, 'en')).toBe('৳1,23,456')
  })
  it('groups every size of number correctly', () => {
    const cases = [[0, '0'], [7, '7'], [999, '999'], [1000, '1,000'], [12345, '12,345'], [100000, '1,00,000'],
      [1234567, '12,34,567'], [12345678, '1,23,45,678'], [-5000, '-5,000']]
    for (const [n, text] of cases) expect(groupLakh(n)).toBe(text)
  })
  it('uses Bangla digits in Bangla mode', () => {
    expect(formatTaka(1500, 'bn')).toBe('৳১,৫০০')
    expect(toBanglaDigits('Tk 5,000')).toBe('Tk ৫,০০০')
  })
})

describe('phone numbers and PINs', () => {
  it('accepts real Bangladeshi mobile numbers only', () => {
    for (const ok of ['01711000001', '01911234567', '01311234567']) expect(isValidPhone(ok)).toBe(true)
    for (const bad of ['', '1711000001', '01211000001', '0171100000', '017110000011', '+8801711000001', '0171100000a'])
      expect(isValidPhone(bad)).toBe(false)
  })
  it('requires exactly five digits for a PIN', () => {
    expect(isValidPin('12345')).toBe(true)
    for (const bad of ['', '1234', '123456', 'abcde', '12 45']) expect(isValidPin(bad)).toBe(false)
  })
  it('formats a number for reading', () => {
    expect(formatPhone('01711000001')).toBe('01711 000001')
  })
})

describe('times (always Bangladesh time)', () => {
  it('reads server times as UTC', () => {
    expect(parseApiTime('2026-10-03T21:28:14.066825').toISOString()).toBe('2026-10-03T21:28:14.066Z')
    expect(parseApiTime('2026-10-03T21:28:14Z').toISOString()).toBe('2026-10-03T21:28:14.000Z')
    expect(parseApiTime(null)).toBeNull()
  })
  it('shows Today, Yesterday and dates in Dhaka time', () => {
    const now = new Date('2026-10-04T10:00:00Z') // 4 Oct, 4:00 pm in Dhaka
    // 09:45 UTC is 3:45 pm in Dhaka, the same day
    expect(formatWhen('2026-10-04T09:45:00', 'en', now)).toBe('Today, 3:45 pm')
    // 18:30 UTC on 3 Oct is 12:30 am on 4 Oct in Dhaka: that is TODAY there, not yesterday
    expect(formatWhen('2026-10-03T18:30:00', 'en', now)).toBe('Today, 12:30 am')
    expect(formatWhen('2026-10-03T05:00:00', 'en', now)).toBe('Yesterday, 11:00 am')
    expect(formatWhen('2026-09-28T12:00:00', 'en', now)).toBe('28 Sept, 6:00 pm')
  })
  it('writes Bangla times completely in Bangla (digits and part of day)', () => {
    const now = new Date('2026-10-04T10:00:00Z')
    const bn = { today: 'আজ', yesterday: 'গতকাল' }
    expect(formatWhen('2026-10-04T09:45:00', 'bn', now, bn)).toBe('আজ, বিকেল ৩:৪৫')       // 3:45 pm in Dhaka
    expect(formatWhen('2026-10-04T05:05:00', 'bn', now, bn)).toBe('আজ, সকাল ১১:০৫')
    expect(formatWhen('2026-10-04T16:00:00', 'bn', new Date('2026-10-04T17:00:00Z'), bn)).toBe('আজ, রাত ১০:০০')
    expect(formatWhen('2026-10-03T18:30:00', 'bn', now, bn)).toBe('আজ, রাত ১২:৩০')
    expect(formatWhen('2026-10-04T06:30:00', 'bn', now, bn)).toBe('আজ, দুপুর ১২:৩০')
    expect(formatWhen('2026-10-03T23:30:00', 'bn', now, bn)).toBe('আজ, ভোর ৫:৩০')
    expect(formatWhen('2026-10-04T12:30:00', 'bn', new Date('2026-10-04T13:00:00Z'), bn)).toBe('আজ, সন্ধ্যা ৬:৩০')
    for (const iso of ['2026-10-04T06:30:00', '2026-10-04T08:30:00', '2026-10-04T11:30:00']) {
      expect(formatWhen(iso, 'bn', now, bn)).not.toMatch(/[a-z]/i)
    }
  })
  it('never prints 0:30 or 24:00 style hours in English', () => {
    const now = new Date('2026-10-04T10:00:00Z')
    expect(formatWhen('2026-10-03T18:05:00', 'en', now)).toBe('Today, 12:05 am')
    expect(formatWhen('2026-10-04T06:00:00', 'en', now)).toBe('Today, 12:00 pm')
  })
})

describe('countdown and keys', () => {
  it('formats the time left as mm:ss and never goes negative', () => {
    expect(formatRemaining(30 * 60 * 1000)).toBe('30:00')
    expect(formatRemaining(29 * 60 * 1000 + 59 * 1000)).toBe('29:59')
    expect(formatRemaining(61_000)).toBe('01:01')
    expect(formatRemaining(900)).toBe('00:01')
    expect(formatRemaining(0)).toBe('00:00')
    expect(formatRemaining(-5000)).toBe('00:00')
  })
  it('makes a different key every time', () => {
    const keys = new Set(Array.from({ length: 50 }, () => newKey()))
    expect(keys.size).toBe(50)
    for (const k of keys) expect(k.length).toBeGreaterThan(10)
  })
})
