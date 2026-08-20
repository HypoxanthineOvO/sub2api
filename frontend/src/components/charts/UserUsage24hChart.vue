<template>
  <div v-if="loading" class="flex h-48 items-center justify-center sm:h-56">
    <LoadingSpinner />
  </div>

  <div
    v-else-if="error"
    data-test="user-usage-error"
    role="alert"
    class="flex h-48 flex-col items-center justify-center gap-3 text-sm glass-muted sm:h-56"
  >
    <span>用户消费金额加载失败</span>
    <button type="button" class="glass-retry-button" @click="emit('retry')">重试</button>
  </div>

  <div
    v-else-if="trendData.length === 0"
    class="flex h-48 items-center justify-center text-sm glass-muted sm:h-56"
  >
    最近 24 小时暂无消费
  </div>

  <div v-else>
    <div
      data-test="user-usage-chart-frame"
      class="h-48 sm:h-56"
      aria-label="最近 24 小时 Top 12 用户实际消费金额曲线"
    >
      <Line data-test="user-usage-line-chart" :data="chartData" :options="lineOptions" />
    </div>

    <p class="sr-only" aria-live="polite">
      共 {{ chartData.datasets.length }} 位用户，{{ chartData.labels.length }} 个小时数据点。
    </p>

    <details data-test="user-usage-table" class="glass-chart-details mt-3">
      <summary>查看小时明细</summary>
      <div class="mt-2 overflow-x-auto">
        <table class="glass-table w-full">
          <thead>
            <tr>
              <th>小时</th>
              <th>用户</th>
              <th class="text-right">请求</th>
              <th class="text-right">消费金额</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in detailRows" :key="`${row.date}-${row.userId}`" class="glass-table-row">
              <td class="whitespace-nowrap font-mono glass-muted">{{ row.date }}</td>
              <td>{{ row.label }}</td>
              <td class="text-right glass-num">{{ formatNumber(row.requests) }}</td>
              <td class="text-right glass-num">{{ formatCurrency(row.actualCost) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip
} from 'chart.js'
import { Line } from 'vue-chartjs'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import type { UserUsageTrendPoint } from '@/types'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend)

const props = withDefaults(
  defineProps<{
    trendData: UserUsageTrendPoint[]
    loading?: boolean
    error?: boolean
  }>(),
  {
    loading: false,
    error: false
  }
)

const emit = defineEmits<{
  retry: []
}>()

const palette = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444',
  '#8b5cf6', '#ec4899', '#14b8a6', '#f97316',
  '#6366f1', '#84cc16', '#06b6d4', '#a855f7'
]

const dashPatterns = [
  [], [6, 3], [2, 3], [10, 3, 2, 3],
  [12, 4], [3, 3], [8, 3, 2, 3], [14, 4],
  [5, 2], [2, 2, 8, 2], [9, 2], [4, 2, 1, 2]
]

const displayName = (point: UserUsageTrendPoint): string =>
  point.username?.trim() || point.email?.trim() || `User #${point.user_id}`

const groupedUsers = computed(() => {
  const groups = new Map<number, {
    id: number
    baseLabel: string
    total: number
    values: Map<string, number>
  }>()

  for (const point of props.trendData) {
    const group = groups.get(point.user_id) ?? {
      id: point.user_id,
      baseLabel: displayName(point),
      total: 0,
      values: new Map<string, number>()
    }
    group.values.set(point.date, (group.values.get(point.date) ?? 0) + point.actual_cost)
    group.total += point.actual_cost
    groups.set(point.user_id, group)
  }

  const nameCounts = new Map<string, number>()
  for (const group of groups.values()) {
    nameCounts.set(group.baseLabel, (nameCounts.get(group.baseLabel) ?? 0) + 1)
  }

  return [...groups.values()]
    .sort((a, b) => b.total - a.total || a.id - b.id)
    .map((group) => ({
      ...group,
      label: (nameCounts.get(group.baseLabel) ?? 0) > 1
        ? `${group.baseLabel} · #${group.id}`
        : group.baseLabel
    }))
})

const labels = computed(() => [...new Set(props.trendData.map((point) => point.date))].sort())

const chartData = computed(() => ({
  labels: labels.value,
  datasets: groupedUsers.value.map((group, index) => ({
    label: group.label,
    data: labels.value.map((date) => group.values.get(date) ?? 0),
    borderColor: palette[index % palette.length],
    backgroundColor: palette[index % palette.length],
    borderDash: dashPatterns[index % dashPatterns.length],
    borderWidth: 2,
    fill: false,
    pointRadius: 0,
    pointHoverRadius: 4,
    spanGaps: true,
    tension: 0.3
  }))
}))

const isDarkMode = computed(() => document.documentElement.classList.contains('dark'))

const lineOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: false as const,
  interaction: {
    intersect: false,
    mode: 'index' as const
  },
  plugins: {
    legend: {
      position: 'top' as const,
      labels: {
        color: isDarkMode.value ? '#e5e7eb' : '#374151',
        usePointStyle: true,
        pointStyle: 'line' as const,
        boxWidth: 24,
        padding: 12,
        font: { size: 11 }
      }
    },
    tooltip: {
      itemSort: (a: { raw: unknown }, b: { raw: unknown }) => Number(b.raw) - Number(a.raw),
      callbacks: {
        label: (context: { dataset: { label?: string }, raw: unknown }) =>
          `${context.dataset.label}: ${formatCurrency(Number(context.raw))}`
      }
    }
  },
  scales: {
    x: {
      grid: { color: isDarkMode.value ? 'rgba(148,163,184,0.12)' : 'rgba(100,116,139,0.12)' },
      ticks: {
        color: isDarkMode.value ? '#cbd5e1' : '#475569',
        autoSkip: true,
        maxTicksLimit: 12,
        maxRotation: 0,
        font: { size: 10 }
      }
    },
    y: {
      beginAtZero: true,
      grid: { color: isDarkMode.value ? 'rgba(148,163,184,0.12)' : 'rgba(100,116,139,0.12)' },
      ticks: {
        color: isDarkMode.value ? '#cbd5e1' : '#475569',
        callback: (value: string | number) => formatCurrency(Number(value)),
        font: { size: 10 }
      },
      title: {
        display: true,
        text: '金额 ($)',
        color: isDarkMode.value ? '#cbd5e1' : '#475569'
      }
    }
  }
}))

const labelByUser = computed(() => new Map(groupedUsers.value.map((group) => [group.id, group.label])))

const detailRows = computed(() => [...props.trendData]
  .sort((a, b) => a.date.localeCompare(b.date) || b.actual_cost - a.actual_cost || a.user_id - b.user_id)
  .map((point) => ({
    date: point.date,
    userId: point.user_id,
    label: labelByUser.value.get(point.user_id) ?? displayName(point),
    requests: point.requests,
    actualCost: point.actual_cost
  })))

const formatNumber = (value: number): string => value.toLocaleString('zh-CN')

const formatCurrency = (value: number): string => {
  const safeValue = Number.isFinite(value) ? value : 0
  if (safeValue >= 1_000_000) return `$${(safeValue / 1_000_000).toFixed(2)}M`
  if (safeValue >= 1_000) return `$${(safeValue / 1_000).toFixed(2)}K`
  if (safeValue >= 1) {
    return `$${safeValue.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
  }
  if (safeValue >= 0.01) return `$${safeValue.toFixed(3)}`
  return `$${safeValue.toFixed(4)}`
}
</script>

<style scoped>
.glass-retry-button {
  min-height: 44px;
  padding: 0 16px;
  border: 1px solid var(--glass-card-border);
  border-radius: 6px;
  color: var(--glass-text);
  background: var(--glass-card-bg);
  cursor: pointer;
  transition: background-color 180ms ease, border-color 180ms ease;
}

.glass-retry-button:hover,
.glass-retry-button:focus-visible {
  border-color: var(--glass-muted);
  background: color-mix(in srgb, var(--glass-card-bg), var(--glass-text) 8%);
  outline: none;
}

.glass-chart-details > summary {
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  color: var(--glass-muted);
  font-size: 12px;
  cursor: pointer;
}
</style>
