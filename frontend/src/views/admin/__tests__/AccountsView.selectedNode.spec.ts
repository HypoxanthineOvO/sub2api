import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import AccountsView from '../AccountsView.vue'

const { listAccounts, listWithEtag, getBatchTodayStats, getAllProxies, getAllGroups } = vi.hoisted(() => ({
  listAccounts: vi.fn(),
  listWithEtag: vi.fn(),
  getBatchTodayStats: vi.fn(),
  getAllProxies: vi.fn(),
  getAllGroups: vi.fn()
}))

vi.mock('@/api/admin', () => ({
  adminAPI: {
    accounts: {
      list: listAccounts,
      listWithEtag,
      getBatchTodayStats,
      getUpstreamBillingProbeSettings: vi.fn().mockResolvedValue({ enabled: true, interval_minutes: 30 })
    },
    proxies: { getAll: getAllProxies },
    groups: { getAll: getAllGroups }
  }
}))

vi.mock('@/stores/app', () => ({
  useAppStore: () => ({ showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn() })
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ token: 'test-token' })
}))

vi.mock('vue-i18n', async () => {
  const actual = await vi.importActual<typeof import('vue-i18n')>('vue-i18n')
  return { ...actual, useI18n: () => ({ t: (key: string) => key }) }
})

const accounts = [
  {
    id: 1,
    name: 'stale-account',
    platform: 'openai',
    type: 'oauth',
    status: 'active',
    schedulable: true,
    proxy_id: 1,
    proxy: {
      id: 1,
      name: 'llm-mihomo-slot-a',
      selected_node_status: 'stale',
      selected_node_name: '新加坡-SG-02',
      selected_node_observed_at: '2026-08-17T08:00:00Z'
    }
  },
  {
    id: 2,
    name: 'unavailable-account',
    platform: 'openai',
    type: 'oauth',
    status: 'active',
    schedulable: true,
    proxy_id: 2,
    proxy: {
      id: 2,
      name: 'llm-mihomo-slot-b',
      selected_node_status: 'unavailable',
      selected_node_name: '旧节点不得显示'
    }
  }
]

const DataTableStub = {
  props: ['data'],
  template: `
    <div>
      <div data-test="desktop-proxy-column">
        <div v-for="row in data" :key="'desktop-' + row.id" :data-row-id="row.id">
          <slot name="cell-proxy" :row="row" />
        </div>
      </div>
      <div data-test="mobile-proxy-column">
        <div v-for="row in data" :key="'mobile-' + row.id" :data-row-id="row.id">
          <slot name="cell-proxy" :row="row" />
        </div>
      </div>
    </div>
  `
}

const mountView = () => mount(AccountsView, {
  global: {
    stubs: {
      AppLayout: { template: '<div><slot /></div>' },
      TablePageLayout: { template: '<div><slot name="filters" /><slot name="table" /><slot name="pagination" /></div>' },
      DataTable: DataTableStub,
      Pagination: true,
      AccountTableActions: true,
      AccountTableFilters: true,
      AccountBulkActionsBar: true,
      AccountActionMenu: true,
      ImportDataModal: true,
      ReAuthAccountModal: true,
      AccountTestModal: true,
      AccountStatsModal: true,
      ScheduledTestsPanel: true,
      SyncFromCrsModal: true,
      TempUnschedStatusModal: true,
      ErrorPassthroughRulesModal: true,
      TLSFingerprintProfilesModal: true,
      CreateAccountModal: true,
      EditAccountModal: true,
      BulkEditAccountModal: true,
      PlatformTypeBadge: true,
      AccountStatusIndicator: true,
      AccountWindowCell: true,
      UpstreamBillingRateCell: true,
      ProviderIcon: true,
      Icon: true
    }
  }
})

describe('AccountsView selected Controller node column', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('account-hidden-columns', '[]')
    localStorage.setItem('account-hidden-columns-version', 'scheduler-score-hidden-by-default')
    listAccounts.mockResolvedValue({ items: accounts, total: 2, page: 1, page_size: 20, pages: 1 })
    listWithEtag.mockResolvedValue({ notModified: true, etag: null, data: null })
    getBatchTodayStats.mockResolvedValue({ stats: {} })
    getAllProxies.mockResolvedValue([])
    getAllGroups.mockResolvedValue([])
  })

  it.each(['desktop-proxy-column', 'mobile-proxy-column'])('%s renders accessible stale and unavailable states', async (hook) => {
    const wrapper = mountView()
    await flushPromises()
    const column = wrapper.get(`[data-test="${hook}"]`)
    const stale = column.get('[data-row-id="1"]')
    const staleNode = stale.get('[data-selected-node-status="stale"]')
    expect(staleNode.text()).toContain('新加坡-SG-02（缓存）')
    expect(staleNode.text()).toContain('观测于 2026-08-17T08:00:00Z')
    expect(stale.get('button[data-test="selected-node-help"]').attributes('aria-label')).toContain('节点状态说明')

    const unavailable = column.get('[data-row-id="2"]')
    expect(unavailable.get('[data-selected-node-status="unavailable"]').text()).toContain('节点不可用')
    expect(unavailable.text()).not.toContain('旧节点不得显示')
    wrapper.unmount()
  })
})

