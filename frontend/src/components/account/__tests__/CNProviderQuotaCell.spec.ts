import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CNProviderQuotaCell from '../CNProviderQuotaCell.vue'
import type { Account } from '@/types'

const { queryQuota } = vi.hoisted(() => ({
  queryQuota: vi.fn()
}))

vi.mock('@/api/admin', () => ({
  adminAPI: {
    cnProviders: { queryQuota }
  }
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, unknown>) =>
      params?.percent == null ? key : `${key}:${params.percent}`
  })
}))

const codingAccount = {
  id: 201,
  platform: 'zhipu',
  type: 'apikey',
  credentials: { account_mode: 'coding' }
} as unknown as Account

const freshAccount = { ...codingAccount, id: 202 } as Account

describe('CNProviderQuotaCell', () => {
  beforeEach(() => {
    queryQuota.mockReset()
  })

  it('renders snapshot bars on mount without probing when snapshot is fresh', async () => {
    queryQuota.mockResolvedValue({ success: true, tiers: [] })
    const account = {
      ...codingAccount,
      extra: {
        zhipu_5h_used_percent: 42,
        zhipu_5h_reset_at: new Date(Date.now() + 3_600_000).toISOString(),
        zhipu_weekly_used_percent: 25,
        zhipu_weekly_reset_at: new Date(Date.now() + 86_400_000).toISOString(),
        zhipu_usage_updated_at: new Date().toISOString()
      }
    } as unknown as Account

    const wrapper = mount(CNProviderQuotaCell, { props: { account } })
    await flushPromises()

    expect(wrapper.text()).toContain('42%')
    expect(wrapper.text()).toContain('25%')
    // Fresh snapshot: no auto probe request is issued
    expect(queryQuota).not.toHaveBeenCalled()
  })

  it('auto-probes on mount when snapshot is stale or missing', async () => {
    queryQuota.mockResolvedValue({
      success: true,
      tiers: [
        { window: '5h', used_percent: 60 },
        { window: 'weekly', used_percent: 30 }
      ]
    })
    const wrapper = mount(CNProviderQuotaCell, { props: { account: freshAccount } })
    await flushPromises()

    expect(queryQuota).toHaveBeenCalledWith(202)
    expect(wrapper.text()).toContain('60%')
    expect(wrapper.text()).toContain('30%')
  })

  it('exposes an explicit action button that triggers a manual refresh', async () => {
    queryQuota.mockResolvedValue({
      success: true,
      tiers: [{ window: '5h', used_percent: 80 }]
    })
    const wrapper = mount(CNProviderQuotaCell, { props: { account: freshAccount } })
    await flushPromises()
    queryQuota.mockClear()

    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(queryQuota).toHaveBeenCalledWith(202)
    expect(wrapper.text()).toContain('80%')
  })

  it('keeps snapshot bars visible when a probe fails', async () => {
    queryQuota.mockResolvedValue({ success: false, error: 'upstream 500' })
    const account = {
      ...codingAccount,
      extra: {
        zhipu_5h_used_percent: 42,
        zhipu_weekly_used_percent: 25,
        zhipu_usage_updated_at: new Date().toISOString()
      }
    } as unknown as Account

    const wrapper = mount(CNProviderQuotaCell, { props: { account } })
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('42%')
    expect(wrapper.text()).toContain('upstream 500')
  })
})
