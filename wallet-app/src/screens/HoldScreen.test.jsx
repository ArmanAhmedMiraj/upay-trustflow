import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api.js'
import { makeT } from '../i18n.js'
import HoldScreen from './HoldScreen.jsx'

vi.mock('../api.js', async (importOriginal) => {
  const real = await importOriginal()
  return { ...real, api: { cancelHold: vi.fn(), transactions: vi.fn(), report: vi.fn() } }
})
import { api } from '../api.js'

const t = makeT('en')
const START = new Date('2026-10-04T09:00:00Z')
const txn = (extra = {}) => ({ id: 77, status: 'held', amount: 5000, release_at: '2026-10-04T09:30:00',
  counterparty_name: 'Jamal Hossain', counterparty_phone: '01711999999', ...extra })

function setup(props = {}) {
  const onBack = vi.fn(), onBalance = vi.fn()
  render(<HoldScreen txn={txn()} t={t} lang="en" onBack={onBack} onBalance={onBalance} {...props} />)
  return { onBack, onBalance, user: userEvent.setup() }
}

beforeEach(() => {
  // only the clock and the once-a-second tick are faked, so the test tools' own waiting keeps working
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
  vi.setSystemTime(START)
  vi.clearAllMocks()
  api.transactions.mockResolvedValue({ transactions: [{ id: 77, status: 'held' }] })
})
afterEach(() => vi.useRealTimers())

const tick = (ms) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

describe('Hold screen', () => {
  it('explains the hold and counts down the 30 minutes', async () => {
    setup()
    expect(screen.getByText(t('holdTitle'))).toBeInTheDocument()
    expect(screen.getByRole('timer')).toHaveTextContent('30:00')
    expect(screen.getByText(/Your ৳5,000 left your balance and is being kept safe. Jamal Hossain will NOT receive it/)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(t('analystMayReview')))).toBeInTheDocument()
    await tick(1000)
    expect(screen.getByRole('timer')).toHaveTextContent('29:59')
    await tick(59_000)
    expect(screen.getByRole('timer')).toHaveTextContent('29:00')
  })

  it('cancels: the money comes back and the new balance is shown', async () => {
    api.cancelHold.mockResolvedValue({ transaction: { id: 77, status: 'cancelled' }, balance: 30000 })
    const { user, onBalance } = setup()
    await user.click(screen.getByRole('button', { name: t('cancelHold') }))
    expect(api.cancelHold).toHaveBeenCalledWith(77)
    expect(await screen.findByText(t('moneyBack'))).toBeInTheDocument()
    expect(screen.getByText(/৳30,000/)).toBeInTheDocument()
    expect(onBalance).toHaveBeenCalledWith(30000)
    expect(screen.queryByRole('timer')).not.toBeInTheDocument()
  })

  it('explains what happened if the hold could not be cancelled any more', async () => {
    api.cancelHold.mockRejectedValue(new ApiError('not_cancellable', 'x', 409))
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: t('cancelHold') }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(api.transactions).toHaveBeenCalled()                       // it checks what the server now says
  })

  it('when the time is up it asks the server and shows that the money was sent', async () => {
    api.transactions.mockResolvedValue({ transactions: [{ id: 77, status: 'completed' }] })
    setup()
    await tick(30 * 60 * 1000 + 1500)
    await waitFor(() => expect(screen.getByText(t('holdReleased'))).toBeInTheDocument())
    expect(api.transactions).toHaveBeenCalled()
  })

  it('keeps asking every few seconds while the server has not released it yet', async () => {
    api.transactions.mockResolvedValue({ transactions: [{ id: 77, status: 'held' }] })
    setup()
    await tick(30 * 60 * 1000 + 1000)
    const first = api.transactions.mock.calls.length
    await tick(7000)
    expect(api.transactions.mock.calls.length).toBeGreaterThan(first)
    expect(screen.getByRole('timer')).toHaveTextContent('00:00')       // never negative
  })

  it('tells the customer when an analyst stopped the transfer and refunded them', async () => {
    api.transactions.mockResolvedValue({ transactions: [{ id: 77, status: 'rejected' }] })
    setup()
    await tick(30 * 60 * 1000 + 1500)
    await waitFor(() => expect(screen.getByText(t('holdRejected'))).toBeInTheDocument())
  })

  it('opens an already-finished transfer without a countdown', () => {
    setup({ txn: txn({ status: 'cancelled' }) })
    expect(screen.queryByRole('timer')).not.toBeInTheDocument()
    expect(screen.getByText(t('moneyBack'))).toBeInTheDocument()
  })

  it('lets the customer report the number, prefilled', async () => {
    api.report.mockResolvedValue({ ok: true })
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: t('reportNumber') }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByLabelText(t('phone'))).toHaveValue('01711999999')
    await user.click(within(dialog).getByRole('button', { name: t('reportNumber') }))
    await waitFor(() => expect(api.report).toHaveBeenCalledWith('01711999999', ''))
    expect(await screen.findByText(new RegExp(t('reportSent')))).toBeInTheDocument()
  })

  it('goes back', async () => {
    const { user, onBack } = setup()
    await user.click(screen.getByRole('button', { name: new RegExp(t('back')) }))
    expect(onBack).toHaveBeenCalled()
  })

  it('stops ticking when the screen is closed', async () => {
    const spy = vi.spyOn(globalThis, 'clearInterval')
    const view = render(<HoldScreen txn={txn()} t={t} lang="en" onBack={() => {}} />)
    view.unmount()
    expect(spy).toHaveBeenCalled()
  })

  it('works in Bangla', () => {
    const bn = makeT('bn')
    setup({ t: bn, lang: 'bn' })
    expect(screen.getByText(bn('holdTitle'))).toBeInTheDocument()
    expect(screen.getByText(/আপনার ৳৫,০০০ ব্যালেন্স থেকে সরিয়ে নিরাপদে রাখা হয়েছে/)).toBeInTheDocument()
  })
})
