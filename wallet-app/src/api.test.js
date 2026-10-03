import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, setToken, setUnauthorizedHandler } from './api.js'

function reply(status, body) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) })
}

beforeEach(() => {
  setToken(null)
  setUnauthorizedHandler(() => {})
})
afterEach(() => vi.restoreAllMocks())

describe('api client', () => {
  it('sends JSON and, once logged in, the bearer token', async () => {
    const fetchMock = vi.fn(() => reply(200, { token: 'abc', user: { name: 'Rahim' } }))
    vi.stubGlobal('fetch', fetchMock)
    await api.login('01711000001', '12345')
    let [url, options] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/auth\/login$/)
    expect(JSON.parse(options.body)).toEqual({ phone: '01711000001', pin: '12345' })
    expect(options.headers.Authorization).toBeUndefined()

    setToken('abc')
    await api.me()
    ;[url, options] = fetchMock.mock.calls[1]
    expect(options.method).toBe('GET')
    expect(options.headers.Authorization).toBe('Bearer abc')
  })

  it('turns server errors into ApiError with code, text and status', async () => {
    vi.stubGlobal('fetch', vi.fn(() => reply(401, { code: 'wrong_credentials', detail: 'Wrong phone number or PIN' })))
    const error = await api.login('01711000001', '00000').catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect([error.code, error.status, error.detail]).toEqual(['wrong_credentials', 401, 'Wrong phone number or PIN'])
  })

  it('handles validation errors and empty replies without crashing', async () => {
    vi.stubGlobal('fetch', vi.fn(() => reply(422, { detail: [{ msg: 'field required' }] })))
    expect(await api.addMoney('x').catch((e) => e.code)).toBe('invalid_input')
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 500, json: () => Promise.reject(new Error('not json')) })))
    expect(await api.me().catch((e) => e.code)).toBe('error')
  })

  it('reports an unreachable server as a network error', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))))
    const error = await api.me().catch((e) => e)
    expect([error.code, error.status]).toEqual(['network', 0])
  })

  it('tells the app when the session is no longer valid', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    vi.stubGlobal('fetch', vi.fn(() => reply(401, { code: 'not_logged_in', detail: 'expired' })))
    await api.me().catch(() => {})
    expect(handler).toHaveBeenCalledTimes(1)
    // a wrong PIN is also a 401, but it must NOT log anyone out
    vi.stubGlobal('fetch', vi.fn(() => reply(401, { code: 'wrong_credentials', detail: 'x' })))
    await api.login('01711000001', '0').catch(() => {})
    expect(handler).toHaveBeenCalledTimes(1)
  })
})

describe('every call a screen makes exists', () => {
  it('has an api function for each api.xxx(...) used in the app', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const here = import.meta.dirname   // the folder of this file; correct on Windows and Linux
    const used = new Set()
    const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).forEach((e) => {
      const full = path.join(dir, e.name)
      if (e.isDirectory()) walk(full)
      else if (/\.jsx?$/.test(e.name) && !/\.test\./.test(e.name) && e.name !== 'api.js') {
        for (const m of fs.readFileSync(full, 'utf8').matchAll(/\bapi\.([A-Za-z]+)\(/g)) used.add(m[1])
      }
    })
    walk(here)
    expect([...used].filter((name) => typeof api[name] !== 'function')).toEqual([])
    expect(used.size).toBeGreaterThan(10)
  })

  it('sends each request to the address the wallet server really has', async () => {
    const calls = []
    vi.stubGlobal('fetch', vi.fn((url, options) => { calls.push(`${options.method} ${url.replace(/^.*?:8000/, '')}`); return reply(200, {}) }))
    await api.cancelHold(77)
    await api.cashOut('01811000001', 500, '12345', 'k')
    await api.preview('01711000002', 800, {}, undefined)
    await api.send({})
    await api.inbox()
    await api.report('01711999999', 'x')
    await api.fakeSms(5000, '01711999999')
    await api.releaseHoldsNow()
    expect(calls).toEqual([
      'POST /wallet/transactions/77/cancel', 'POST /wallet/cash-out', 'POST /wallet/send/preview', 'POST /wallet/send',
      'GET /sms/inbox', 'POST /wallet/report', 'POST /demo/fake-sms', 'POST /demo/release-holds-now',
    ])
  })
})
