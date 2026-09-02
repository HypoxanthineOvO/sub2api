<template>
  <div v-if="visible" class="space-y-1" data-testid="newapi-management-cell">
    <div class="flex flex-wrap items-center gap-1.5 text-[10px] leading-4">
      <span
        v-if="hasBalance"
        class="rounded bg-emerald-50 px-1.5 py-0.5 font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
      >
        {{ t('admin.accounts.newapiManagement.balance') }} {{ formatUSD(balance) }}
      </span>
      <span
        v-else
        :class="snapshot?.status === 'failed' ? 'text-red-600 dark:text-red-400' : 'text-gray-400 dark:text-gray-500'"
      >
        {{ snapshot?.status === 'failed' ? t('admin.accounts.newapiManagement.failed') : t('admin.accounts.newapiManagement.pending') }}
      </span>
      <span v-if="hasBalance && used != null" class="text-gray-500 dark:text-gray-400">
        {{ t('admin.accounts.newapiManagement.used') }} {{ formatUSD(used) }}
      </span>
    </div>
    <div class="flex items-center gap-1.5">
      <button
        type="button"
        class="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium text-blue-600 transition-colors hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50 dark:text-blue-400 dark:hover:bg-blue-900/30"
        :disabled="loading"
        :title="detailsTooltip"
        data-testid="newapi-management-probe"
        @click="probe"
      >
        <Icon name="refresh" size="xs" :class="{ 'animate-spin': loading }" />
        {{ t('admin.accounts.newapiManagement.refresh') }}
      </button>
      <span v-if="snapshot?.fetched_at" class="text-[9px] text-gray-400" :title="snapshot.fetched_at">
        {{ formatRelativeTime(snapshot.fetched_at) }}
      </span>
    </div>
    <div v-if="displayError" class="max-w-[220px] truncate text-[10px] text-red-600 dark:text-red-400" :title="displayError">
      {{ displayError }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { adminAPI } from '@/api/admin'
import Icon from '@/components/icons/Icon.vue'
import { formatCompactNumber, formatRelativeTime } from '@/utils/format'
import type { Account, NewAPIManagementSnapshot } from '@/types'

const props = defineProps<{ account: Account }>()
const emit = defineEmits<{ updated: [account: Account] }>()
const { t } = useI18n()
const loading = ref(false)
const error = ref('')
const localSnapshot = ref<NewAPIManagementSnapshot | null>(null)

const configured = computed(() =>
  props.account.credentials?.newapi_management_enabled === true &&
  props.account.credentials_status?.has_newapi_management_token === true
)
const snapshot = computed(() => localSnapshot.value || (
  props.account.extra?.newapi_management_snapshot as NewAPIManagementSnapshot | undefined
))
const visible = computed(() => configured.value)
const quotaPerUnit = computed(() => snapshot.value?.quota_per_unit || 500_000)
const balance = computed(() => {
  const value = snapshot.value?.balance_usd ?? snapshot.value?.balance
  if (typeof value === 'number') return value
  return typeof snapshot.value?.quota === 'number' ? snapshot.value.quota / quotaPerUnit.value : null
})
const used = computed(() => {
  const value = snapshot.value?.used_usd ?? snapshot.value?.used
  if (typeof value === 'number') return value
  return typeof snapshot.value?.used_quota === 'number' ? snapshot.value.used_quota / quotaPerUnit.value : null
})
const hasBalance = computed(() =>
  balance.value != null && (snapshot.value?.status !== 'failed' || !!snapshot.value?.fetched_at)
)
const displayError = computed(() => error.value || (
  snapshot.value?.status === 'failed'
    ? snapshot.value.error || t('admin.accounts.newapiManagement.probeFailed')
    : ''
))
const totalTokens = computed(() => snapshot.value?.total_tokens ?? (
  (snapshot.value?.prompt_tokens || 0) +
  (snapshot.value?.completion_tokens || 0) +
  (snapshot.value?.cache_tokens || 0) +
  (snapshot.value?.cache_creation_tokens || 0)
))
const detailsTooltip = computed(() => [
  snapshot.value?.request_count != null
    ? t('admin.accounts.newapiManagement.requestCount', { count: formatCompactNumber(snapshot.value.request_count) })
    : '',
  totalTokens.value > 0
    ? t('admin.accounts.newapiManagement.tokenCount', { count: formatCompactNumber(totalTokens.value) })
    : ''
].filter(Boolean).join(' · ') || t('admin.accounts.newapiManagement.refreshHint'))

const formatUSD = (value: number | null) => value == null ? '--' : `$${value.toFixed(2)}`

const probe = async () => {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const next = await adminAPI.accounts.probeNewAPIManagement(props.account.id)
    if (next.status === 'failed') {
      error.value = next.error || t('admin.accounts.newapiManagement.probeFailed')
      if (!hasBalance.value) localSnapshot.value = next
      return
    }
    localSnapshot.value = next
    emit('updated', {
      ...props.account,
      extra: { ...(props.account.extra || {}), newapi_management_snapshot: next }
    })
  } catch (cause) {
    const e = cause as { message?: string; response?: { data?: { message?: string } } }
    error.value = e.response?.data?.message || e.message || t('admin.accounts.newapiManagement.probeFailed')
  } finally {
    loading.value = false
  }
}

watch(() => props.account.id, () => {
  localSnapshot.value = null
  error.value = ''
})
</script>
