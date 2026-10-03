import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api.js'
import App from './App.jsx'
import { makeT } from './i18n.js'

let unauthorizedHandler = () => {}
vi.mock('./api.js', async (importOriginal) => {
  const real = await importOriginal()
  return {
    ...real,
    setToken: vi.fn(),
    setUnauthorizedHandler: vi.fn((h) => { unauthorizedHandler = h }),
    api: { me: vi.fn(), login: vi.fn(), register: vi.fn(), logout: vi.fn(), transactions: vi.fn(), addMoney: vi.fn() },
  }
})
import { api, setToken } from './api.js'

const t = makeT('en')
const RAHIM = { id: 1, name: 'Rahim Uddin', phone: '01711000001', role: 'customer', balance: 44111 }

beforeEach(() => {
  vi.clearAllMocks()
  api.transactions.mockResolvedValue({ transactions: [] })
  api.logout.mockResolvedValue({ ok: true })
})

describe('App', () => {
  it('starts at the login screen', () => {
    render(<App />)
    expect(screen.getByRole('button', { name: t('login') })).toBeInTheDocument()
  })

  it('logs in, saves the session, and shows the home screen', async () => {
    api.login.mockResolvedValue({ token: 'tok123', user: RAHIM })
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Rahim' }))
    await user.click(screen.getByRole('button', { name: t('login') }))
    expect(await screen.findByTestId('balance')).toHaveTextContent('৳44,111')
    expect(localStorage.getItem('upay_token')).toBe('tok123')
    expect(setToken).toHaveBeenCalledWith('tok123')
  })

  it('brings a returning customer straight back in', async () => {
    localStorage.setItem('upay_token', 'saved')
    api.me.mockResolvedValue({ user: RAHIM })
    render(<App />)
    expect(await screen.findByTestId('balance')).toBeInTheDocument()
    expect(setToken).toHaveBeenCalledWith('saved')
  })

  it('drops a saved login the server no longer accepts', async () => {
    localStorage.setItem('upay_token', 'stale')
    api.me.mockRejectedValue(new ApiError('not_logged_in', 'x', 401))
    render(<App />)
    expect(await screen.findByRole('button', { name: t('login') })).toBeInTheDocument()
    expect(localStorage.getItem('upay_token')).toBeNull()
  })

  it('tells the customer when the wallet cannot be reached at start-up', async () => {
    localStorage.setItem('upay_token', 'saved')
    api.me.mockRejectedValue(new ApiError('network', 'x', 0))
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errNetwork'))
  })

  it('logs out even if the server cannot be reached', async () => {
    localStorage.setItem('upay_token', 'saved')
    api.me.mockResolvedValue({ user: RAHIM })
    api.logout.mockRejectedValue(new ApiError('network', 'x', 0))
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: t('logout') }))
    expect(await screen.findByRole('button', { name: t('login') })).toBeInTheDocument()
    expect(localStorage.getItem('upay_token')).toBeNull()
  })

  it('sends the customer back to login, with a reason, when the session expires mid-use', async () => {
    localStorage.setItem('upay_token', 'saved')
    api.me.mockResolvedValue({ user: RAHIM })
    render(<App />)
    await screen.findByTestId('balance')
    unauthorizedHandler()
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errSession'))
  })

  it('remembers the chosen language', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<App />)
    await user.click(screen.getByRole('button', { name: 'Change language' }))
    await waitFor(() => expect(localStorage.getItem('upay_lang')).toBe('bn'))
    expect(document.documentElement.lang).toBe('bn')
    unmount()
    render(<App />)
    expect(screen.getByRole('button', { name: makeT('bn')('login') })).toBeInTheDocument()
  })
})

describe('App navigation', () => {
  async function loggedIn() {
    localStorage.setItem('upay_token', 'saved')
    api.me.mockResolvedValue({ user: RAHIM })
    api.inbox = vi.fn().mockResolvedValue({ messages: [] })
    api.preview = vi.fn()
    const user = userEvent.setup()
    render(<App />)
    await screen.findByTestId('balance')
    return user
  }

  it('opens messages and history from the home tiles and comes back', async () => {
    const user = await loggedIn()
    await user.click(screen.getByRole('button', { name: new RegExp(t('inbox')) }))
    expect(await screen.findByText(t('noMessages'))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: new RegExp(t('back')) }))
    expect(await screen.findByTestId('balance')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: new RegExp(t('history')) }))
    expect(await screen.findByText(t('noActivity'))).toBeInTheDocument()
  })

  it('starts a transfer and returns home with a refreshed balance when closed', async () => {
    const user = await loggedIn()
    await user.click(screen.getByRole('button', { name: new RegExp(t('sendMoney')) }))
    expect(await screen.findByLabelText(t('recipientPhone'))).toBeInTheDocument()
    api.me.mockResolvedValue({ user: { ...RAHIM, balance: 39111 } })
    await user.click(screen.getByRole('button', { name: t('close') }))
    await waitFor(() => expect(screen.getByTestId('balance')).toHaveTextContent('৳39,111'))
  })
})
