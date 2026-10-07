import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RiskLab from './RiskLab.jsx'

vi.mock('../api.js', async (importOriginal) => {
  const real = await importOriginal()
  return { ...real, api: { labAccounts: vi.fn(), labScore: vi.fn(), labReport: vi.fn() } }
})
import { api } from '../api.js'

const ACCOUNTS = {
  default_tx: { amount: 2000, hour: 14, on_call: 0, hesitation_secs: 6, amount_edits: 0, mins_since_credit: 2000, new_device: 0, sms_claim_mismatch: 0 },
  senders: [{ id: 'rahim', name: 'Rahim Uddin', bio: 'Office worker', district: 'Dhaka' }, { id: 'karim', name: 'Abdul Karim', bio: 'Retired teacher', district: 'Khulna' }],
  recipients: [
    { id: 'mother', name: 'Fatema Begum', story: 'Rahim\'s mother.', facts: { 'wallet age (days)': 1900, 'SIM swapped recently': false } },
    { id: 'mule_officer', name: "'Officer Rafiq' account", story: 'A collector account.', facts: { 'wallet age (days)': 5, 'SIM swapped recently': false } },
  ],
  scenarios: [
    { id: 'family', title: 'Rahim sends to his mother', shows: 'Everything normal.', sender: 'rahim', recipient: 'mother', tx: { amount: 1000 } },
    { id: 'officer', title: 'Fake officer', shows: 'Both sides agree.', sender: 'karim', recipient: 'mule_officer', tx: { amount: 45000, on_call: 1 } },
  ],
}
const row = (signal, side, label, points, text, present = true) => ({ signal, side, label, points, text, present, muted: false, value: 1, why: '' })
const RESULT = {
  risk_pct: 91.5, tier: 'very_high', action: 'hold_30min', baseline_pct: 0.5, signals_present: 7, muted: [],
  tier_thresholds_pct: { note: 9.8, high: 27.8, very_high: 61.9 },
  sides: { sender: 20.5, recipient: 58.9, pair: 11.6 },
  combination: { typical_transfer_pct: 0, sender_signals_only_pct: 1.7, recipient_signals_only_pct: 90.1, all_signals_pct: 91.5, extra_from_combining_points: 0.1 },
  contributions: [
    row('r_wallets_per_nid', 'recipient', 'Wallets under the same ID', 14.2, '2 wallets registered under the same ID'),
    row('s_on_call', 'sender', 'Sender is on a phone call', 6.1, 'Sender is on a phone call while sending'),
    row('i_mutual_contacts', 'pair', 'Contacts in common', 3.0, 'No contacts in common'),
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
  api.labAccounts.mockResolvedValue(ACCOUNTS)
  api.labScore.mockResolvedValue(RESULT)
  api.labReport.mockResolvedValue(REPORT)
})

describe('Risk Lab', () => {
  it('opens on the fake-officer story and shows the score, the tier and who pushed it', async () => {
    render(<RiskLab />)
    expect(await screen.findByText('91.5')).toBeInTheDocument()
    expect(screen.getByText('Very high risk')).toBeInTheDocument()
    expect(screen.getByText('Hold for 30 minutes')).toBeInTheDocument()
    const sides = within(screen.getByText('Who pushed the score').nextElementSibling.nextElementSibling)
    expect(sides.getByText('+58.9')).toBeInTheDocument()
    expect(sides.getByText('Recipient account')).toBeInTheDocument()
    await waitFor(() => expect(api.labScore).toHaveBeenCalledWith(expect.objectContaining({ sender_id: 'karim', recipient_id: 'mule_officer', mute_sides: [] })))
  })

  it('lists each signal with its points and plain-language reason', async () => {
    render(<RiskLab />)
    expect(await screen.findByText('Wallets under the same ID')).toBeInTheDocument()
    expect(screen.getByText('▲ +14.2 pts')).toBeInTheDocument()
    expect(screen.getByText('2 wallets registered under the same ID')).toBeInTheDocument()
    expect(screen.getByText('▼ −1.2 pts')).toBeInTheDocument()
  })

  it('asks the model again when a story or a live detail changes', async () => {
    const user = userEvent.setup()
    render(<RiskLab />)
    await screen.findByText('91.5')
    await user.click(screen.getByRole('button', { name: 'Rahim sends to his mother' }))
    await waitFor(() => expect(api.labScore).toHaveBeenLastCalledWith(expect.objectContaining({ sender_id: 'rahim', recipient_id: 'mother', tx: expect.objectContaining({ amount: 1000 }) })))
    await user.click(screen.getByLabelText('Sender is on a phone call'))
    await waitFor(() => expect(api.labScore).toHaveBeenLastCalledWith(expect.objectContaining({ tx: expect.objectContaining({ on_call: 1 }) })))
  })

  it('can hide a whole group of signals to show the model needs both sides', async () => {
    const user = userEvent.setup()
    render(<RiskLab />)
    await screen.findByText('91.5')
    await user.click(screen.getByRole('button', { name: 'Recipient account' }))
    await waitFor(() => expect(api.labScore).toHaveBeenLastCalledWith(expect.objectContaining({ mute_sides: ['recipient'] })))
    expect(screen.getByRole('button', { name: /Hidden: Recipient account/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('shows the evidence table from the model report', async () => {
    render(<RiskLab />)
    expect(await screen.findByText('Evidence: why the model needs both sides')).toBeInTheDocument()
    expect(screen.getByText('sender signals only')).toBeInTheDocument()
    expect(screen.getByText('all three sides')).toBeInTheDocument()
  })

  it('says so plainly when Shield is not reachable', async () => {
    api.labAccounts.mockRejectedValue(Object.assign(new Error('x'), { code: 'shield_unavailable', detail: 'The Risk Lab needs Shield', status: 503 }))
    render(<RiskLab />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
