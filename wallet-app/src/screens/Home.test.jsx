import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api.js'
import { makeT } from '../i18n.js'
import Home from './Home.jsx'

vi.mock('../api.js', async (importOriginal) => {
  const real = await importOriginal()
  return { ...real, api: { transactions: vi.fn(), addMoney: vi.fn(), me: vi.fn(), cashOut: vi.fn(), report: vi.fn(), fakeSms: vi.fn(), releaseHoldsNow: vi.fn() } }
})
import { api } from '../api.js'

const t = makeT('en')
const user0 = { id: 1, name: 'Rahim Uddin', phone: '01711000001', role: 'customer', balance: 44111 }
const TXNS = [
  { id: 3, kind: 'send_money', direction: 'out', amount: 5000, status: 'held', created_at: '2026-10-03T09:00:00', counterparty_name: 'Jamal Hossain' },
  { id: 2, kind: 'send_money', direction: 'in', amount: 800, status: 'completed', created_at: '2026-10-02T09:00:00', counterparty_name: 'Rahima Begum' },
  { id: 1, kind: 'add_money', direction: 'in', amount: 10000, status: 'completed', created_at: '2026-10-01T09:00:00', counterparty_name: null },
  { id: 0, kind: 'send_money', direction: 'out', amount: 300, status: 'cancelled', created_at: '2026-09-30T09:00:00', counterparty_name: 'Karim Mia' },
]

function setup(props = {}) {
  const setUser = vi.fn()
  const onLogout = vi.fn()
  const onToggleLang = vi.fn()
  const go = vi.fn()
  const view = render(<Home user={user0} setUser={setUser} t={t} lang="en" onToggleLang={onToggleLang} onLogout={onLogout} go={go} {...props} />)
  return { setUser, onLogout, onToggleLang, go, user: userEvent.setup(), view }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.transactions.mockResolvedValue({ transactions: TXNS })
})

describe('Home screen', () => {
  it('shows the signed-in person\'s own phone number under their name', async () => {
    setup()
    expect(await screen.findByText('01711 000001')).toBeInTheDocument()
  })

  it('greets the customer by first name and shows the balance in lakh style', async () => {
    setup({ user: { ...user0, balance: 123456 } })
    expect(screen.getByText('Rahim')).toBeInTheDocument()
    expect(screen.getByTestId('balance')).toHaveTextContent('৳1,23,456')
    await screen.findByText(/Sent to Jamal Hossain/)
  })

  it('can hide and show the balance', async () => {
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: t('hideBalance') }))
    expect(screen.getByTestId('balance')).toHaveTextContent('••••')
    expect(screen.getByTestId('balance')).not.toHaveTextContent('44,111')
    await user.click(screen.getByRole('button', { name: t('showBalance') }))
    expect(screen.getByTestId('balance')).toHaveTextContent('৳44,111')
  })

  it('lists recent activity with the right wording, sign and status', async () => {
    setup()
    const list = await screen.findByRole('list')
    const rows = Array.from(list.querySelectorAll('li'))
    expect(rows).toHaveLength(4)
    expect(rows[0]).toHaveTextContent('Sent to Jamal Hossain')
    expect(rows[0]).toHaveTextContent('−৳5,000')
    expect(rows[0]).toHaveTextContent(t('statusHeld'))
    expect(rows[1]).toHaveTextContent('Received from Rahima Begum')
    expect(rows[1]).toHaveTextContent('+৳800')
    expect(rows[2]).toHaveTextContent(t('addedMoney'))
    expect(rows[3]).toHaveTextContent(t('statusCancelled'))
  })

  it('says so when there is no activity yet', async () => {
    api.transactions.mockResolvedValue({ transactions: [] })
    setup()
    expect(await screen.findByText(t('noActivity'))).toBeInTheDocument()
  })

  it('shows a clear message, with a retry, when the wallet cannot be reached', async () => {
    api.transactions.mockRejectedValueOnce(new ApiError('network', 'x', 0))
    const { user } = setup()
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errNetwork'))
    await user.click(screen.getByRole('button', { name: '↻' }))
    expect(await screen.findByText(/Sent to Jamal Hossain/)).toBeInTheDocument()
  })

  it('adds money: updates the balance, closes the sheet and refreshes the list', async () => {
    api.addMoney.mockResolvedValue({ balance: 49111 })
    const { user, setUser } = setup()
    await user.click(screen.getByRole('button', { name: new RegExp(t('addMoney')) }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText(t('amount')), '5000')
    await user.click(within(dialog).getByRole('button', { name: t('confirm') }))
    await waitFor(() => expect(api.addMoney).toHaveBeenCalledWith(5000))
    await waitFor(() => expect(setUser).toHaveBeenCalled())
    expect(setUser.mock.calls[0][0]({ balance: 44111 }).balance).toBe(49111)
    expect(await screen.findByRole('status')).toHaveTextContent(t('moneyAdded'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.transactions).toHaveBeenCalledTimes(2)
  })

  it('refuses amounts outside the allowed range without calling the server', async () => {
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: new RegExp(t('addMoney')) }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText(t('amount')), '5')
    await user.click(within(dialog).getByRole('button', { name: t('confirm') }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(t('errInvalidAmount'))
    expect(api.addMoney).not.toHaveBeenCalled()
  })

  it('offers quick amounts', async () => {
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: new RegExp(t('addMoney')) }))
    await user.click(screen.getByRole('button', { name: '৳1,000' }))
    expect(screen.getByLabelText(t('amount'))).toHaveValue('1000')
  })

  it('opens each part of the app from the tiles', async () => {
    const { user, go } = setup()
    await user.click(screen.getByRole('button', { name: new RegExp(t('sendMoney')) }))
    expect(go).toHaveBeenLastCalledWith({ name: 'send' })
    await user.click(screen.getByRole('button', { name: new RegExp(t('inbox')) }))
    expect(go).toHaveBeenLastCalledWith({ name: 'inbox' })
    await user.click(screen.getByRole('button', { name: new RegExp(t('history')) }))
    expect(go).toHaveBeenLastCalledWith({ name: 'history' })
  })

  it('opens a held transfer when it is tapped', async () => {
    const { user, go } = setup()
    const row = await screen.findByRole('button', { name: /Sent to Jamal Hossain/ })
    await user.click(row)
    expect(go).toHaveBeenLastCalledWith({ name: 'hold', txn: expect.objectContaining({ id: 3, status: 'held' }) })
  })

  it('cashes out to an agent', async () => {
    api.cashOut.mockResolvedValue({ balance: 41000 })
    const { user, setUser } = setup()
    await user.click(screen.getByRole('button', { name: new RegExp(t('cashOut')) }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText(t('agentPhone')), '01811000001')
    await user.type(within(dialog).getByLabelText(t('amount')), '3000')
    await user.type(within(dialog).getByLabelText(t('pin')), '12345')
    await user.click(within(dialog).getByRole('button', { name: t('confirm') }))
    await waitFor(() => expect(api.cashOut).toHaveBeenCalledWith('01811000001', 3000, '12345', expect.any(String)))
    expect(await screen.findByRole('status')).toHaveTextContent(t('cashedOutOk'))
    expect(setUser.mock.calls[0][0]({ balance: 44111 }).balance).toBe(41000)
  })

  it('shows a wrong-PIN error on cash out and clears the PIN', async () => {
    api.cashOut.mockRejectedValue(new ApiError('wrong_credentials', 'x', 401))
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: new RegExp(t('cashOut')) }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText(t('agentPhone')), '01811000001')
    await user.type(within(dialog).getByLabelText(t('amount')), '3000')
    await user.type(within(dialog).getByLabelText(t('pin')), '99999')
    await user.click(within(dialog).getByRole('button', { name: t('confirm') }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(t('errWrongCredentials'))
    expect(within(dialog).getByLabelText(t('pin'))).toHaveValue('')
  })

  it('reports a suspicious number', async () => {
    api.report.mockResolvedValue({ ok: true })
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: new RegExp(t('reportNumber')) }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText(t('phone')), '01711999999')
    await user.type(within(dialog).getByLabelText(t('reportReason')), 'Asked me to return money')
    await user.click(within(dialog).getByRole('button', { name: t('reportNumber') }))
    await waitFor(() => expect(api.report).toHaveBeenCalledWith('01711999999', 'Asked me to return money'))
    expect(await screen.findByRole('status')).toHaveTextContent(t('reportSent'))
  })

  it('explains a report that was already made', async () => {
    api.report.mockRejectedValue(new ApiError('already_reported', 'x', 409))
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: new RegExp(t('reportNumber')) }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText(t('phone')), '01711999999')
    await user.click(within(dialog).getByRole('button', { name: t('reportNumber') }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(t('errAlreadyReported'))
  })

  it('demo tools plant a fake SMS and skip the wait', async () => {
    api.fakeSms.mockResolvedValue({ ok: true })
    api.releaseHoldsNow.mockResolvedValue({ released: 2 })
    api.me.mockResolvedValue({ user: user0 })
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: new RegExp(t('demoTools')) }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: t('dropSms') }))
    await waitFor(() => expect(api.fakeSms).toHaveBeenCalledWith(5000, '01711999999'))
    expect(await within(dialog).findByRole('status')).toHaveTextContent(t('smsDropped'))
    await user.click(within(dialog).getAllByRole('button', { name: t('skipWait') })[0])
    await waitFor(() => expect(api.releaseHoldsNow).toHaveBeenCalled())
    await waitFor(() => expect(within(dialog).getByRole('status')).toHaveTextContent('2 hold(s) released'))
  })

  it('logs out and switches language', async () => {
    const { user, onLogout, onToggleLang } = setup()
    await user.click(screen.getByRole('button', { name: t('logout') }))
    await user.click(screen.getByRole('button', { name: /change language/ }))
    expect(onLogout).toHaveBeenCalledTimes(1)
    expect(onToggleLang).toHaveBeenCalledTimes(1)
  })

  it('works fully in Bangla', async () => {
    const bn = makeT('bn')
    setup({ t: bn, lang: 'bn' })
    expect(screen.getByTestId('balance')).toHaveTextContent('৳৪৪,১১১')
    expect(await screen.findByText(/পাঠানো হয়েছে Jamal Hossain/)).toBeInTheDocument()
    expect(screen.getByText(bn('recent'))).toBeInTheDocument()
  })
})
