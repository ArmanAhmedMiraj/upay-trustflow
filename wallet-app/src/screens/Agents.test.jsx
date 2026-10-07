import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api.js'
import ForecastChart from '../components/ForecastChart.jsx'
import { makeT } from '../i18n.js'
import AgentHome from './AgentHome.jsx'
import AgentsTab from './AgentsTab.jsx'

vi.mock('../api.js', async (importOriginal) => {
  const real = await importOriginal()
  return { ...real, api: {
    agentForecast: vi.fn(), agentRefillRequest: vi.fn(), agentRefillRequests: vi.fn(),
    opsAgents: vi.fn(), opsAgent: vi.fn(), opsCoverage: vi.fn(), opsLiquidityReport: vi.fn(), opsRefillRequests: vi.fn(), dispatchRefill: vi.fn() } }
})
import { api } from '../api.js'

const t = makeT('en')
const hours = Array.from({ length: 48 }, (_, i) => (8 + i) % 24)
const series = (base) => hours.map((h) => Math.round(base * (h >= 9 && h <= 19 ? 1.5 : 0.3)))
const RED = {
  agent_id: 0, name: 'Agent Babul', area: 'Chawkbazar', area_type: 'market', lat: 23.717, lng: 90.397, status: 'red', day: 74,
  cash_now: 31612, float_now: 90000, need_cash_24h: 104245, need_float_24h: 50000, refill_cash: 72633, refill_float: 0,
  runout_hours_from_now: 5, runout_label: 'Today 1:00 pm', runout_label_bn: 'আজ দুপুর ১টা', p50_out_24h: 80000, p90_out_24h: 104000,
  briefing_en: 'Your cash may run out around today 1:00 pm. Add ৳72,633 cash before then.', briefing_bn: 'আজ দুপুর ১টা-এর দিকে আপনার নগদ শেষ হয়ে যেতে পারে।',
  hours, p50_out: series(6000), p90_out: series(9000), p50_in: series(3000), p90_in: series(4000),
  cash_path_plan: hours.map((_, i) => 31612 - i * 4000), float_path_plan: hours.map((_, i) => 90000 - i * 800),
}
const GREEN = { ...RED, status: 'green', refill_cash: 0, runout_label: null, runout_hours_from_now: null, briefing_en: 'You have enough cash for the next 24 hours.', briefing_bn: 'আগামী ২৪ ঘণ্টার জন্য আপনার নগদ যথেষ্ট।' }
const user = { id: 5, name: 'Agent Babul', role: 'agent', phone: '01811000001', balance: 0 }

function home(props = {}) {
  const onLogout = vi.fn(), onToggleLang = vi.fn()
  render(<AgentHome user={user} t={t} lang="en" onToggleLang={onToggleLang} onLogout={onLogout} {...props} />)
  return { onLogout, onToggleLang, u: userEvent.setup() }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.agentForecast.mockResolvedValue(RED)
  api.agentRefillRequests.mockResolvedValue({ requests: [] })
})

describe('Agent phone screen', () => {
  it('tells the agent in plain words when the cash runs out and how much to add', async () => {
    home()
    expect(await screen.findByText(t('statusRed'))).toBeInTheDocument()
    expect(screen.getByText(/Today 1:00 pm/)).toBeInTheDocument()
    const figure = (label) => screen.getByText(label).closest('div')
    expect(figure(t('cashOnHand'))).toHaveTextContent('৳31,612')
    expect(figure(t('cashNeeded'))).toHaveTextContent('৳1,04,245')
    expect(figure(t('addCash'))).toHaveTextContent('৳72,633')
    expect(screen.getByText(/Add ৳72,633 cash before then/)).toBeInTheDocument()
    expect(api.agentForecast).toHaveBeenCalledWith('festival')
  })

  it('shows the briefing in Bangla in Bangla mode', async () => {
    const bn = makeT('bn')
    home({ t: bn, lang: 'bn' })
    expect(await screen.findByText(bn('statusRed'))).toBeInTheDocument()
    expect(screen.getByText(/আজ দুপুর ১টা-এর দিকে/)).toBeInTheDocument()
    expect(screen.getByText(/৳৭২,৬৩৩/)).toBeInTheDocument()
    expect(screen.getByText(`${bn('runsOutAt')}: আজ দুপুর ১টা`)).toBeInTheDocument()          // no English left in the Bangla screen
    expect(screen.queryByText(/Today/)).not.toBeInTheDocument()
  })

  it('asks upay for the refill with one tap, and shows the request', async () => {
    api.agentRefillRequest.mockResolvedValue({ request: { id: 1 } })
    api.agentRefillRequests.mockResolvedValueOnce({ requests: [] })
    api.agentRefillRequests.mockResolvedValue({ requests: [{ id: 1, cash_bdt: 72633, status: 'open', created_at: new Date().toISOString().slice(0, 19) }] })
    const { u } = home()
    await u.click(await screen.findByRole('button', { name: t('requestRefill') }))
    await waitFor(() => expect(api.agentRefillRequest).toHaveBeenCalledWith('festival'))
    expect(await screen.findByRole('status')).toHaveTextContent(t('requestSent'))
    expect(await screen.findByText(t('reqOpen'))).toBeInTheDocument()
  })

  it('shows a dispatched request as on its way', async () => {
    api.agentRefillRequests.mockResolvedValue({ requests: [{ id: 1, cash_bdt: 72633, status: 'dispatched', created_at: '2026-10-04T08:00:00' }] })
    home()
    expect(await screen.findByText(t('reqDispatched'))).toBeInTheDocument()
  })

  it('has no request button when no refill is needed', async () => {
    api.agentForecast.mockResolvedValue(GREEN)
    home()
    expect(await screen.findByText(t('statusGreen'))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: t('requestRefill') })).not.toBeInTheDocument()
    expect(screen.getByText(new RegExp(t('nothingNeeded')))).toBeInTheDocument()
  })

  it('switches the demo day', async () => {
    const { u } = home()
    await screen.findByText(t('statusRed'))
    api.agentForecast.mockResolvedValue(GREEN)
    await u.click(screen.getByRole('button', { name: t('scenarioNormal') }))
    await waitFor(() => expect(api.agentForecast).toHaveBeenLastCalledWith('normal'))
    expect(await screen.findByText(t('statusGreen'))).toBeInTheDocument()
  })

  it('explains problems clearly', async () => {
    api.agentForecast.mockRejectedValue(new ApiError('network', 'x', 0))
    home()
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errNetwork'))
  })

  it('logs out and changes language', async () => {
    const { u, onLogout, onToggleLang } = home()
    await u.click(await screen.findByRole('button', { name: t('logout') }))
    await u.click(screen.getByRole('button', { name: /change language/ }))
    expect(onLogout).toHaveBeenCalled(); expect(onToggleLang).toHaveBeenCalled()
  })
})

// ------------------------------------------------------------------ operations tab
const agentRow = (id, status, name, area, cash, runout, refill) => ({ ...RED, agent_id: id, status, name, area, cash_now: cash, runout_label: runout, refill_cash: refill })
const OVERVIEW = {
  day: 74, scenario: 'festival', calendar: { day_of_month: 15, weekday: 'Fri', payday: false, festival_rush: true, days_to_festival: 0 },
  counts: { red: 2, yellow: 0, green: 1 }, total_refill_cash: 190000, total_refill_float: 0,
  agents: [agentRow(0, 'red', 'Agent Babul', 'Chawkbazar', 31612, 'Today 1:00 pm', 72633), agentRow(1, 'red', 'Agent #2', 'Mirpur-10', 20000, 'Today 11:00 am', 118000),
           agentRow(2, 'green', 'Agent #3', 'Uttara', 90000, null, 0)],
}
const REPORT = {
  quality: { p90_coverage_cash_out: 0.927, p90_coverage_festival_hours: 0.951, pinball_p50_model: 688, pinball_p50_same_hour_last_week: 2093 },
  policy: {
    plan_mix: 0.6, tradeoff: [{ mix: 0, missed_share: 0.066, avg_cash_held: 35000 }, { mix: 0.6, missed_share: 0.0014, avg_cash_held: 64000 }],
    guess_from_last_week_plus_20pct: { unmet_bdt: 8e7, demand_bdt: 3e8, avg_cash_held: 72000, topups_bdt: 1.1e8, by_day_type: { normal: { missed_share: 0 }, payday: { missed_share: 0.27 }, festival: { missed_share: 0.45 } } },
    guess_with_same_average_cash: { unmet_bdt: 8.4e7, demand_bdt: 3e8, avg_cash_held: 64000, topups_bdt: 1.1e8, by_day_type: { normal: { missed_share: 0.001 }, payday: { missed_share: 0.31 }, festival: { missed_share: 0.47 } } },
    forecast_driven: { unmet_bdt: 4.2e5, demand_bdt: 3e8, avg_cash_held: 64000, topups_bdt: 1.8e8, by_day_type: { normal: { missed_share: 0.004 }, payday: { missed_share: 0.003 }, festival: { missed_share: 0 } } },
  },
  agents: 120, train_days: [28, 69], test_days: [70, 89],
}
const COVERAGE = { agents: [], recommendations: [{ area: 'Jatrabari', lat: 23.71, lng: 90.43, times_city_median: 1.8, reason: 'Each of the 3 agents near Jatrabari handles about 1.8x the typical load.' }] }

describe('Operations: Agents tab', () => {
  beforeEach(() => {
    api.opsAgents.mockResolvedValue(OVERVIEW)
    api.opsAgent.mockResolvedValue(RED)
    api.opsCoverage.mockResolvedValue(COVERAGE)
    api.opsLiquidityReport.mockResolvedValue(REPORT)
    api.opsRefillRequests.mockResolvedValue({ requests: [] })
  })

  it('shows how many agents will run short and how much cash to deliver', async () => {
    render(<AgentsTab />)
    const kpi = async (label) => (await screen.findByText(label)).closest('.kpi')
    expect(await kpi('Will run short within 24 hours')).toHaveTextContent('2')
    expect(await kpi('Enough cash')).toHaveTextContent('1')
    expect(await kpi('Cash to deliver today')).toHaveTextContent('৳1,90,000')
    expect(screen.getByText(/festival rush/)).toBeInTheDocument()
    expect(api.opsAgents).toHaveBeenCalledWith('festival')
  })

  it('lists the agents who need cash first, with when they run out and the top-up', async () => {
    render(<AgentsTab />)
    const row = (await screen.findByText('Agent #2')).closest('tr')
    expect(row).toHaveTextContent('Mirpur-10'); expect(row).toHaveTextContent('Today 11:00 am'); expect(row).toHaveTextContent('৳1,18,000')
    expect(screen.getByText('Agent #3').closest('tr')).toHaveTextContent('–')
  })

  it('opens an agent: numbers, charts and the message in both languages', async () => {
    const u = userEvent.setup()
    render(<AgentsTab />)
    await u.click((await screen.findByText('Agent #2')).closest('tr'))
    await waitFor(() => expect(api.opsAgent).toHaveBeenLastCalledWith(1, 'festival'))
    expect(await screen.findByText(/Message to the agent \(English\)/)).toBeInTheDocument()
    expect(screen.getByText(/আজ দুপুর ১টা-এর দিকে/)).toBeInTheDocument()
    expect(screen.getAllByRole('img').length).toBeGreaterThanOrEqual(3)          // map + two charts
  })

  it('switches the day and reloads', async () => {
    const u = userEvent.setup()
    render(<AgentsTab />)
    await screen.findByText('Agent #2')
    api.opsAgents.mockResolvedValue({ ...OVERVIEW, scenario: 'normal', counts: { red: 0, yellow: 0, green: 3 }, total_refill_cash: 0, calendar: { ...OVERVIEW.calendar, festival_rush: false, days_to_festival: 10 } })
    await u.click(screen.getByRole('button', { name: 'A normal day' }))
    await waitFor(() => expect(api.opsAgents).toHaveBeenLastCalledWith('normal'))
    const kpi = (await screen.findByText('Enough cash')).closest('.kpi')
    await waitFor(() => expect(kpi).toHaveTextContent('3'))
  })

  it('dispatches a refill request', async () => {
    api.opsRefillRequests.mockResolvedValue({ requests: [{ id: 7, agent: { name: 'Agent Babul' }, cash_bdt: 72633, float_bdt: 0, needed_by: 'Today 1:00 pm', status: 'open' }] })
    api.dispatchRefill.mockResolvedValue({})
    const u = userEvent.setup()
    render(<AgentsTab />)
    expect(await screen.findByText(/asks for ৳72,633/)).toBeInTheDocument()
    await u.click(screen.getByRole('button', { name: 'Dispatch' }))
    await waitFor(() => expect(api.dispatchRefill).toHaveBeenCalledWith(7))
  })

  it('names where another agent would help most and why', async () => {
    render(<AgentsTab />)
    expect(await screen.findByText('Jatrabari')).toBeInTheDocument()
    expect(screen.getByText(/1.8× busier than typical/)).toBeInTheDocument()
    expect(screen.getByText(/handles about 1.8x the typical load/)).toBeInTheDocument()
  })

  it('shows the evidence, including the cost and where the gain comes from', async () => {
    render(<AgentsTab />)
    const heading = await screen.findByText(/Does the forecast work/)
    const panel = heading.closest('.evidence')
    expect(panel).toHaveTextContent('Refill from the forecast')
    expect(within(panel).getByText('Refill from last week, same average cash').closest('tr')).toHaveTextContent('47.0%')
    expect(panel).toHaveTextContent('prove the method, not performance on real upay data')
    expect(panel).toHaveTextContent('more cash through refills')
    expect(panel).toHaveTextContent('The safety dial')
  })

  it('explains problems clearly', async () => {
    api.opsAgents.mockRejectedValue(new ApiError('network', 'x', 0))
    render(<AgentsTab />)
    expect(await screen.findByRole('alert')).toHaveTextContent(t('errNetwork'))
  })
})

describe('Forecast chart', () => {
  it('draws one bar per hour and a cash line, with a red zone when cash goes below zero', () => {
    const { container } = render(<ForecastChart data={RED} labels={{ demand: 'Demand', normal: 'Normal', busy: 'Busy', cash: 'Cash' }} />)
    expect(container.querySelectorAll('rect.bar-normal')).toHaveLength(48)
    expect(container.querySelector('path.line-cash')).toBeTruthy()
    expect(container.querySelector('rect.below-zero')).toBeTruthy()
    expect(screen.getByRole('img', { name: 'Cash' })).toBeInTheDocument()
  })

  it('has no red zone when the agent has enough cash', () => {
    const { container } = render(<ForecastChart data={{ ...GREEN, cash_path_plan: hours.map(() => 50000) }} labels={{ demand: 'D', normal: 'N', busy: 'B', cash: 'C' }} />)
    expect(container.querySelector('rect.below-zero')).toBeNull()
  })
})
