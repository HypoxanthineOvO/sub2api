import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { probe } = vi.hoisted(() => ({ probe: vi.fn() }))

vi.mock('@/api/admin', () => ({
  adminAPI: { accounts: { probeNewAPIManagement: probe } }
}))
vi.mock('vue-i18n', async () => {
  const actual = await vi.importActual<typeof import('vue-i18n')>('vue-i18n')
  return {
    ...actual,
    useI18n: () => ({ t: (key: string, params?: Record<string, unknown>) => params ? `${key}:${JSON.stringify(params)}` : key })
  }
})

import NewAPIManagementCell from '../NewAPIManagementCell.vue'

const account = (snapshot?: Record<string, unknown>) => ({
  id: 9,
  platform: 'anthropic',
  type: 'apikey',
  credentials: { newapi_management_enabled: true, newapi_management_base_url: 'https://relay.example.com' },
  credentials_status: { has_newapi_management_token: true },
  extra: snapshot ? { newapi_management_snapshot: snapshot } : {}
} as any)

describe('NewAPIManagementCell', () => {
  beforeEach(() => probe.mockReset())

  it('renders a persisted balance and cumulative usage', () => {
    const wrapper = mount(NewAPIManagementCell, {
      props: { account: account({ status: 'ok', balance_usd: 2.002, used_usd: 1997.998, request_count: 12 }) }
    })

    expect(wrapper.text()).toContain('$2.00')
    expect(wrapper.text()).toContain('$1998.00')
    expect(wrapper.get('[data-testid="newapi-management-probe"]').attributes('title')).toContain('requestCount')
  })

  it('keeps the previous balance when a refresh returns a failed snapshot', async () => {
    probe.mockResolvedValue({ status: 'failed', error: 'HTTP 401' })
    const wrapper = mount(NewAPIManagementCell, {
      props: { account: account({ status: 'ok', balance_usd: 3, used_usd: 7 }) }
    })

    await wrapper.get('[data-testid="newapi-management-probe"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('$3.00')
    expect(wrapper.text()).toContain('HTTP 401')
    expect(wrapper.emitted('updated')).toBeUndefined()
  })

  it('shows pending instead of a zero balance without a snapshot', () => {
    const wrapper = mount(NewAPIManagementCell, { props: { account: account() } })
    expect(wrapper.text()).toContain('admin.accounts.newapiManagement.pending')
    expect(wrapper.text()).not.toContain('$0.00')
  })
})
