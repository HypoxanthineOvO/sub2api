import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import NewAPIManagementSettings from '../NewAPIManagementSettings.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

describe('NewAPIManagementSettings', () => {
  it('suggests the management origin when enabled', async () => {
    const wrapper = mount(NewAPIManagementSettings, {
      props: {
        enabled: false,
        managementBaseUrl: '',
        token: '',
        sourceBaseUrl: 'https://aimoniker.top/v1'
      }
    })

    await wrapper.get('[data-testid="newapi-management-toggle"]').trigger('click')

    expect(wrapper.emitted('update:enabled')?.[0]).toEqual([true])
    expect(wrapper.emitted('update:managementBaseUrl')?.[0]).toEqual(['https://aimoniker.top'])
  })

  it('allows an existing token to remain blank while editing', () => {
    const wrapper = mount(NewAPIManagementSettings, {
      props: {
        enabled: true,
        managementBaseUrl: 'https://aimoniker.top',
        token: '',
        sourceBaseUrl: 'https://aimoniker.top/v1',
        tokenConfigured: true
      }
    })

    expect(wrapper.get('[data-testid="newapi-management-token"]').attributes('required')).toBeUndefined()
    expect(wrapper.get('[data-testid="newapi-management-token"]').attributes('placeholder'))
      .toBe('admin.accounts.newapiManagement.keepToken')
  })
})
