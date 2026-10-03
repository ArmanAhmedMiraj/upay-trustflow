import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api.js'
import Console from './Console.jsx'

vi.mock('../api.js', async (importOriginal) => {
  const real = await importOriginal()
  return { ...real, api: { analystCases: vi.fn(), approve: vi.fn(), reject: vi.fn(), impact: vi.fn(), modelReport: vi.fn(), resetDemo: vi.fn() } }
})
import { api } from '../api.js'

const analyst = { id: 9, name: 'Nadia Rahman (Fraud Analyst)', role: 'analyst' }
const CASE = {
  id: 101, status: 'held', amount: 5000, risk_pct: 100, risk_tier: 'very_high', scam_type: 'return_by_mistake',
  reasons: [{ source: 'rule', text: 'An SMS says money was received, but the upay ledger shows no such credit' }, { source: 'model', text: 'First transfer to this number' }],
  sender: { name: 'Rahim Uddin', phone: '01711000001' }, recipient: { name: 'Jamal Hossain', phone: '01711999999' },
  created_at: '2026-10-04T08:00:00', release_at: new Date(Date.now() + 25 * 60 * 1000).toISOString().slice(0, 19), review_note: null,
}
const IMPACT = {
  window_hours: 168, checks: 20, tiers: { low: 14, note: 2, high: 1, very_high: 3 }, flagged: 4, friction_rate: 0.2,
  outcomes: {
    walked_away: { count: 1, bdt: 5000 }, cancelled: { count: 1, bdt: 6000 }, rejected: { count: 1, bdt: 7000 },
    on_hold: { count: 0, bdt: 0 }, released_after_hold: { count: 0, bdt: 0 }, sent_after_warning: { count: 1, bdt: 4000 } },
  heeded: 3, heeded_rate: 0.75, kept_back_bdt: 18000, released_bdt: 4000, on_hold_bdt: 0, open_cases: 0, reports: 5, reported_wallets: 2, shield_available_rate: 1,
}
const REPORT = {
  test_transfers: 50960, test_fraud: 943, fraud_caught_pct: 0.72, fraud_value_caught_pct: 0.82, genuine_disturbed_pct: 0.002, precision: 0.87,
  ranking: { rules_only_baseline: { recall_at_2pct_friction: 0.34 }, logistic_regression_baseline: { recall_at_2pct_friction: 0.84 }, lightgbm_raw: { recall_at_2pct_friction: 0.84 }, full_system_with_rules: { recall_at_2pct_friction: 0.84 } },
  by_scam_type: { return_by_mistake: 0.78, fake_officer: 0.7 }, calibration_error: 0.002,
  impact_by_heeding_rate: { '0.3': { fraud_bdt_stopped: 974087, net_benefit_bdt: 972556 }, '0.5': { fraud_bdt_stopped: 1623478, net_benefit_bdt: 1621948 } },
  evasion: { none: 0.72, aged_wallet: 0.25 }, latency_ms: 4.1,
}

function setup(props = {}) {
  const onLogout = vi.fn(), onDemoReset = vi.fn()
  render(<Console user={analyst} onLogout={onLogout} onDemoReset={onDemoReset} {...props} />)
  return { onLogout, onDemoReset, user: userEvent.setup() }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.analystCases.mockResolvedValue({ cases: [CASE] })
  api.impact.mockResolvedValue(IMPACT)
  api.modelReport.mockResolvedValue({ report: REPORT })
})
afterEach(() => vi.useRealTimers())

describe('Cases', () => {
  it('shows a held case with who, how much, the risk, the scam type and the reasons', async () => {
    setup()
    const card = await screen.findByRole('article')
    expect(card).toHaveTextContent('Case #101')
    expect(card).toHaveTextContent('Rahim Uddin')
    expect(card).toHaveTextContent('Jamal Hossain')
    expect(card).toHaveTextContent('৳5,000')
    expect(card).toHaveTextContent('100%')
    expect(card).toHaveTextContent("Return money 'sent by mistake'")
    expect(within(card).getByText('Verified fact')).toBeInTheDocument()
    expect(card).toHaveTextContent('upay ledger shows no such credit')
    expect(card).toHaveTextContent(/releases automatically in \d\d:\d\d/)
    expect(api.analystCases).toHaveBeenCalledWith('held', 100)
  })

  it('approves with the typed note and refreshes the list', async () => {
    api.approve.mockResolvedValue({})
    const { user } = setup()
    await user.type(await screen.findByLabelText('Note for case 101'), 'Genuine rent')
    api.analystCases.mockResolvedValue({ cases: [] })
    await user.click(screen.getByRole('button', { name: /Approve/ }))
    await waitFor(() => expect(api.approve).toHaveBeenCalledWith(101, 'Genuine rent'))
    expect(await screen.findByText(/No cases right now/)).toBeInTheDocument()
  })

  it('rejects and refunds', async () => {
    api.reject.mockResolvedValue({})
    const { user } = setup()
    await user.click(await screen.findByRole('button', { name: /Reject/ }))
    await waitFor(() => expect(api.reject).toHaveBeenCalledWith(101, undefined))
  })

  it('explains it clearly if another analyst already decided the case', async () => {
    api.approve.mockRejectedValue(new ApiError('already_decided', 'x', 409))
    const { user } = setup()
    await user.click(await screen.findByRole('button', { name: /Approve/ }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(api.analystCases.mock.calls.length).toBeGreaterThan(1)       // it reloads to show the truth
  })

  it('has no decision buttons on cases that are already closed', async () => {
    api.analystCases.mockResolvedValue({ cases: [{ ...CASE, status: 'rejected', review_note: 'Known mule', release_at: null }] })
    const { user } = setup()
    await user.selectOptions(await screen.findByLabelText('Show'), 'all')
    await screen.findByText('Note: Known mule')
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument()
    expect(api.analystCases).toHaveBeenLastCalledWith('all', 100)
  })

  it('refreshes by itself so new cases appear while presenting', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
    setup()
    await screen.findByRole('article')
    const before = api.analystCases.mock.calls.length
    await act(async () => { await vi.advanceTimersByTimeAsync(11000) })
    expect(api.analystCases.mock.calls.length).toBeGreaterThan(before)
  })
})

describe('Impact', () => {
  async function openImpact() {
    const view = setup()
    await view.user.click(screen.getByRole('tab', { name: 'Impact' }))
    await screen.findByText('Transfers checked')
    return view
  }

  it('shows the measured numbers in plain words', async () => {
    await openImpact()
    const kpi = (label) => screen.getByText(label).closest('.kpi')
    expect(kpi('Transfers checked')).toHaveTextContent('20')
    expect(kpi('Interrupted (warning or hold)')).toHaveTextContent('20.0%')
    expect(kpi('Kept back from flagged wallets')).toHaveTextContent('৳18,000')
    expect(kpi('Customers who heeded the warning')).toHaveTextContent('75%')
    expect(kpi('Went through after a warning')).toHaveTextContent('৳4,000')
    expect(kpi('Numbers reported by customers')).toHaveTextContent('5')
    expect(screen.getByText('Saw the warning and did not send').closest('.bar-row')).toHaveTextContent('1 · ৳5,000')
  })

  it('shows the offline evaluation and is honest that it proves the method only', async () => {
    await openImpact()
    expect(await screen.findByText(/prove the method/)).toBeInTheDocument()
    expect(screen.getByText('Fraud caught (by count)').closest('.kpi')).toHaveTextContent('72.0%')
    expect(screen.getByText('Genuine transfers disturbed').closest('.kpi')).toHaveTextContent('0.20%')
    expect(screen.getByText('Simple rules').closest('.bar-row')).toHaveTextContent('34%')
    expect(screen.getByText(/assumption, so three values/)).toBeInTheDocument()
  })

  it('does not divide by zero before anything has happened', async () => {
    api.impact.mockResolvedValue({ ...IMPACT, checks: 0, flagged: 0, friction_rate: 0, heeded: 0, heeded_rate: 0, kept_back_bdt: 0, released_bdt: 0,
      tiers: { low: 0, note: 0, high: 0, very_high: 0 }, outcomes: Object.fromEntries(Object.keys(IMPACT.outcomes).map((k) => [k, { count: 0, bdt: 0 }])) })
    await openImpact()
    expect(screen.getByText('No flagged transfers in this period yet.')).toBeInTheDocument()
    expect(screen.getByText('Customers who heeded the warning').closest('.kpi')).toHaveTextContent('–')
  })

  it('changes the period', async () => {
    const { user } = await openImpact()
    await user.selectOptions(screen.getByLabelText('Period'), '24')
    await waitFor(() => expect(api.impact).toHaveBeenLastCalledWith(24))
  })
})

describe('Header', () => {
  it('needs a second click before it wipes the demo, then asks the app to log out', async () => {
    api.resetDemo.mockResolvedValue({ users: 2000 })
    const { user, onDemoReset } = setup()
    await user.click(screen.getByRole('button', { name: 'Reset demo' }))
    expect(api.resetDemo).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Click again to wipe and reset' }))
    await waitFor(() => expect(api.resetDemo).toHaveBeenCalledTimes(1))
    expect(onDemoReset).toHaveBeenCalled()
  })

  it('logs out', async () => {
    const { user, onLogout } = setup()
    await user.click(screen.getByRole('button', { name: 'Log out' }))
    expect(onLogout).toHaveBeenCalled()
  })
})
