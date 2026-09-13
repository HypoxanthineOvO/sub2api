<template>
  <BaseDialog :show="show" :title="labels.title" :width="advanced ? 'wide' : 'normal'" @close="emit('close')">
    <div class="space-y-5" data-testid="vsp-key-access">
      <template v-if="!advanced">
        <div class="rounded-xl border border-gray-200 p-4 dark:border-dark-600">
          <p class="mb-2 text-sm font-medium text-gray-600 dark:text-dark-300">BaseURL</p>
          <p class="break-all font-mono text-sm text-gray-900 dark:text-dark-100">{{ base || labels.invalid }}</p>
          <button class="btn btn-secondary mt-3 min-h-11 w-full" :disabled="!base" @click="copy(base)">{{ labels.base }}</button>
        </div>
        <div class="rounded-xl border border-gray-200 p-4 dark:border-dark-600">
          <p class="mb-2 text-sm font-medium text-gray-600 dark:text-dark-300">APIKey</p>
          <p class="break-all font-mono text-sm text-gray-900 dark:text-dark-100">{{ apiKey || labels.emptyKey }}</p>
          <button class="btn btn-secondary mt-3 min-h-11 w-full" :disabled="!apiKey.trim()" @click="copy(apiKey)">{{ labels.key }}</button>
        </div>
        <button class="btn btn-primary min-h-11 w-full" :disabled="!base || !apiKey.trim()" @click="copy(combined)">{{ labels.both }}</button>
        <button ref="advancedTrigger" class="btn btn-secondary min-h-11 w-full" @click="openAdvanced">{{ labels.clients }}</button>
      </template>
      <template v-else>
        <button ref="backButton" class="btn btn-secondary min-h-11" @click="goBack">{{ labels.back }}</button>
        <p class="text-sm text-gray-600 dark:text-dark-300">{{ labels.intro }}</p>
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-3" role="group" :aria-label="labels.clients">
          <button v-for="client in clients" :key="client.id" class="btn min-h-11 flex-col" :class="selected === client.id ? 'btn-primary' : 'btn-secondary'"
            :aria-pressed="selected === client.id" @click="selected = client.id">{{ client.name }}<span v-if="isDiscouraged(client.id)" class="whitespace-nowrap text-xs">（{{ labels.discouraged }}）</span></button>
        </div>
        <p v-if="isDiscouraged(selected)" role="note" class="rounded-lg border border-amber-400 p-3 text-sm text-amber-800 dark:text-amber-300">{{ labels.discouragedHint }}</p>
        <section class="space-y-2 rounded-lg border border-gray-200 p-3 dark:border-dark-600" data-testid="default-locations">
          <h4 class="text-sm font-medium">{{ labels.defaultLocation }}</h4>
          <div v-for="location in defaultLocations(selected)" :key="location.label" class="flex flex-wrap items-center gap-2 text-sm">
            <span>{{ location.label }}</span><code class="min-w-0 break-all">{{ location.content }}</code>
            <button class="btn btn-secondary min-h-11" @click="copy(location.content)">{{ labels.copyPath }}</button>
          </div>
          <p class="text-sm text-gray-600 dark:text-dark-300">{{ labels.locationHint }}</p>
        </section>
        <p v-if="selected === 'zcode'" class="text-sm text-gray-600 dark:text-dark-300">{{ labels.zcodeHint }}</p>
        <a v-if="current.docs" :href="current.docs" target="_blank" rel="noopener noreferrer" class="inline-block py-2 text-primary-600 underline dark:text-primary-400">{{ labels.docs }}</a>
        <p class="text-sm text-gray-600 dark:text-dark-300">{{ labels.modelHint }}</p>
        <p v-if="!base" role="alert">{{ labels.invalid }}</p>
        <p v-else-if="needsCatalog && !catalog" role="status">{{ labels.missing }}</p>
        <p v-else-if="configs.error" role="alert">{{ labels.unsupported }}</p>
        <section v-for="block in configs.blocks" :key="block.label" class="min-w-0 space-y-2">
          <h4 class="break-all text-sm font-medium">{{ block.label }}</h4>
          <pre class="max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-gray-100 p-3 text-xs dark:bg-dark-800"><code>{{ block.content }}</code></pre>
          <button class="btn btn-secondary min-h-11" :disabled="!apiKey.trim() || !block.content" @click="copy(block.content)">{{ labels.copy }}</button>
        </section>
        <section class="space-y-3 border-t border-gray-200 pt-4 dark:border-dark-600">
          <h4 class="font-medium">{{ labels.metadata }}<span v-if="catalog"> · {{ catalog.models.length }}</span></h4>
          <p class="text-sm text-gray-600 dark:text-dark-300">{{ labels.metadataHint }}</p>
          <p class="text-sm text-gray-600 dark:text-dark-300">{{ labels.protocol }}</p>
          <p v-if="loading" role="status">{{ labels.loading }}</p>
          <p v-if="failed" role="alert" class="text-sm text-red-600 dark:text-red-400">{{ labels.failed }}</p>
          <div class="flex flex-wrap gap-2">
            <button class="btn btn-secondary min-h-11" :disabled="loading || !base" @click="loadCatalog">{{ labels.retry }}</button>
            <button v-if="catalog" class="btn btn-secondary min-h-11" @click="copy(JSON.stringify(catalog, null, 2))">{{ labels.copyCatalog }}</button>
            <a v-if="base" :href="catalogHref" target="_blank" rel="noopener noreferrer" class="btn btn-secondary min-h-11">{{ labels.openCatalog }}</a>
          </div>
        </section>
      </template>
    </div>
  </BaseDialog>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { useClipboard } from '@/composables/useClipboard'
import { useAppStore } from '@/stores/app'
import { catalogUrl, combinedCredentials, rootBaseUrl } from './credentials'
import { fetchCatalog, type ModelCatalog } from './catalog'
import { clients, clientConfig, defaultLocations, isDiscouraged, type ClientId } from './clientConfigs'
import { messages } from './messages'

const props = defineProps<{ show: boolean; apiKey: string; baseUrl: string; platform: string | null; allowMessagesDispatch?: boolean }>()
const emit = defineEmits<{ (event: 'close'): void }>()
const { locale, t } = useI18n()
const labels = computed(() => locale.value.startsWith('zh') ? messages.zh : messages.en)
const { copyToClipboard } = useClipboard()
const app = useAppStore()
const advanced = ref(false)
const advancedTrigger = ref<HTMLButtonElement>()
const backButton = ref<HTMLButtonElement>()
const selected = ref<ClientId>('codex')
const catalog = ref<ModelCatalog>()
const loading = ref(false)
const failed = ref(false)
let controller: AbortController | undefined
let generation = 0
const base = computed(() => {
  try { return rootBaseUrl(props.baseUrl || window.location.origin) } catch { return '' }
})
const combined = computed(() => base.value ? combinedCredentials(base.value, props.apiKey) : '')
const catalogHref = computed(() => base.value ? catalogUrl(base.value) : '')
const current = computed(() => clients.find(client => client.id === selected.value)!)
const needsCatalog = computed(() => ['pi', 'kimi', 'opencode'].includes(selected.value))
const configs = computed(() => {
  if (!advanced.value || !base.value || (needsCatalog.value && !catalog.value)) return { blocks: [], error: false }
  try { return { blocks: clientConfig(selected.value, base.value, props.apiKey, catalog.value), error: false } }
  catch { return { blocks: [], error: true } }
})
async function copy(content: string) {
  try { await copyToClipboard(content) } catch { app.showError(t('common.copyFailed')) }
}
function cancel() { generation++; controller?.abort(); controller = undefined }
function reset() {
  cancel(); advanced.value = false; selected.value = 'codex'; catalog.value = undefined; loading.value = false; failed.value = false
}
watch(() => [props.show, props.baseUrl, props.apiKey], reset)
onBeforeUnmount(cancel)
async function loadCatalog() {
  if (!props.show || !base.value) return
  cancel()
  const request = generation
  const activeController = new AbortController()
  controller = activeController
  const signal = activeController.signal
  const timer = setTimeout(() => activeController.abort(), 8000)
  loading.value = true; failed.value = false
  try {
    const result = await fetchCatalog(base.value, signal)
    if (request === generation) catalog.value = result
  } catch {
    if (request === generation) failed.value = true
  } finally {
    clearTimeout(timer)
    if (request === generation) loading.value = false
  }
}
async function openAdvanced() {
  advanced.value = true
  if (!catalog.value) void loadCatalog()
  await nextTick()
  backButton.value?.focus()
}
async function goBack() {
  advanced.value = false
  await nextTick()
  advancedTrigger.value?.focus()
}
</script>
