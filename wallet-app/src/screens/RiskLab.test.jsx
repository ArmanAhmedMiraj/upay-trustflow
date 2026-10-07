import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RiskLab from './RiskLab.jsx'

vi.mock('../api.js', async (importOriginal) => {
  const real = await importOriginal()
  return { ...real, api: { labTransactions: vi.fn(), labFilters: vi.fn(), labExplain: vi.fn(), labReport: vi.fn() } }
})
import { api } from '../api.js'

const E1 = { id: 11, transaction_id: 101, created_at: '2026-10-07T08:30:00', amount: 3000, status: 'held', risk_pct: 99.9, tier: 'very_high',
  sender: { name: 'Rahim Uddin', phone: '01711000001' }, recipient: { name: 'Rina Sultana', phone: '01613308841' } }
const E2 = { id: 10, transaction_id: 100, created_at: '2026-10-07T08:10:00', amount: 500, status: 'completed', risk_pct: 0.1, tier: 'low',
  sender: { name: 'Nusrat Jahan', phone: '01711000005' }, recipient: { name: 'Shahin Grocery', phone: '01711000004' } }
const OPTIONS = {
  senders: [{ phone: '01711000001', name: 'Rahim Uddin' }, { phone: '01711000005', name: 'Nusrat Jahan' }],
  recipients: [{ phone: '01613308841', name: 'Rina Sultana' }, { phone: '01711000004', name: 'Shahin Grocery' }], total: 2,
}
const row = (signal, side, label, points, text, present = true) => ({ signal, side, label, points, text, present, muted: false, value: 1, why: '' })
const RESULT = {
  risk_pct: 99.9, tier: 'very_high', action: 'hold_30min', baseline_pct: 0.5, signals_present: 7, muted: [],
  tier_thresholds_pct: { note: 9.8, high: 27.8, very_high: 61.9 },
  sides: { sender: 2.5, recipient: 80.9, pair: 11.6 },
  combination: { typical_transfer_pct: 0, sender_signals_only_pct: 1.7, recipient_signals_only_pct: 90.1, all_signals_pct: 99.9, extra_from_combining_points: 0.1 },
  contributions: [
    row('r_wallets_per_nid', 'recipient', 'Wallets under the same ID', 14.2, '4 wallets registered under the same ID'),
    row('s_on_call', 'sender', 'Sender is on a phone call', 6.1, 'Sender is on a phone call while sending'),
    row('s_history_count', 'sender', "Sender's transfer history", -1.2, '12 earlier transfers on record', false),
  ],
}
const REPORT = {
  data: { test: 40000, scams_in_test: 2000 },
  which_sides_are_needed: {
    'sender signals only': { signals: 10, pr_auc: 0.25, caught_at_hold_tier: 0.06 }, 'recipient signals only': { signals: 15, pr_auc: 0.58, caught_at_hold_tier: 0.31 },
    'sender + recipient (no link signals)': { signals: 25, pr_auc: 0.7, caught_at_hold_tier: 0.42 }, 'all three sides': { signals: 31, pr_auc: 0.8, caught_at_hold_tier: 0.54 },
  },
  score_spread: { scams_scoring_99_or_more_pct: 10.6, scam_score_percentiles: { 25: 23.5, 75: 94.3 } },
  headline: { genuine_disturbed_pct_at_hold: 0.27, calibration_error: 0.0045 },
}

beforeEach(() => {
  vi.clearAllMocks()
  api.labTransactions.mockResolvedValue({ entries: [E1, E2], total_recorded: 2 })
  api.labFilters.mockResolvedValue(OPTIONS)
  api.labExplain.mockResolvedValue({ ...RESULT, entry: E1 })
  api.labReport.mockResolvedValue(REPORT)
})

describe('Risk Lab: the log of real transfers', () => {
  it('is empty, and says so, until a real transfer happens', async () => {
    api.labTransactions.mockResolvedValue({ entries: [], total_recorded: 0 })
    api.labFilters.mockResolvedValue({ senders: [], recipients: [], total: 0 })
    render(<RiskLab />)
    expect(await screen.findByText('No transactions yet.')).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'Real transfers' })).not.toBeInTheDocument()
    expect(screen.getByText('0 shown of 0 recorded')).toBeInTheDocument()
  })

  it('lists each real transfer with names, numbers, amount, risk and outcome', async () => {
    render(<RiskLab />)
    const table = await screen.findByRole('table', { name: 'Real transfers' })
    const first = within(table).getAllByRole('row')[1]
    expect(first).toHaveTextContent('Rahim Uddin')
    expect(first).toHaveTextContent('01711 000001')
    expect(first).toHaveTextContent('Rina Sultana')
    expect(first).toHaveTextContent('01613 308841')
    expect(first).toHaveTextContent('99.9% · Very high')
    expect(first).toHaveTextContent('Held')
    expect(within(table).getAllByRole('row')[2]).toHaveTextContent('Sent')
    expect(screen.getByText('2 shown of 2 recorded')).toBeInTheDocument()
  })

  it('shows times in Bangladesh time', async () => {
    render(<RiskLab />)
    const table = await screen.findByRole('table', { name: 'Real transfers' })
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('14:30:00')      // 08:30 UTC = 14:30 in Dhaka
  })

  it('offers only the numbers and names that really appear, in dropdowns', async () => {
    render(<RiskLab />)
    await screen.findByRole('table', { name: 'Real transfers' })
    const sender = screen.getByLabelText('Sender number')
    expect(within(sender).getAllByRole('option').map((o) => o.textContent)).toEqual(['All senders', '01711 000001 · Rahim Uddin', '01711 000005 · Nusrat Jahan'])
    const recipient = screen.getByLabelText('Recipient number')
    expect(within(recipient).getAllByRole('option')).toHaveLength(3)
  })

  it('asks the server to filter by sender number, recipient number, name and date/time', async () => {
    const user = userEvent.setup()
    render(<RiskLab />)
    await screen.findByRole('table', { name: 'Real transfers' })
    await user.selectOptions(screen.getByLabelText('Sender number'), '01711000001')
    await waitFor(() => expect(api.labTransactions).toHaveBeenLastCalledWith('sender=01711000001'))
    await user.selectOptions(screen.getByLabelText('Recipient number'), '01613308841')
    await waitFor(() => expect(api.labTransactions).toHaveBeenLastCalledWith('sender=01711000001&recipient=01613308841'))
    await user.type(screen.getByLabelText('Registered name'), 'Rina')
    await waitFor(() => expect(api.labTransactions).toHaveBeenLastCalledWith(expect.stringContaining('name=Rina')))
    await user.type(screen.getByLabelText('From (Bangladesh time)'), '2026-10-07T14:00')
    await waitFor(() => expect(api.labTransactions).toHaveBeenLastCalledWith(expect.stringContaining('since=2026-10-07T14%3A00')))
    await user.type(screen.getByLabelText('To (Bangladesh time)'), '2026-10-07T15:00')
    await waitFor(() => expect(api.labTransactions).toHaveBeenLastCalledWith(expect.stringContaining('until=2026-10-07T15%3A00')))
  })

  it('says no transfer matches when filters leave nothing, and can clear them', async () => {
    const user = userEvent.setup()
    render(<RiskLab />)
    await screen.findByRole('table', { name: 'Real transfers' })
    api.labTransactions.mockResolvedValue({ entries: [], total_recorded: 2 })
    await user.type(screen.getByLabelText('Registered name'), 'nobody')
    expect(await screen.findByText('No transfers match these filters.')).toBeInTheDocument()
    api.labTransactions.mockResolvedValue({ entries: [E1, E2], total_recorded: 2 })
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(await screen.findByRole('table', { name: 'Real transfers' })).toBeInTheDocument()
    expect(screen.getByLabelText('Registered name')).toHaveValue('')
  })

  it('explains a transfer signal by signal when it is opened', async () => {
    const user = userEvent.setup()
    render(<RiskLab />)
    await user.click(await screen.findByRole('button', { name: /Open transfer 11/ }))
    expect(await screen.findByText('Very high risk')).toBeInTheDocument()
    expect(api.labExplain).toHaveBeenCalledWith(11, { mute_sides: [] })
    expect(screen.getByText('Wallets under the same ID')).toBeInTheDocument()
    expect(screen.getByText('▲ +14.2 pts')).toBeInTheDocument()
    expect(screen.getByText('▼ −1.2 pts')).toBeInTheDocument()
    const sides = within(screen.getByText('Who pushed the score').nextElementSibling.nextElementSibling)
    expect(sides.getByText('+80.9')).toBeInTheDocument()
  })

  it('can hide a whole group of signals for the chosen transfer', async () => {
    const user = userEvent.setup()
    render(<RiskLab />)
    await user.click(await screen.findByRole('button', { name: /Open transfer 11/ }))
    await screen.findByText('Very high risk')
    await user.click(screen.getByRole('button', { name: 'Recipient account' }))
    await waitFor(() => expect(api.labExplain).toHaveBeenLastCalledWith(11, { mute_sides: ['recipient'] }))
  })

  it('shows the evidence table from the model report', async () => {
    render(<RiskLab />)
    expect(await screen.findByText('Evidence: why the model needs both sides')).toBeInTheDocument()
    expect(screen.getByText('all three sides')).toBeInTheDocument()
  })

  it('says so plainly when Shield is not reachable', async () => {
    api.labTransactions.mockRejectedValue(Object.assign(new Error('x'), { code: 'shield_unavailable', detail: 'The Risk Lab needs Shield', status: 503 }))
    render(<RiskLab />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('says why a transfer cannot be explained if it was recorded while Shield was off', async () => {
    const user = userEvent.setup()
    api.labTransactions.mockResolvedValue({ entries: [{ ...E1, risk_pct: null, tier: null }], total_recorded: 1 })
    api.labExplain.mockRejectedValue(Object.assign(new Error('x'), { code: 'shield_unavailable', detail: 'The Risk Lab needs Shield', status: 503 }))
    render(<RiskLab />)
    const table = await screen.findByRole('table', { name: 'Real transfers' })
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('—')
    await user.click(screen.getByRole('button', { name: /Open transfer 11/ }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
