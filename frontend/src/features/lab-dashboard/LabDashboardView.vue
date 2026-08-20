<template>
  <AppLayout>
    <div class="glass-dash">
      <!-- 玻璃页面背景层（三层渐变，取自 --glass-page-bg） -->
      <div class="glass-page-bg pointer-events-none fixed inset-0" aria-hidden="true"></div>

      <div class="relative space-y-6">
        <!-- 页头 -->
        <div class="flex flex-wrap items-end justify-between gap-2">
          <div>
            <div class="text-[22px] font-bold tracking-tight glass-text">仪表盘</div>
            <div class="mt-0.5 text-xs glass-muted">{{ pageSub }}</div>
          </div>
        </div>

        <!-- Loading State -->
        <div v-if="initialLoading" class="flex items-center justify-center py-12">
          <LoadingSpinner />
        </div>

        <GlassCard v-else-if="loadError" role="alert" class="py-10 text-center">
          <p class="text-sm glass-muted">仪表盘数据加载失败，请稍后重试。</p>
          <button type="button" class="glass-dashboard-retry mt-4" @click="loadDashboard">重试</button>
        </GlassCard>

        <template v-else>
          <!-- 今日概览条 -->
          <GlassCard data-test="today-strip" class="glass-today-strip">
            <div class="glass-today-item">
              <div class="glass-today-v glass-num glass-accent-text">${{ formatCost(todayActualCost) }}</div>
              <div class="glass-today-k glass-muted">今日总消耗</div>
            </div>
            <div class="glass-today-sep"></div>
            <div class="glass-today-item">
              <div class="glass-today-v glass-num">{{ formatNumber(stats?.today_requests) }}</div>
              <div class="glass-today-k glass-muted">今日请求</div>
            </div>
            <div class="glass-today-sep"></div>
            <div class="glass-today-item">
              <div class="glass-today-v glass-num">{{ formatNumber(stats?.active_users) }}</div>
              <div class="glass-today-k glass-muted">今日活跃用户</div>
            </div>
            <div class="glass-today-sep"></div>
            <div class="glass-today-item">
              <div class="glass-today-v glass-num">
                {{ schedulableCount }}
                <span class="glass-muted text-xs font-medium">/ {{ accountCards.length }} 调度中</span>
              </div>
              <div class="glass-today-k glass-muted">可用卡</div>
            </div>
            <div class="glass-chip ml-auto">
              本周累计 <span class="glass-num">${{ formatCost(weekActualCost) }}</span>
            </div>
          </GlassCard>

          <!-- Provider 分组账户状态 -->
          <section data-test="account-status">
            <div class="glass-section-title">
              账户状态
            </div>
            <div class="provider-pools">
              <article
                v-for="group in providerGroups"
                :key="group.key"
                class="provider-pool"
                :class="{ 'provider-pool--wide': group.wide }"
                :data-provider="group.key"
              >
                <div class="provider-pool__header">
                  <h3>{{ group.label }}</h3>
                  <span class="glass-muted">{{ group.cards.length }} 个账号</span>
                </div>
                <div class="grid-cards grid items-stretch" :class="group.gridClass">
                  <GlassCard v-for="card in group.cards" :key="card.id" data-test="account-card" class="flex flex-col">
                    <div class="glass-card-head">
                      <div class="glass-card-name">
                        <div class="glass-provider-icon">{{ card.iconText }}</div>
                        <div class="min-w-0">
                          <div class="glass-card-title truncate" :title="card.name">{{ card.name }}</div>
                          <div class="glass-card-sub glass-muted">{{ card.sub }}</div>
                          <span
                            v-if="card.hasNodeBinding"
                            class="account-node-binding mt-1"
                            data-test="account-node-binding"
                            :title="card.nodeBindingTitle"
                          >{{ card.nodeBindingText }}</span>
                        </div>
                      </div>
                      <GlassChip :tone="card.paused ? 'stop' : 'ok'">
                        {{ card.paused ? pausedBadgeText(card) : '调度中' }}
                      </GlassChip>
                    </div>

                    <template v-if="card.quotaBased">
                      <div class="glass-waterline">
                        <div class="glass-waterline-row">
                          <span class="glass-muted">5 小时窗口</span>
                          <span class="glass-num">{{ percentText(card.fiveHour) }}</span>
                        </div>
                        <GlassBar :value="card.fiveHour ?? 0" />
                      </div>
                      <div class="glass-waterline">
                        <div class="glass-waterline-row">
                          <span class="glass-muted">周窗口</span>
                          <span class="glass-num">{{ percentText(card.sevenDay) }}</span>
                        </div>
                        <GlassBar :value="card.sevenDay ?? 0" variant="default" />
                      </div>
                      <div class="glass-waterline">
                        <div class="glass-waterline-row">
                          <span
                            class="glass-muted"
                            data-test="schedule-probability-label"
                            title="无粘性新会话首选概率估算；不包含请求级模型和 transport 过滤"
                          >主分组新会话基础选择概率</span>
                          <span class="glass-num">{{ percentText(probPercentMap[card.id] ?? null) }}</span>
                        </div>
                        <GlassBar :value="probPercentMap[card.id] ?? 0" :variant="card.paused ? 'mute' : 'default'" />
                      </div>
                      <div class="glass-card-foot glass-muted">
                        今日 {{ formatNumber(card.todayRequests) }} 请求 · 消耗
                        <span class="glass-num">${{ formatCost(card.todayCost) }}</span>
                      </div>
                    </template>
                    <div v-else class="billing-card-metrics">
                      <div>
                        <span class="glass-muted">今日费用</span>
                        <strong class="glass-num">${{ formatCost(card.todayCost) }}</strong>
                      </div>
                      <div>
                        <span class="glass-muted">今日请求</span>
                        <strong class="glass-num">{{ formatNumber(card.todayRequests) }}</strong>
                      </div>
                      <div class="billing-card-balance" data-test="account-balance">
                        <span class="glass-muted">
                          当前余额
                          <span v-if="card.balanceLow" class="balance-low" data-test="balance-low">余额偏低</span>
                        </span>
                        <strong class="glass-num" :title="balanceText(card.balances)">{{ balanceText(card.balances) }}</strong>
                      </div>
                    </div>
                  </GlassCard>
                </div>
              </article>
            </div>
          </section>

          <div
            class="grid gap-6 lg:grid-cols-2 lg:items-stretch"
            data-test="dashboard-operations-grid"
          >
          <!-- 按账号卡展示今日消费，不混入分组/Key 汇总 -->
          <section data-test="channel-usage" class="flex min-w-0 flex-col">
            <div class="glass-section-title">
              卡片消耗
            </div>
            <GlassCard class="flex-1" flush>
              <div v-if="accountCards.length > 0" class="divide-y divide-white/10">
                <div
                  v-for="card in accountCards"
                  :key="card.id"
                  class="grid grid-cols-[minmax(0,1fr)_auto] gap-3 px-4 py-3"
                  data-test="account-card-spend-row"
                >
                  <div class="min-w-0">
                    <div class="truncate text-sm font-semibold glass-text" :title="card.name">{{ card.name }}</div>
                    <div class="mt-0.5 truncate text-xs glass-muted" :title="card.sub">{{ card.sub }}</div>
                    <span
                      v-if="card.hasNodeBinding"
                      class="account-node-binding mt-1"
                      data-test="account-node-binding"
                      :title="card.nodeBindingTitle"
                    >{{ card.nodeBindingText }}</span>
                  </div>
                  <div class="text-right">
                    <div class="glass-num whitespace-nowrap font-semibold">${{ formatCost(card.todayCost) }}</div>
                    <div class="mt-0.5 whitespace-nowrap text-xs glass-muted">{{ formatNumber(card.todayRequests) }} 请求</div>
                  </div>
                </div>
              </div>
              <div v-else class="px-4 py-6 text-sm glass-muted">暂无数据</div>
            </GlassCard>
          </section>

          <!-- 排行榜（今日消耗 / 最近活跃 / 累计消耗） -->
          <section data-test="leaderboard" class="flex min-w-0 flex-col">
            <div class="flex flex-wrap items-baseline justify-between gap-2">
              <div class="glass-section-title">排行榜</div>
              <span class="text-xs font-normal glass-muted">{{ historyRangeText }}</span>
            </div>
            <GlassCard flush class="flex-1">
              <div class="overflow-hidden" data-test="leaderboard-scroll">
                <table class="glass-table leaderboard-table w-full table-fixed">
                  <thead>
                    <tr>
                      <th class="w-8 text-center" data-test="leaderboard-rank-header">#</th>
                      <th class="text-left">用户</th>
                      <th class="w-[18%] text-right" data-test="leaderboard-today-header" title="今日消耗">今日</th>
                      <th class="w-[22%] text-center" data-test="leaderboard-active-header" title="今日最后一次请求时间">最近活跃</th>
                      <th
                        class="w-[18%] text-right"
                        data-test="leaderboard-total-header"
                        title="累计消耗（当前保留数据）"
                      >累计</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, index) in leaderboardRows" :key="row.userId" class="glass-table-row">
                      <td class="text-center" data-test="leaderboard-rank-value">
                        <span
                          class="glass-rank-badge"
                          :class="index === 0 ? 'glass-rank-badge--first' : 'glass-muted'"
                        >
                          {{ index + 1 }}
                        </span>
                      </td>
                      <td class="truncate text-left font-medium" :title="row.name">{{ row.name }}</td>
                      <td class="glass-num text-right text-sm" data-test="leaderboard-today-value">${{ formatCost(row.todayCost) }}</td>
                      <td
                        class="glass-num whitespace-nowrap text-center text-sm"
                        data-test="leaderboard-active-value"
                        :title="formatLastActiveTitle(row.lastActiveAt)"
                      >{{ formatTime(row.lastActiveAt) }}</td>
                      <td class="glass-num text-right text-sm" data-test="leaderboard-total-value">
                        <template v-if="row.totalCost !== null">${{ formatCost(row.totalCost) }}</template>
                        <template v-else>—</template>
                      </td>
                    </tr>
                  <tr v-if="leaderboardRows.length === 0" class="glass-table-row">
                    <td colspan="5" class="py-6 text-center text-sm glass-muted">暂无数据</td>
                  </tr>
                </tbody>
              </table>
              </div>
            </GlassCard>
          </section>
          </div>

          <section data-test="user-usage-24h">
            <div class="glass-section-title">
              最近 24 小时用户消费
            </div>
            <GlassCard>
              <UserUsage24hChart
                :trend-data="userTrend"
                :loading="userTrendLoading"
                :error="userTrendError"
                @retry="loadUserUsage24h"
              />
            </GlassCard>
          </section>

          <!-- 最近使用记录（实际路由卡 + 切卡事件） -->
          <section data-test="recent-usage">
            <div class="glass-section-title">
              最近使用记录
            </div>
            <GlassCard flush>
              <div class="overflow-x-auto">
                <table class="glass-table">
                  <thead>
                    <tr>
                      <th>时间</th>
                      <th>用户</th>
                      <th>模型</th>
                      <th>实际路由卡</th>
                      <th class="text-right">消耗</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="log in recentUsage" :key="log.id" class="glass-table-row">
                      <td class="glass-muted font-mono">{{ formatTime(log.created_at) }}</td>
                      <td class="max-w-0 truncate">{{ usageUserName(log) }}</td>
                      <td class="font-mono">{{ log.model }}</td>
                      <td>
                        <template v-if="log.switch_from_account">
                          <span class="glass-muted line-through">{{ log.switch_from_account.name }}</span>
                          <span class="glass-faint"> → </span>
                          {{ log.account?.name || '—' }}
                          <GlassChip tone="swap" class="ml-1">
                            切卡{{ log.switch_reason ? ` · ${log.switch_reason}` : '' }}
                          </GlassChip>
                        </template>
                        <template v-else>{{ log.account?.name || '—' }}</template>
                      </td>
                      <td class="glass-num text-right">${{ formatCost(log.actual_cost) }}</td>
                    </tr>
                    <tr v-if="recentUsage.length === 0" class="glass-table-row">
                      <td colspan="5" class="py-6 text-center text-sm glass-muted">暂无数据</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </GlassCard>
          </section>
        </template>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getLabDashboard, type LabDashboardAccount, type LabDashboardResponse } from '@/api/labDashboard'
import type { UserUsageTrendPoint } from '@/types'
import '@/styles/glass.tokens.css'
import AppLayout from '@/components/layout/AppLayout.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import UserUsage24hChart from '@/components/charts/UserUsage24hChart.vue'
import { GlassCard, GlassChip, GlassBar } from '@/components/common/glass'

const data = ref<LabDashboardResponse | null>(null)
const initialLoading = ref(true)
const loadError = ref(false)
const userTrendLoading = ref(false)
const userTrendError = ref(false)

const toFiniteNumber = (value: unknown): number => {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

const formatNumber = (value: number | null | undefined): string =>
  toFiniteNumber(value).toLocaleString('zh-CN')

const formatCost = (value: number | null | undefined): string => {
  const safeValue = toFiniteNumber(value)
  if (safeValue >= 1_000_000) return `${(safeValue / 1_000_000).toFixed(2)}M`
  if (safeValue >= 1) return safeValue.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  if (safeValue >= 0.01) return safeValue.toFixed(3)
  return safeValue.toFixed(4)
}

const formatTime = (iso: string | null | undefined): string => {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

const formatLastActiveTitle = (iso: string | null | undefined): string => {
  if (!iso) return '暂无今日活跃记录'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '暂无今日活跃记录'
  return date.toLocaleString('zh-CN', { hour12: false })
}

const pageSub = computed(() => {
  const generatedAt = data.value?.generated_at ? new Date(data.value.generated_at) : new Date()
  const weekday = '日一二三四五六'[generatedAt.getDay()]
  return `${generatedAt.getFullYear()}年${generatedAt.getMonth() + 1}月${generatedAt.getDate()}日 · 周${weekday} · 数据每 5 分钟刷新`
})

const stats = computed(() => data.value?.summary ?? null)
const todayActualCost = computed(() => data.value?.summary.today_actual_cost ?? 0)
const weekActualCost = computed(() => data.value?.summary.week_actual_cost ?? 0)

interface AccountCardModel {
  id: string
  providerKey: string
  name: string
  sub: string
  iconText: string
  fiveHour: number | null
  sevenDay: number | null
  paused: boolean
  selectionProbability: number | null
  todayRequests: number
  todayCost: number
  nodeBindingText: string
  nodeBindingTitle: string
  hasNodeBinding: boolean
  quotaBased: boolean
  balances: Array<{ currency: string; balance: number }>
  balanceLow: boolean
  sortIndex: number
  planRank: number
}

const clampPercent = (value: unknown): number | null => {
  if (value === null || value === undefined) return null
  const number = Number(value)
  if (!Number.isFinite(number)) return null
  return Math.min(100, Math.max(0, Math.round(number)))
}

const percentText = (value: number | null): string => value === null ? '—' : `${value}%`

const formatBalance = (entry: { currency: string; balance: number }): string => {
  const currency = entry.currency.trim().toUpperCase() || 'CNY'
  const balance = toFiniteNumber(entry.balance)
  const formatted = balance >= 100
    ? balance.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
    : balance.toFixed(2)
  return `${currency} ${formatted}`
}

const balanceText = (balances: Array<{ currency: string; balance: number }>): string =>
  balances.length > 0 ? balances.map(formatBalance).join(' · ') : '—'

const accountQuotaPercent = (
  account: LabDashboardAccount,
  windows: string[],
  legacyValue: number | undefined
): number | null => {
  const quotaWindow = account.quota_windows?.find((item) => windows.includes(item.window.toLowerCase()))
  return clampPercent(quotaWindow?.used_percent ?? legacyValue)
}

const accountSelectionProbability = (account: LabDashboardAccount): number | null => {
  if (!account.schedulable || account.selection_probability_status === 'outside_first_choice_pool') return 0
  if (account.selection_probability_status !== 'computed') return null
  const probability = Number(account.selection_probability)
  if (!Number.isFinite(probability)) return null
  return Math.min(1, Math.max(0, probability))
}

const accountNodeBinding = (account: LabDashboardAccount): { text: string; title: string } => {
  const title = 'Mihomo Controller 当前选择节点，不代表单次请求实际出口'
  const slot = account.slot_label?.trim() || '未绑定代理'
  if (!account.selected_node_name?.trim()) return { text: `${slot}: 节点未知`, title }
  if (account.selected_node_status === 'stale') {
    return {
      text: `${slot}: ${account.selected_node_name}（缓存）`,
      title: `Mihomo Controller 缓存快照，观测于 ${account.selected_node_observed_at || '时间未知'}，不代表单次请求实际出口`
    }
  }
  return { text: `${slot}: ${account.selected_node_name}`, title }
}

const normalizeProvider = (platform: string): string => {
  const value = platform.trim().toLowerCase()
  if (value === 'zhipu') return 'glm'
  return value || 'other'
}

const providerLabel = (provider: string): string => ({
  openai: 'OpenAI',
  deepseek: 'DeepSeek',
  kimi: 'Kimi',
  glm: 'GLM',
  anthropic: 'Anthropic',
  gemini: 'Gemini',
  grok: 'Grok'
}[provider] || provider.charAt(0).toUpperCase() + provider.slice(1))

const providerIconText = (provider: string): string => ({
  openai: 'AI',
  deepseek: 'DS',
  kimi: 'KM',
  glm: 'GL'
}[provider] || provider.slice(0, 2).toUpperCase())

const accountPlanRank = (account: LabDashboardAccount): number => {
  const plan = (account.plan_type || account.name).toLowerCase()
  if (plan.includes('pro')) return 0
  if (plan.includes('plus')) return 2
  return 1
}

const accountCards = computed<AccountCardModel[]>(() =>
  (data.value?.accounts ?? []).map((account, index) => {
    const nodeBinding = accountNodeBinding(account)
    const providerKey = normalizeProvider(account.platform)
    const fiveHour = accountQuotaPercent(account, ['5h'], account.quota_5h_used_percent)
    const sevenDay = accountQuotaPercent(account, ['weekly', '7d'], account.quota_7d_used_percent)
    const quotaBased = account.billing_mode === 'coding' || (account.quota_windows?.length ?? 0) > 0
    const balances = (account.balances ?? []).filter((entry) =>
      typeof entry.currency === 'string' && Number.isFinite(Number(entry.balance))
    )
    return {
      id: `${account.name}-${index}`,
      providerKey,
      name: account.name,
      sub: [account.plan_type, account.type].filter(Boolean).join(' · ') || account.platform,
      iconText: providerIconText(providerKey),
      fiveHour,
      sevenDay,
      paused: !account.schedulable,
      selectionProbability: accountSelectionProbability(account),
      todayRequests: account.today_requests,
      todayCost: account.today_actual_cost,
      nodeBindingText: nodeBinding.text,
      nodeBindingTitle: nodeBinding.title,
      hasNodeBinding: Boolean(account.slot_label || account.selected_node_name),
      quotaBased,
      balances,
      balanceLow: account.balance_low === true,
      sortIndex: index,
      planRank: accountPlanRank(account)
    }
  }).sort((left, right) => left.planRank - right.planRank || left.sortIndex - right.sortIndex)
)

const schedulableCount = computed(() => accountCards.value.filter((card) => !card.paused).length)

const providerOrder = ['openai', 'deepseek', 'kimi', 'glm', 'anthropic', 'gemini', 'grok']
const providerGroups = computed(() => {
  const groups = new Map<string, AccountCardModel[]>()
  for (const card of accountCards.value) {
    const cards = groups.get(card.providerKey) ?? []
    cards.push(card)
    groups.set(card.providerKey, cards)
  }
  return [...groups.entries()]
    .sort(([left], [right]) => {
      const leftIndex = providerOrder.indexOf(left)
      const rightIndex = providerOrder.indexOf(right)
      return (leftIndex < 0 ? providerOrder.length : leftIndex) -
        (rightIndex < 0 ? providerOrder.length : rightIndex) || left.localeCompare(right)
    })
    .map(([key, cards]) => ({
      key,
      label: providerLabel(key),
      cards,
      wide: key === 'openai' || cards.length >= 3,
      gridClass: `cols-${Math.min(4, Math.max(1, cards.length))}`
    }))
})
const pausedBadgeText = (card: AccountCardModel): string =>
  card.fiveHour === null ? '已暂停' : `已暂停 · ${card.fiveHour}%`

const probPercentMap = computed<Record<string, number | null>>(() =>
  Object.fromEntries(accountCards.value.map((card) => [
    card.id,
    card.selectionProbability === null ? null : Math.round(card.selectionProbability * 100)
  ]))
)

interface LeaderboardRow {
  userId: string
  name: string
  todayCost: number
  lastActiveAt: string | null
  totalCost: number | null
}

const leaderboardRows = computed<LeaderboardRow[]>(() =>
  (data.value?.leaderboard.rows ?? [])
    .map((row, index) => ({
      userId: `${row.display_name}-${index}`,
      name: row.display_name,
      todayCost: row.today_actual_cost ?? 0,
      lastActiveAt: row.last_active_at ?? null,
      totalCost: row.total_actual_cost
    }))
    .sort((left, right) => right.todayCost - left.todayCost || right.totalCost! - left.totalCost!)
    .slice(0, 10)
)

const historyRangeText = computed(() => {
  const start = data.value?.leaderboard.history_start_date
  const end = data.value?.leaderboard.history_end_date
  if (start === 'retained' && end) return `当前保留数据 · 截至 ${end}`
  return start && end ? `${start} 至 ${end}` : '暂无保留数据'
})

const userNameIDs = computed(() => {
  const names = [...new Set((data.value?.user_usage_24h ?? []).map((row) => row.display_name))].sort()
  return new Map(names.map((name, index) => [name, index + 1]))
})

const userTrend = computed<UserUsageTrendPoint[]>(() =>
  (data.value?.user_usage_24h ?? []).map((row) => ({
    date: row.bucket,
    user_id: userNameIDs.value.get(row.display_name) ?? 0,
    email: '',
    username: row.display_name,
    requests: row.requests,
    tokens: 0,
    cost: row.actual_cost,
    actual_cost: row.actual_cost
  }))
)

const recentUsage = computed(() =>
  (data.value?.recent_usage ?? []).map((row, index) => ({
    id: `${row.created_at}-${index}`,
    created_at: row.created_at,
    user: { username: row.user_display_name, email: '' },
    model: row.model,
    account: row.account_name ? { name: row.account_name } : null,
    switch_from_account: row.switch_from_account_name ? { name: row.switch_from_account_name } : null,
    switch_reason: row.switch_reason,
    actual_cost: row.actual_cost
  }))
)

const usageUserName = (log: { user?: { username?: string; email?: string } | null }): string =>
  log.user?.username?.trim() || log.user?.email?.trim() || '—'

const loadDashboard = async () => {
  try {
    data.value = await getLabDashboard()
    loadError.value = false
    userTrendError.value = false
  } catch (error) {
    loadError.value = true
    userTrendError.value = true
    console.error('Failed to load lab dashboard:', error)
  }
}

const loadUserUsage24h = async () => {
  userTrendLoading.value = true
  try {
    await loadDashboard()
  } finally {
    userTrendLoading.value = false
  }
}

const REFRESH_INTERVAL_MS = 5 * 60 * 1000
let refreshTimer: number | undefined

onMounted(async () => {
  initialLoading.value = true
  try {
    await loadDashboard()
  } finally {
    initialLoading.value = false
  }
  refreshTimer = window.setInterval(() => void loadDashboard(), REFRESH_INTERVAL_MS)
})

onUnmounted(() => {
  if (refreshTimer !== undefined) window.clearInterval(refreshTimer)
})
</script>

<style scoped>
.account-node-binding {
  @apply inline-flex max-w-full truncate rounded-full border border-cyan-400/30 bg-cyan-400/10 px-2 py-0.5 text-[10px] font-medium text-cyan-700 dark:text-cyan-200;
}

.provider-pools {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.provider-pool {
  min-width: 0;
}

.provider-pool--wide {
  grid-column: 1 / -1;
}

.provider-pool__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.provider-pool__header h3 {
  font-size: 14px;
  font-weight: 700;
}

.provider-pool__header span {
  font-size: 11px;
}

.billing-card-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: auto;
  padding-top: 18px;
}

.billing-card-balance {
  grid-column: 1 / -1;
  min-width: 0;
  padding-top: 2px;
}

.billing-card-balance strong {
  overflow-wrap: anywhere;
  font-size: 15px;
}

.balance-low {
  @apply ml-1 inline-flex rounded border border-red-400/30 bg-red-400/10 px-1.5 py-0.5 text-[10px] font-medium text-red-700 dark:text-red-300;
}

.billing-card-metrics > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.billing-card-metrics span {
  font-size: 11px;
}

.billing-card-metrics strong {
  font-size: 18px;
}

.glass-dashboard-retry {
  min-height: 40px;
  padding: 0 16px;
  border: 1px solid var(--glass-card-border);
  border-radius: 6px;
  color: var(--glass-text);
  background: var(--glass-card-bg);
}

@media (max-width: 900px) {
  .provider-pools {
    grid-template-columns: minmax(0, 1fr);
  }

  .provider-pool--wide {
    grid-column: auto;
  }
}

.leaderboard-table th,
.leaderboard-table td {
  @apply px-1.5;
}

.leaderboard-table .text-center {
  text-align: center;
}

.leaderboard-table .text-right {
  text-align: right;
}
</style>
