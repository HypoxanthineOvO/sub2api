import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CNProviderBalanceCell from '../CNProviderBalanceCell.vue'
import type { Account } from '@/types'

const { queryBalance } = vi.hoisted(() => ({
  queryBalance: vi.fn()
}))

vi.mock('@/api/admin', () => ({
  adminAPI: {
    cnProviders: { queryBalance }
  }
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, unknown>) =>
      params?.percent == null ? key : `${key}:${params.percent}`
  })
}))

const paygAccount = {
  id: 301,
  platform: 'kimi',
  type: 'apikey',
  credentials: { account_mode: 'payg' }
} as unknown as Account

describe('CNProviderBalanceCell', () => {
  beforeEach(() => {
    queryBalance.mockReset()
  })

  it('renders the persisted balance snapshot as static text', () => {
    const account = {
      ...paygAccount,
      extra: { kimi_balance: 12.5, kimi_balance_currency: 'CNY' }
    } as unknown as Account

    const wrapper = mount(CNProviderBalanceCell, { props: { account } })

    expect(wrapper.text()).toContain('CNY 12.50')
  })

  it('shows the low-balance badge from the snapshot marker', () => {
    const account = {
      ...paygAccount,
      extra: { kimi_balance: 0.4, kimi_balance_low: true }
    } as unknown as Account

    const wrapper = mount(CNProviderBalanceCell, { props: { account } })

    expect(wrapper.text()).toContain('admin.accounts.cnProviders.balanceLow')
  })

  it('exposes an explicit action button that triggers a manual balance query', async () => {
    queryBalance.mockResolvedValue({
      success: true,
      balance: 88.4,
      currency: 'CNY',
      available: true
    })
    const wrapper = mount(CNProviderBalanceCell, { props: { account: paygAccount } })

    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(queryBalance).toHaveBeenCalledWith(301)
    expect(wrapper.text()).toContain('CNY 88')
  })

  it('keeps the snapshot balance when a query fails', async () => {
    queryBalance.mockResolvedValue({ success: false, error: 'HTTP 401' })
    const account = {
      ...paygAccount,
      extra: { kimi_balance: 12.5, kimi_balance_currency: 'CNY' }
    } as unknown as Account

    const wrapper = mount(CNProviderBalanceCell, { props: { account } })
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('CNY 12.50')
    expect(wrapper.text()).toContain('HTTP 401')
  })
})
