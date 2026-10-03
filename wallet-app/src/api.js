// The only file that talks to the wallet server. Every call returns data or throws an ApiError.

export const API_BASE = import.meta.env?.VITE_WALLET_API ?? 'http://localhost:8000'

export class ApiError extends Error {
  constructor(code, detail, status, extra = {}) {
    super(detail)
    this.code = code
    this.detail = detail
    this.status = status
    Object.assign(this, extra)
  }
}

let token = null
let onUnauthorized = () => {}

export function setToken(value) {
  token = value
}
export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

async function request(method, path, body) {
  let response
  try {
    response = await fetch(API_BASE + path, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError('network', 'Cannot reach the wallet', 0)
  }
  let data = null
  try {
    data = await response.json()
  } catch {
    /* an empty or non-JSON reply */
  }
  if (!response.ok) {
    // validation errors from the server come as {detail: [...]}; our own errors as {code, detail}
    const code = data?.code ?? (response.status === 422 ? 'invalid_input' : 'error')
    const detail = typeof data?.detail === 'string' ? data.detail : 'Request failed'
    if (response.status === 401 && code === 'not_logged_in') onUnauthorized()
    throw new ApiError(code, detail, response.status, { risk: data?.risk })
  }
  return data
}

export const api = {
  login: (phone, pin) => request('POST', '/auth/login', { phone, pin }),
  register: (phone, name, pin) => request('POST', '/auth/register', { phone, name, pin }),
  logout: () => request('POST', '/auth/logout'),
  me: () => request('GET', '/me'),
  transactions: (limit = 20) => request('GET', `/wallet/transactions?limit=${limit}`),
  addMoney: (amount) => request('POST', '/wallet/add-money', { amount }),
  preview: (recipient_phone, amount, behavior, safety_answers) =>
    request('POST', '/wallet/send/preview', { recipient_phone, amount, behavior, safety_answers }),
  send: (payload) => request('POST', '/wallet/send', payload),
  cancelHold: (id) => request('POST', `/wallet/transactions/${id}/cancel`),
  cashOut: (agent_phone, amount, pin, idempotency_key) => request('POST', '/wallet/cash-out', { agent_phone, amount, pin, idempotency_key }),
  inbox: () => request('GET', '/sms/inbox'),
  report: (phone, reason) => request('POST', '/wallet/report', { phone, reason: reason || undefined }),
  fakeSms: (amount, from_number) => request('POST', '/demo/fake-sms', { amount, from_number }),
  releaseHoldsNow: () => request('POST', '/demo/release-holds-now'),
  impact: (hours = 168) => request('GET', `/analyst/impact?hours=${hours}`),
  modelReport: () => request('GET', '/analyst/model-report'),
  resetDemo: () => request('POST', '/demo/reset'),
  analystCases: (status = 'held', limit = 100) => request('GET', `/analyst/cases?status=${status}&limit=${limit}`),
  approve: (id, note) => request('POST', `/analyst/cases/${id}/approve`, { note }),
  reject: (id, note) => request('POST', `/analyst/cases/${id}/reject`, { note }),
}
