import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api.js'
import { makeT } from '../i18n.js'
import History from './History.jsx'
import Inbox from './Inbox.jsx'

vi.mock('../api.js', async (importOriginal) => {
  const real = await importOriginal()
  return { ...real, api: { inbox: vi.fn(), report: vi.fn(), transactions: vi.fn() } }
})
import { api } from '../api.js'

const t = makeT('en')
const MESSAGES = [
  { id: 2, from: '01711999999', text: 'You have received Tk 5,000 from 01711999999. Please return it, it was sent by mistake.', official: false, created_at: '2026-10-04T08:50:00' },
  { id: 1, from: 'upay', text: 'You have received Tk 800 from 01711000002.', official: true, created_at: '2026-10-04T08:00:00' },
]

beforeEach(() => vi.clearAllMocks())

describe('Inbox', () => {
  it('shows real upay messages as official and fake ones with a clear warning', async () => {
    api.inbox.mockResolvedValue({ messages: MESSAGES })
    render(<Inbox t={t} lang="en" onBack={() => {}} />)
    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent(t('notFromUpay'))
    expect(items[0]).toHaveTextContent(t('notFromUpayHelp'))
    expect(items[0]).toHaveClass('unofficial')
    expect(items[1]).toHaveTextContent(t('officialUpay'))
    expect(items[1]).not.toHaveTextContent(t('notFromUpayHelp'))
    expect(within(items[1]).queryByRole('button')).not.toBeInTheDocument()   // nothing to report on a true message
  })

  it('reports the sender of a fake message with one tap', async () => {
    api.inbox.mockResolvedValue({ messages: MESSAGES })
    api.report.mockResolvedValue({ ok: true })
    const user = userEvent.setup()
    render(<Inbox t={t} lang="en" onBack={() => {}} />)
    await user.click(await screen.findByRole('button', { name: t('reportNumber') }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByLabelText(t('phone'))).toHaveValue('01711999999')
    await user.click(within(dialog).getByRole('button', { name: t('reportNumber') }))
    await waitFor(() => expect(api.report).toHaveBeenCalledWith('01711999999', ''))
    expect(await screen.findByRole('status')).toHaveTextContent(t('reportSent'))
  })

  it('says so when there are no messages, and when the wallet cannot be reached', async () => {
    api.inbox.mockResolvedValueOnce({ messages: [] })
    const { unmount } = render(<Inbox t={t} lang="en" onBack={() => {}} />)
    expect(await screen.findByText(t('noMessages'))).toBeInTheDocument()
    unmount()
    api.inbox.mockRejectedValueOnce(new ApiError('network', 'x', 0))
    render(<Inbox t={t} lang="en" onBack={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errNetwork'))
  })
})

describe('History', () => {
  const TXNS = [
    { id: 3, kind: 'send_money', direction: 'out', amount: 5000, status: 'held', created_at: '2026-10-04T08:00:00', counterparty_name: 'Jamal Hossain' },
    { id: 2, kind: 'send_money', direction: 'out', amount: 800, status: 'completed', created_at: '2026-10-03T08:00:00', counterparty_name: 'Mum' },
  ]

  it('lists everything and opens a held transfer when tapped', async () => {
    api.transactions.mockResolvedValue({ transactions: TXNS })
    const onOpenHold = vi.fn()
    const user = userEvent.setup()
    render(<History t={t} lang="en" onBack={() => {}} onOpenHold={onOpenHold} />)
    expect(await screen.findByText(/Sent to Mum/)).toBeInTheDocument()
    expect(api.transactions).toHaveBeenCalledWith(60)
    await user.click(screen.getByRole('button', { name: /Sent to Jamal Hossain/ }))
    expect(onOpenHold).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }))
  })

  it('shows an empty state and errors clearly', async () => {
    api.transactions.mockResolvedValueOnce({ transactions: [] })
    const { unmount } = render(<History t={t} lang="en" onBack={() => {}} onOpenHold={() => {}} />)
    expect(await screen.findByText(t('noActivity'))).toBeInTheDocument()
    unmount()
    api.transactions.mockRejectedValueOnce(new ApiError('network', 'x', 0))
    render(<History t={t} lang="en" onBack={() => {}} onOpenHold={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errNetwork'))
  })
})
