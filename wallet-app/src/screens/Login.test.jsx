import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api.js'
import { makeT } from '../i18n.js'
import Login from './Login.jsx'

vi.mock('../api.js', async (importOriginal) => {
  const real = await importOriginal()
  return { ...real, api: { login: vi.fn(), register: vi.fn() } }
})
import { api } from '../api.js'

const t = makeT('en')
function setup(props = {}) {
  const onLoggedIn = vi.fn()
  render(<Login t={t} lang="en" onToggleLang={() => {}} onLoggedIn={onLoggedIn} notice="" {...props} />)
  return { onLoggedIn, user: userEvent.setup() }
}
const phoneBox = () => screen.getByLabelText(t('phone'))
const pinBox = () => screen.getByLabelText(t('pin'))
const submit = () => screen.getByRole('button', { name: t('login') })

beforeEach(() => vi.clearAllMocks())

describe('Login screen', () => {
  it('logs in with a valid number and PIN', async () => {
    api.login.mockResolvedValue({ token: 'tok', user: { name: 'Rahim' } })
    const { onLoggedIn, user } = setup()
    await user.type(phoneBox(), '01711000001')
    await user.type(pinBox(), '12345')
    await user.click(submit())
    await waitFor(() => expect(onLoggedIn).toHaveBeenCalledWith('tok', { name: 'Rahim' }))
    expect(api.login).toHaveBeenCalledWith('01711000001', '12345')
  })

  it('stops a bad phone number or PIN before asking the server', async () => {
    const { user } = setup()
    await user.type(phoneBox(), '0171')
    await user.type(pinBox(), '12345')
    await user.click(submit())
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errInvalidPhone'))
    await user.clear(phoneBox())
    await user.type(phoneBox(), '01711000001')
    await user.clear(pinBox())
    await user.type(pinBox(), '12')
    await user.click(submit())
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errInvalidPin'))
    expect(api.login).not.toHaveBeenCalled()
  })

  it('only lets digits into the number and PIN boxes, and caps their length', async () => {
    const { user } = setup()
    await user.type(phoneBox(), '01a7-11 000001999')
    await user.type(pinBox(), '12ab3456789')
    expect(phoneBox()).toHaveValue('01711000001')
    expect(pinBox()).toHaveValue('12345')
  })

  it('shows a friendly message for a wrong PIN and for an unreachable server', async () => {
    api.login.mockRejectedValueOnce(new ApiError('wrong_credentials', 'x', 401))
    const { user } = setup()
    await user.type(phoneBox(), '01711000001')
    await user.type(pinBox(), '99999')
    await user.click(submit())
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errWrongCredentials'))
    api.login.mockRejectedValueOnce(new ApiError('network', 'x', 0))
    await user.click(submit())
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(t('errNetwork')))
  })

  it('creates an account, then logs in', async () => {
    api.register.mockResolvedValue({})
    api.login.mockResolvedValue({ token: 'tok', user: { name: 'Salma' } })
    const { onLoggedIn, user } = setup()
    await user.click(screen.getByRole('tab', { name: t('register') }))
    await user.type(screen.getByLabelText(t('fullName')), 'Salma Akter')
    await user.type(phoneBox(), '01711555555')
    await user.type(pinBox(), '24680')
    await user.click(screen.getByRole('button', { name: t('register') }))
    await waitFor(() => expect(onLoggedIn).toHaveBeenCalled())
    expect(api.register).toHaveBeenCalledWith('01711555555', 'Salma Akter', '24680')
  })

  it('needs a name to create an account', async () => {
    const { user } = setup()
    await user.click(screen.getByRole('tab', { name: t('register') }))
    await user.type(phoneBox(), '01711555555')
    await user.type(pinBox(), '24680')
    await user.click(screen.getByRole('button', { name: t('register') }))
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errInvalidName'))
    expect(api.register).not.toHaveBeenCalled()
  })

  it('fills in a demo account with one tap', async () => {
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: 'Rahim' }))
    expect(phoneBox()).toHaveValue('01711000001')
    expect(pinBox()).toHaveValue('12345')
  })

  it('shows a notice, for example after the session expired', () => {
    setup({ notice: t('errSession') })
    expect(screen.getByRole('alert')).toHaveTextContent(t('errSession'))
  })
})
