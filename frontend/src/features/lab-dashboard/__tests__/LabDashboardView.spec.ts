import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import LabDashboardView from '../LabDashboardView.vue'

const { getLabDashboard } = vi.hoisted(() => ({ getLabDashboard: vi.fn() }))
vi.mock('@/api/labDashboard', () => ({ getLabDashboard }))

describe('LabDashboardView', () => {
  beforeEach(() => {
    getLabDashboard.mockReset()
    getLabDashboard.mockResolvedValue({
      generated_at: '2026-08-20T00:00:00Z', timezone: 'Asia/Shanghai',
      summary: { today_actual_cost: 1, today_requests: 2, active_users: 1, schedulable_accounts: 1, total_accounts: 1, week_actual_cost: 3 },
      accounts: [{ name: 'Card A', platform: 'openai', type: 'oauth', status: 'active', schedulable: true, quota_factor: .5, selection_probability: .75, selection_probability_status: 'computed', today_requests: 2, today_actual_cost: 1 }],
      leaderboard: { rows: [{ display_name: 'Alice', today_actual_cost: 1, total_actual_cost: 3 }] },
      user_usage_24h: [{ bucket: '10:00', display_name: 'Alice', requests: 2, actual_cost: 1 }],
      recent_usage: [{ created_at: '2026-08-20T00:00:00Z', user_display_name: 'Alice', model: 'gpt', account_name: 'Card A', actual_cost: 1 }]
    })
  })

  it('loads one allowlisted endpoint and renders every shared section without management controls', async () => {
    const wrapper = mount(LabDashboardView, { global: { stubs: { AppLayout: { template: '<div><slot /></div>' } } } })
    await flushPromises()
    expect(getLabDashboard).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('实验室仪表盘')
    expect(wrapper.text()).toContain('账号状态')
    expect(wrapper.text()).toContain('历史金额榜')
    expect(wrapper.text()).toContain('最近 24 小时用户消费')
    expect(wrapper.text()).toContain('最近使用记录')
    expect(wrapper.text()).not.toContain('编辑')
    expect(wrapper.text()).not.toContain('删除')
  })
})
