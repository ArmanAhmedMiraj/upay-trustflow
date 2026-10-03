import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api.js'
import { makeT } from '../i18n.js'
import SendFlow from './SendFlow.jsx'

vi.mock('../api.js', async (importOriginal) => {
  const real = await importOriginal()
  return { ...real, api: { preview: vi.fn(), send: vi.fn(), transactions: vi.fn() } }
})
import { api } from '../api.js'

const t = makeT('en')
const me = { id: 1, name: 'Rahim Uddin', phone: '01711000001', role: 'customer', balance: 30000 }
const MUM = { name: 'Rahima Begum (Mum)', phone: '01711000002' }
const JAMAL = { name: 'Jamal Hossain', phone: '01711999999' }

const base = { scam_type: null, reasons: [], questions: [], message_bn: null, message_en: null, shield_available: true, risk_before_pct: null }
const LOW = { ...base, action: 'allow', risk_pct: 3, tier: 'low' }
const NOTE = { ...base, action: 'allow_with_note', risk_pct: 12, tier: 'note', message_en: 'Please double-check\nYou have not sent money to this number before.',
  message_bn: 'একটু দেখে নিন\nএই নম্বরে আপনি আগে টাকা পাঠাননি।' }
const QUESTIONS = [
  { id: 'g1', risky_answer: 'yes', bn: 'কেউ কি ফোন বা মেসেজে আপনাকে এই টাকা পাঠাতে বলেছে?', en: 'Has anyone asked you, by phone or message, to send this money?' },
  { id: 's_advance', risky_answer: 'yes', bn: 'পণ্য পাওয়ার আগেই কি পুরো টাকা দিতে বলা হয়েছে?', en: 'Are you being asked to pay in full before getting the item?' },
]
const SAFETY = { ...base, action: 'safety_check', risk_pct: 45, tier: 'high', questions: QUESTIONS,
  message_en: 'Warning: this transfer shows signs of risk\nIf anyone is rushing you, stop.', message_bn: 'সতর্কতা: এই লেনদেনে ঝুঁকির লক্ষণ আছে\nকেউ তাড়া দিলে থামুন।' }
const HOLD = { ...base, action: 'hold_30min', risk_pct: 100, tier: 'very_high', scam_type: 'return_by_mistake',
  reasons: [{ source: 'rule', feature: 'story_mismatch', text: 'An SMS says money was received from this number, but the upay ledger shows no such credit' },
            { source: 'model', feature: 'is_first_time_recipient', text: 'First transfer to this number', share_pct: 20 }],
  message_en: 'Stop! This may be a scam\nOur records show this money was never credited to your account.',
  message_bn: 'থামুন! এটি প্রতারণা হতে পারে\nআমাদের হিসাবে আপনার অ্যাকাউন্টে এই টাকা জমা হয়নি।' }

function setup(props = {}) {
  const onClose = vi.fn(), onSent = vi.fn(), onHeld = vi.fn()
  render(<SendFlow user={me} t={t} lang="en" onClose={onClose} onSent={onSent} onHeld={onHeld} {...props} />)
  return { onClose, onSent, onHeld, user: userEvent.setup() }
}
async function fill(user, phone, amount) {
  await user.type(screen.getByLabelText(t('recipientPhone')), phone)
  await user.type(screen.getByLabelText(t('amount')), String(amount))
  await user.click(screen.getByRole('button', { name: t('continue') }))
}
const btn = (name) => screen.getByRole('button', { name })
async function enterPinAndSend(user, label = t('sendNow'), pin = '12345') {
  await user.type(await screen.findByLabelText(t('pin')), pin)
  await user.click(btn(label))
}

beforeEach(() => {
  vi.clearAllMocks()
  api.transactions.mockResolvedValue({ transactions: [] })
})

describe('Send money: everyday payment', () => {
  it('goes details -> review -> PIN -> sent, with no friction when the risk is low', async () => {
    api.preview.mockResolvedValue({ recipient: MUM, risk: LOW })
    api.send.mockResolvedValue({ transaction: { id: 9, status: 'completed' }, balance: 29200 })
    const { user, onSent } = setup()
    await fill(user, '01711000002', 800)
    expect(api.preview).toHaveBeenCalledWith('01711000002', 800, expect.objectContaining({ amount_edits: 0, on_call: false }), undefined)

    expect(await screen.findByText('Rahima Begum (Mum)')).toBeInTheDocument()
    expect(screen.getByText('৳800')).toBeInTheDocument()
    expect(screen.getByText(new RegExp(t('noRiskSigns')))).toBeInTheDocument()
    await user.click(btn(t('continue')))
    await enterPinAndSend(user)

    await waitFor(() => expect(api.send).toHaveBeenCalledTimes(1))
    expect(api.send).toHaveBeenCalledWith(expect.objectContaining({
      recipient_phone: '01711000002', amount: 800, pin: '12345', acknowledged_risk: false, idempotency_key: expect.any(String), safety_answers: undefined }))
    expect(await screen.findByText('You sent ৳800 to Rahima Begum (Mum)')).toBeInTheDocument()
    expect(onSent).toHaveBeenCalledWith(29200)
  })

  it('shows a gentle note for a low-medium risk and lets the customer carry on', async () => {
    api.preview.mockResolvedValue({ recipient: MUM, risk: NOTE })
    const { user } = setup()
    await fill(user, '01711000002', 800)
    expect(await screen.findByRole('meter')).toHaveAttribute('aria-valuenow', '12')
    expect(screen.getByText('Please double-check')).toBeInTheDocument()
    expect(btn(t('continue'))).toBeEnabled()
  })

  it('refuses bad details before asking Shield anything', async () => {
    const { user } = setup()
    await fill(user, '0171', 800)
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errInvalidPhone'))
    await user.clear(screen.getByLabelText(t('recipientPhone')))
    await fill(user, '01711000001', 800)                                          // your own number
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errSelf'))
    await user.clear(screen.getByLabelText(t('recipientPhone')))
    await user.clear(screen.getByLabelText(t('amount')))
    await fill(user, '01711000002', 5)
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errInvalidAmount'))
    expect(api.preview).not.toHaveBeenCalled()
  })

  it('tells the customer when the recipient does not exist', async () => {
    api.preview.mockRejectedValue(new ApiError('recipient_not_found', 'x', 404))
    const { user } = setup()
    await fill(user, '01799999999', 800)
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errNotFound'))
  })

  it('still works when the safety check is switched off, and says so', async () => {
    api.preview.mockResolvedValue({ recipient: MUM, risk: { ...LOW, shield_available: false } })
    const { user } = setup()
    await fill(user, '01711000002', 800)
    expect(await screen.findByText(t('shieldOff'))).toBeInTheDocument()
    expect(btn(t('continue'))).toBeEnabled()
  })

  it('passes on whether the customer says they are on a call', async () => {
    api.preview.mockResolvedValue({ recipient: MUM, risk: LOW })
    const { user } = setup()
    await user.click(screen.getByLabelText(t('onCall')))
    await fill(user, '01711000002', 800)
    await screen.findByText('Rahima Begum (Mum)')
    expect(api.preview.mock.calls[0][2].on_call).toBe(true)
  })

  it('counts a changed amount as an edit, which is one of Shield\'s signals', async () => {
    api.preview.mockResolvedValue({ recipient: MUM, risk: LOW })
    const { user } = setup()
    await fill(user, '01711000002', 800)
    await screen.findByText('Rahima Begum (Mum)')
    await user.click(screen.getByRole('button', { name: t('back') }))
    await user.clear(screen.getByLabelText(t('amount')))
    await user.type(screen.getByLabelText(t('amount')), '900')
    await user.click(btn(t('continue')))
    await waitFor(() => expect(api.preview).toHaveBeenCalledTimes(2))
    expect(api.preview.mock.calls[1][2].amount_edits).toBe(1)
  })

  it('offers recent recipients as one-tap shortcuts', async () => {
    api.transactions.mockResolvedValue({ transactions: [
      { id: 1, kind: 'send_money', direction: 'out', counterparty_name: 'Karim Mia', counterparty_phone: '01711000003' },
      { id: 2, kind: 'send_money', direction: 'in', counterparty_name: 'Not Me', counterparty_phone: '01711000009' },
    ] })
    const { user } = setup()
    await user.click(await screen.findByRole('button', { name: 'Karim' }))
    expect(screen.getByLabelText(t('recipientPhone'))).toHaveValue('01711000003')
    expect(screen.queryByRole('button', { name: 'Not' })).not.toBeInTheDocument()
  })
})

describe('Send money: the PIN step', () => {
  async function toPin(user, risk = LOW) {
    api.preview.mockResolvedValue({ recipient: MUM, risk })
    await fill(user, '01711000002', 800)
    await screen.findByText('Rahima Begum (Mum)')
    await user.click(btn(t('continue')))
  }

  it('shows a wrong-PIN error, keeps the customer on the PIN screen, and retries with the SAME key', async () => {
    api.send.mockRejectedValueOnce(new ApiError('wrong_credentials', 'x', 401))
    api.send.mockResolvedValueOnce({ transaction: { id: 9, status: 'completed' }, balance: 29200 })
    const { user } = setup()
    await toPin(user)
    await enterPinAndSend(user, t('sendNow'), '99999')
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errWrongCredentials'))
    expect(screen.getByLabelText(t('pin'))).toHaveValue('')
    await enterPinAndSend(user)
    await screen.findByText(t('sentOk'))
    const [first, second] = api.send.mock.calls.map((c) => c[0])
    expect(first.idempotency_key).toBe(second.idempotency_key)                    // a retry can never pay twice
  })

  it('refuses a PIN that is not five digits', async () => {
    const { user } = setup()
    await toPin(user)
    await enterPinAndSend(user, t('sendNow'), '12')
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errInvalidPin'))
    expect(api.send).not.toHaveBeenCalled()
  })

  it('goes back to the review with the new verdict if the server sees a higher risk', async () => {
    api.send.mockRejectedValue(new ApiError('risk_interruption', 'x', 409, { risk: HOLD }))
    const { user } = setup()
    await toPin(user)
    await enterPinAndSend(user)
    expect(await screen.findByRole('meter')).toHaveAttribute('aria-valuenow', '100')
    expect(btn(t('holdAndSend'))).toBeInTheDocument()
  })
})

describe('Send money: the scam story', () => {
  it('holds the money, shows the verified ledger fact and the Bangla warning, then opens the hold screen', async () => {
    api.preview.mockResolvedValue({ recipient: JAMAL, risk: HOLD })
    api.send.mockResolvedValue({ transaction: { id: 77, status: 'held', amount: 5000, release_at: '2026-10-04T09:30:00' }, balance: 25000 })
    const { user, onHeld } = setup()
    await fill(user, '01711999999', 5000)

    const meter = await screen.findByRole('meter')
    expect(meter).toHaveAttribute('aria-valuenow', '100')
    expect(meter).toHaveTextContent(t('tierVeryHigh'))
    expect(screen.getByText('Stop! This may be a scam')).toBeInTheDocument()
    await user.click(screen.getByText(t('whyShown')))
    expect(screen.getByText(t('verifiedFact'))).toBeInTheDocument()
    expect(screen.getByText(/ledger shows no such credit/)).toBeInTheDocument()

    await user.click(btn(t('holdAndSend')))
    await enterPinAndSend(user, t('holdAndSend'))
    await waitFor(() => expect(api.send).toHaveBeenCalledWith(expect.objectContaining({ acknowledged_risk: true, amount: 5000 })))
    expect(onHeld).toHaveBeenCalledWith(expect.objectContaining({ id: 77, status: 'held', counterparty_name: 'Jamal Hossain', counterparty_phone: '01711999999' }), 25000)
  })

  it('the customer can walk away from a risky transfer', async () => {
    api.preview.mockResolvedValue({ recipient: JAMAL, risk: HOLD })
    const { user, onClose } = setup()
    await fill(user, '01711999999', 5000)
    await user.click(await screen.findByRole('button', { name: t('cancelTransfer') }))
    expect(onClose).toHaveBeenCalled()
    expect(api.send).not.toHaveBeenCalled()
  })

  it('writes the warning in Bangla in Bangla mode', async () => {
    api.preview.mockResolvedValue({ recipient: JAMAL, risk: HOLD })
    const bn = makeT('bn')
    setup({ t: bn, lang: 'bn' })
    await userEvent.setup().type(screen.getByLabelText(bn('recipientPhone')), '01711999999')
    await userEvent.setup().type(screen.getByLabelText(bn('amount')), '5000')
    await userEvent.setup().click(screen.getByRole('button', { name: bn('continue') }))
    expect(await screen.findByText('থামুন! এটি প্রতারণা হতে পারে')).toBeInTheDocument()
    expect(screen.getByRole('meter')).toHaveTextContent('১০০%')
  })
})

describe('Send money: safety-check questions', () => {
  it('asks two questions, re-scores on each answer, and turns a risky answer into a hold', async () => {
    api.preview.mockResolvedValueOnce({ recipient: JAMAL, risk: SAFETY })
    api.preview.mockResolvedValueOnce({ recipient: JAMAL, risk: { ...HOLD, risk_pct: 78, risk_before_pct: 45 } })
    api.send.mockResolvedValue({ transaction: { id: 5, status: 'held', amount: 4000, release_at: '2026-10-04T09:30:00' }, balance: 26000 })
    const { user, onHeld } = setup()
    await fill(user, '01711999999', 4000)

    expect(await screen.findByRole('meter')).toHaveAttribute('aria-valuenow', '45')
    expect(screen.getByText(t('answerQuestions'))).toBeInTheDocument()
    expect(screen.getByText(QUESTIONS[0].en)).toBeInTheDocument()
    expect(btn(t('continueAnyway'))).toBeInTheDocument()

    const first = screen.getByText(QUESTIONS[0].en).closest('fieldset')
    await user.click(within(first).getByRole('button', { name: t('yes') }))
    await waitFor(() => expect(screen.getByRole('meter')).toHaveAttribute('aria-valuenow', '78'))
    expect(api.preview).toHaveBeenLastCalledWith('01711999999', 4000, expect.any(Object), [{ question_id: 'g1', answer: 'yes' }])
    expect(screen.getByText(/The risk was 45% → Now/)).toBeInTheDocument()
    expect(within(first).getByRole('button', { name: t('yes') })).toHaveAttribute('aria-pressed', 'true')

    await user.click(btn(t('holdAndSend')))
    await enterPinAndSend(user, t('holdAndSend'))
    await waitFor(() => expect(api.send).toHaveBeenCalledWith(expect.objectContaining({
      acknowledged_risk: true, safety_answers: [{ question_id: 'g1', answer: 'yes' }] })))
    expect(onHeld).toHaveBeenCalled()
  })

  it('lets the customer go on after reassuring answers, but only after acknowledging the risk', async () => {
    api.preview.mockResolvedValueOnce({ recipient: JAMAL, risk: SAFETY })
    api.preview.mockResolvedValueOnce({ recipient: JAMAL, risk: { ...SAFETY, action: 'warn_and_confirm', risk_pct: 31, risk_before_pct: 45, questions: [] } })
    api.send.mockResolvedValue({ transaction: { id: 6, status: 'completed' }, balance: 26000 })
    const { user, onSent } = setup()
    await fill(user, '01711999999', 4000)
    const first = (await screen.findByText(QUESTIONS[0].en)).closest('fieldset')
    await user.click(within(first).getByRole('button', { name: t('no') }))
    await waitFor(() => expect(screen.getByRole('meter')).toHaveAttribute('aria-valuenow', '31'))
    expect(screen.getByText(QUESTIONS[0].en)).toBeInTheDocument()               // the questions stay visible
    await user.click(btn(t('continueAnyway')))
    await enterPinAndSend(user)
    await waitFor(() => expect(api.send).toHaveBeenCalledWith(expect.objectContaining({ acknowledged_risk: true })))
    expect(onSent).toHaveBeenCalledWith(26000)
  })

  it('shows the questions in Bangla in Bangla mode', async () => {
    api.preview.mockResolvedValue({ recipient: JAMAL, risk: SAFETY })
    const bn = makeT('bn')
    setup({ t: bn, lang: 'bn' })
    const u = userEvent.setup()
    await u.type(screen.getByLabelText(bn('recipientPhone')), '01711999999')
    await u.type(screen.getByLabelText(bn('amount')), '4000')
    await u.click(screen.getByRole('button', { name: bn('continue') }))
    expect(await screen.findByText(QUESTIONS[0].bn)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: bn('yes') })).toHaveLength(2)
  })

  it('keeps the old verdict and shows an error if re-scoring fails', async () => {
    api.preview.mockResolvedValueOnce({ recipient: JAMAL, risk: SAFETY })
    api.preview.mockRejectedValueOnce(new ApiError('network', 'x', 0))
    const { user } = setup()
    await fill(user, '01711999999', 4000)
    const first = (await screen.findByText(QUESTIONS[0].en)).closest('fieldset')
    await user.click(within(first).getByRole('button', { name: t('yes') }))
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errNetwork'))
    expect(screen.getByRole('meter')).toHaveAttribute('aria-valuenow', '45')
  })
})

describe('Send money: closing', () => {
  it('closes from the cross button', async () => {
    const { user, onClose } = setup()
    await user.click(screen.getByRole('button', { name: t('close') }))
    expect(onClose).toHaveBeenCalled()
  })
})
