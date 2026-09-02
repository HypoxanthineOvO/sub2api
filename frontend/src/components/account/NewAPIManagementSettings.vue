<template>
  <div class="border-t border-gray-200 pt-4 dark:border-dark-600" data-testid="newapi-management-settings">
    <div class="flex items-center justify-between gap-4">
      <div>
        <label class="input-label mb-0">{{ t('admin.accounts.newapiManagement.title') }}</label>
        <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
          {{ t('admin.accounts.newapiManagement.hint') }}
        </p>
      </div>
      <Toggle
        :model-value="enabled"
        :aria-label="t('admin.accounts.newapiManagement.title')"
        data-testid="newapi-management-toggle"
        @update:model-value="setEnabled"
      />
    </div>

    <div v-if="enabled" class="mt-4 space-y-4">
      <div>
        <label class="input-label">{{ t('admin.accounts.newapiManagement.baseUrl') }}</label>
        <input
          :value="managementBaseUrl"
          type="url"
          required
          class="input font-mono"
          placeholder="https://example.com"
          data-testid="newapi-management-base-url"
          @input="updateBaseUrl(($event.target as HTMLInputElement).value)"
        />
        <p class="input-hint">{{ t('admin.accounts.newapiManagement.baseUrlHint') }}</p>
      </div>
      <div>
        <label class="input-label">{{ t('admin.accounts.newapiManagement.token') }}</label>
        <input
          :value="token"
          type="password"
          :required="!tokenConfigured"
          class="input font-mono"
          autocomplete="new-password"
          data-1p-ignore
          data-lpignore="true"
          data-bwignore="true"
          :placeholder="tokenConfigured ? t('admin.accounts.newapiManagement.keepToken') : t('admin.accounts.newapiManagement.tokenPlaceholder')"
          data-testid="newapi-management-token"
          @input="$emit('update:token', ($event.target as HTMLInputElement).value)"
        />
        <p class="input-hint">
          {{ tokenConfigured ? t('admin.accounts.newapiManagement.keepToken') : t('admin.accounts.newapiManagement.tokenHint') }}
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Toggle from '@/components/common/Toggle.vue'
import { suggestNewAPIManagementBaseUrl } from '@/utils/newapiManagement'

const props = withDefaults(defineProps<{
  enabled: boolean
  managementBaseUrl: string
  token: string
  sourceBaseUrl: string
  tokenConfigured?: boolean
}>(), {
  tokenConfigured: false
})

const emit = defineEmits<{
  'update:enabled': [value: boolean]
  'update:managementBaseUrl': [value: string]
  'update:token': [value: string]
}>()

const { t } = useI18n()
let lastSuggestedBaseUrl = ''

const fillSuggestedBaseUrl = () => {
  const suggestion = suggestNewAPIManagementBaseUrl(props.sourceBaseUrl)
  if (!suggestion) return
  if (!props.managementBaseUrl || props.managementBaseUrl === lastSuggestedBaseUrl) {
    emit('update:managementBaseUrl', suggestion)
  }
  lastSuggestedBaseUrl = suggestion
}

const setEnabled = (value: boolean) => {
  emit('update:enabled', value)
  if (value) fillSuggestedBaseUrl()
}

const updateBaseUrl = (value: string) => {
  emit('update:managementBaseUrl', value)
}

watch(() => props.sourceBaseUrl, () => {
  if (props.enabled) fillSuggestedBaseUrl()
})
</script>
