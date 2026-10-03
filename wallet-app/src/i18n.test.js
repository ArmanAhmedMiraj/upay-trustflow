import { describe, expect, it } from 'vitest'
import { ApiError } from './api.js'
import { STRINGS, errorText, makeT } from './i18n.js'

describe('translations', () => {
  it('has every English word in Bangla and vice versa', () => {
    expect(Object.keys(STRINGS.bn).sort()).toEqual(Object.keys(STRINGS.en).sort())
  })
  it('has no empty texts', () => {
    for (const lang of ['en', 'bn']) for (const [k, v] of Object.entries(STRINGS[lang])) expect(v.trim(), `${lang}.${k}`).not.toBe('')
  })
  it('writes Bangla in Bangla script', () => {
    const bangla = /[\u0980-\u09FF]/
    const keepLatin = new Set(['phonePlaceholder', 'language']) // 01XXXXXXXXX and the "English" switch label
    for (const [k, v] of Object.entries(STRINGS.bn)) if (!keepLatin.has(k)) expect(v, k).toMatch(bangla)
  })
  it('falls back to English, then to the key, never to blank', () => {
    expect(makeT('bn')('login')).toBe(STRINGS.bn.login)
    expect(makeT('xx')('login')).toBe(STRINGS.en.login)
    expect(makeT('en')('no_such_key')).toBe('no_such_key')
  })
})

describe('error messages', () => {
  const t = makeT('en')
  it('explains each known problem in plain words', () => {
    expect(errorText(new ApiError('network', 'x', 0), t)).toBe(STRINGS.en.errNetwork)
    expect(errorText(new ApiError('wrong_credentials', 'x', 401), t)).toBe(STRINGS.en.errWrongCredentials)
    expect(errorText(new ApiError('account_locked', 'x', 423), t)).toBe(STRINGS.en.errLocked)
  })
  it('never shows raw server text for unknown problems', () => {
    expect(errorText(new ApiError('something_new', 'Traceback: secret', 500), t)).toBe(STRINGS.en.errGeneric)
    expect(errorText(undefined, t)).toBe(STRINGS.en.errGeneric)
  })
})

describe('every text a screen asks for exists in both languages', () => {
  it('has no t("...") call without a translation', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const here = import.meta.dirname   // the folder of this file; correct on Windows and Linux
    const files = []
    const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).forEach((e) => {
      const full = path.join(dir, e.name)
      if (e.isDirectory()) walk(full)
      else if (/\.(jsx?|js)$/.test(e.name) && !/\.test\./.test(e.name)) files.push(full)
    })
    walk(here)
    const missing = []
    for (const file of files) {
      for (const m of fs.readFileSync(file, 'utf8').matchAll(/\bt\('([A-Za-z0-9_]+)'/g)) {
        if (!(m[1] in STRINGS.en) || !(m[1] in STRINGS.bn)) missing.push(`${path.basename(file)}: ${m[1]}`)
      }
    }
    expect(missing).toEqual([])
  })

  it('fills {placeholders} and leaves unknown ones alone', () => {
    expect(makeT('en')('sentOkFull', { amount: '৳800', name: 'Karim' })).toBe('You sent ৳800 to Karim')
    expect(makeT('bn')('holdsReleased', { n: 2 })).toBe('2টি হোল্ড মুক্ত হয়েছে')
    expect(makeT('en')('sentOkFull', { amount: '৳1' })).toBe('You sent ৳1 to {name}')
  })
})
