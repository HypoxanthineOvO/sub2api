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
      accounts: [
        { name: 'Card A', platform: 'openai', type: 'oauth', status: 'active', schedulable: true, quota_5h_used_percent: 20, quota_7d_used_percent: 40, quota_factor: .5, selection_probability: .75, selection_probability_status: 'computed', today_requests: 2, today_actual_cost: 1 },
        { name: 'Card B', platform: 'openai', type: 'oauth', status: 'active', schedulable: true, quota_5h_used_percent: 0, quota_7d_used_percent: 10, quota_factor: 1, selection_probability_status: 'outside_first_choice_pool', today_requests: 3, today_actual_cost: .25 },
        { name: 'Card C', platform: 'openai', type: 'oauth', status: 'disabled', schedulable: false, quota_5h_used_percent: 0, quota_7d_used_percent: 100, quota_factor: 1, selection_probability_status: 'unavailable', today_requests: 0, today_actual_cost: 0 },
        { name: 'DeepSeek Billed', platform: 'deepseek', type: 'apikey', status: 'active', schedulable: true, quota_factor: 1, selection_probability_status: 'unavailable', today_requests: 9, today_actual_cost: 2.5 },
        { name: 'GLM Billed', platform: 'zhipu', type: 'apikey', status: 'active', schedulable: true, quota_factor: 1, selection_probability_status: 'unavailable', today_requests: 4, today_actual_cost: .5 }
      ],
      leaderboard: { rows: [{ display_name: 'Alice', today_actual_cost: 1, total_actual_cost: 3 }] },
      user_usage_24h: [{ bucket: '10:00', display_name: 'Alice', requests: 2, actual_cost: 1 }],
      recent_usage: [{ created_at: '2026-08-20T00:00:00Z', user_display_name: 'Alice', model: 'gpt', account_name: 'Card A', actual_cost: 1 }]
    })
  })

  it('loads one allowlisted endpoint and renders every shared section without management controls', async () => {
    const wrapper = mount(LabDashboardView, {
      global: {
        stubs: {
          AppLayout: { template: '<div><slot /></div>' },
          LoadingSpinner: true,
          UserUsage24hChart: { template: '<div data-test="user-usage-line-chart" />' }
        }
      }
    })
    await flushPromises()
    expect(getLabDashboard).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('仪表盘')
    expect(wrapper.text()).toContain('账户状态')
    expect(wrapper.text()).toContain('主分组新会话基础选择概率')
    expect(wrapper.text()).toContain('75%')
    expect(wrapper.text()).toContain('0%')
    expect(wrapper.text()).toContain('卡片消耗')
    expect(wrapper.text()).toContain('排行榜')
    expect(wrapper.text()).toContain('最近 24 小时用户消费')
    expect(wrapper.text()).toContain('最近使用记录')
    expect(wrapper.text()).toContain('已暂停')
    expect(wrapper.findAll('[data-test="account-card"]')).toHaveLength(5)
    expect(wrapper.get('[data-provider="openai"]').text()).toContain('3 个账号')
    expect(wrapper.get('[data-provider="deepseek"]').text()).toContain('今日费用')
    expect(wrapper.get('[data-provider="deepseek"]').text()).toContain('$2.5')
    expect(wrapper.get('[data-provider="glm"]').text()).toContain('GLM Billed')
    expect(wrapper.get('[data-provider="glm"]').text()).not.toContain('5 小时窗口')
    expect(wrapper.text()).not.toContain('编辑')
    expect(wrapper.text()).not.toContain('删除')
  })
})
