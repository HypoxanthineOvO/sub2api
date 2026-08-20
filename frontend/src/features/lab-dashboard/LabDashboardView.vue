<template>
  <AppLayout>
    <div class="lab-dashboard">
      <header class="lab-dashboard__header">
        <div>
          <h1>实验室仪表盘</h1>
          <p>只读运行概览 · {{ data?.timezone || '—' }}</p>
        </div>
        <button type="button" class="lab-dashboard__refresh" :disabled="loading" @click="load">刷新</button>
      </header>

      <div v-if="loading" class="lab-dashboard__state">加载中…</div>
      <div v-else-if="error" class="lab-dashboard__state" role="alert">加载失败，请重试。</div>
      <template v-else-if="data">
        <section class="lab-dashboard__summary" data-test="lab-summary">
          <div><strong>${{ money(data.summary.today_actual_cost) }}</strong><span>今日消耗</span></div>
          <div><strong>{{ number(data.summary.today_requests) }}</strong><span>今日请求</span></div>
          <div><strong>{{ number(data.summary.active_users) }}</strong><span>活跃用户</span></div>
          <div><strong>{{ data.summary.schedulable_accounts }}/{{ data.summary.total_accounts }}</strong><span>可调度账号</span></div>
          <div><strong>${{ money(data.summary.week_actual_cost) }}</strong><span>本周消耗</span></div>
        </section>

        <section data-test="lab-accounts">
          <h2>账号状态</h2>
          <div class="lab-dashboard__accounts">
            <article v-for="account in data.accounts" :key="account.name" class="lab-dashboard__account">
              <div class="lab-dashboard__account-head"><strong>{{ account.name }}</strong><span :class="{ 'lab-dashboard__account-state--active': account.schedulable }">{{ accountState(account) }}</span></div>
              <p>{{ account.plan_type || account.type }} · {{ account.platform }}</p>
              <dl>
                <div><dt>5h</dt><dd>{{ percent(account.quota_5h_used_percent) }}</dd></div>
                <div><dt>7d</dt><dd>{{ percent(account.quota_7d_used_percent) }}</dd></div>
                <div><dt>额度因子</dt><dd>{{ factor(account.quota_factor) }}</dd></div>
                <div><dt>基础概率</dt><dd>{{ probability(account) }}</dd></div>
              </dl>
              <small v-if="account.selected_node_name">{{ account.slot_label || 'Slot' }} · {{ account.selected_node_name }} · {{ account.selected_node_status }}</small>
            </article>
          </div>
        </section>

        <section class="lab-dashboard__grid">
          <div><h2>历史金额榜</h2><table><thead><tr><th>用户</th><th>今日</th><th>累计</th></tr></thead><tbody><tr v-for="row in data.leaderboard.rows" :key="row.display_name"><td>{{ row.display_name }}</td><td>{{ row.today_actual_cost == null ? '—' : `$${money(row.today_actual_cost)}` }}</td><td>${{ money(row.total_actual_cost) }}</td></tr></tbody></table></div>
          <div><h2>最近 24 小时用户消费</h2><table><thead><tr><th>时间</th><th>用户</th><th>金额</th></tr></thead><tbody><tr v-for="row in data.user_usage_24h" :key="`${row.bucket}-${row.display_name}`"><td>{{ row.bucket }}</td><td>{{ row.display_name }}</td><td>${{ money(row.actual_cost) }}</td></tr></tbody></table></div>
        </section>

        <section><h2>最近使用记录</h2><table><thead><tr><th>时间</th><th>用户</th><th>模型</th><th>路由账号</th><th>金额</th></tr></thead><tbody><tr v-for="row in data.recent_usage" :key="`${row.created_at}-${row.user_display_name}-${row.model}`"><td>{{ time(row.created_at) }}</td><td>{{ row.user_display_name }}</td><td>{{ row.model }}</td><td>{{ row.switch_from_account_name ? `${row.switch_from_account_name} → ${row.account_name || '—'}` : row.account_name || '—' }}</td><td>${{ money(row.actual_cost) }}</td></tr></tbody></table></section>
      </template>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppLayout from '@/components/layout/AppLayout.vue'
import { getLabDashboard, type LabDashboardAccount, type LabDashboardResponse } from '@/api/labDashboard'

const data = ref<LabDashboardResponse | null>(null)
const loading = ref(true)
const error = ref(false)
const load = async () => { loading.value = true; error.value = false; try { data.value = await getLabDashboard() } catch { error.value = true } finally { loading.value = false } }
const number = (value: number) => Number(value || 0).toLocaleString()
const money = (value: number) => Number(value || 0).toFixed(4)
const percent = (value?: number) => value == null ? '—' : `${Math.round(value)}%`
const factor = (value: number) => Number(value || 0).toFixed(2)
const probability = (account: LabDashboardAccount) => account.selection_probability_status === 'computed' && account.selection_probability != null ? `${Math.round(account.selection_probability * 100)}%` : '不可用'
const accountState = (account: LabDashboardAccount) => {
  if (account.schedulable) return '调度中'
  if (account.status === 'disabled') return '已禁用'
  if (account.status === 'error') return '异常'
  return '不可调度'
}
const time = (value: string) => new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
onMounted(load)
</script>

<style scoped>
.lab-dashboard { max-width: 1440px; margin: 0 auto; padding: 24px; color: var(--color-text, #1f2937); }
.lab-dashboard__header, .lab-dashboard__account-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.lab-dashboard__header h1 { margin: 0; font-size: 22px; } .lab-dashboard__header p, .lab-dashboard__account p, .lab-dashboard__account small { color: #64748b; font-size: 12px; }
.lab-dashboard__refresh { min-height: 40px; padding: 0 14px; border: 1px solid #cbd5e1; border-radius: 6px; background: transparent; cursor: pointer; }
.lab-dashboard__summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 24px 0; } .lab-dashboard__summary div, .lab-dashboard__account, .lab-dashboard__grid > div, section > table { border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px; background: rgba(255,255,255,.7); }
.lab-dashboard__summary strong, .lab-dashboard__summary span { display: block; } .lab-dashboard__summary span { margin-top: 4px; color: #64748b; font-size: 12px; }
.lab-dashboard h2 { margin: 22px 0 10px; font-size: 15px; } .lab-dashboard__accounts { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.lab-dashboard__account-head span { color: #b45309; font-size: 12px; } .lab-dashboard__account-head .lab-dashboard__account-state--active { color: #047857; } .lab-dashboard__account dl { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 12px 0; } .lab-dashboard__account dt, .lab-dashboard__account dd { display: inline; font-size: 12px; } .lab-dashboard__account dd { float: right; font-weight: 600; }
.lab-dashboard__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; } table { width: 100%; border-collapse: collapse; font-size: 12px; } th, td { padding: 9px 8px; border-bottom: 1px solid #e2e8f0; text-align: left; } th:last-child, td:last-child { text-align: right; }
.lab-dashboard__state { padding: 48px 0; text-align: center; color: #64748b; }
.dark .lab-dashboard { color: #e5e7eb; }
.dark .lab-dashboard__header p, .dark .lab-dashboard__account p, .dark .lab-dashboard__account small, .dark .lab-dashboard__summary span, .dark .lab-dashboard__state { color: #94a3b8; }
.dark .lab-dashboard__refresh { color: #e5e7eb; border-color: #475569; }
.dark .lab-dashboard__summary div, .dark .lab-dashboard__account, .dark .lab-dashboard__grid > div, .dark .lab-dashboard section > table { border-color: #334155; background: rgba(15,23,42,.72); }
.dark .lab-dashboard th, .dark .lab-dashboard td { border-color: #334155; }
@media (max-width: 768px) { .lab-dashboard { padding: 16px; } .lab-dashboard__summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } .lab-dashboard__grid { grid-template-columns: 1fr; } .lab-dashboard__grid > div { max-width: 100%; overflow-x: auto; } .lab-dashboard__grid table { min-width: 360px; } section > table { max-width: 100%; overflow-x: auto; display: block; white-space: nowrap; } }
</style>
