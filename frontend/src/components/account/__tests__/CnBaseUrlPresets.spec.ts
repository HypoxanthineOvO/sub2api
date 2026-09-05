import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CnBaseUrlPresets from '../CnBaseUrlPresets.vue'

describe('CnBaseUrlPresets', () => {
  it('highlights only the exact MiMo Token Plan region and emits the complete preset', async () => {
    const wrapper = mount(CnBaseUrlPresets, {
      props: {
        platform: 'mimo',
        mode: 'coding',
        protocol: 'chat_completions',
        currentUrl: 'https://token-plan-sgp.xiaomimimo.com/v1'
      }
    })

    const buttons = wrapper.findAll('[data-testid="cn-base-url-preset"]')
    expect(buttons).toHaveLength(4)
    expect(buttons.filter(button => button.classes().includes('bg-primary-100'))).toHaveLength(1)

    await buttons[3].trigger('click')
    expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({
      mode: 'coding',
      protocol: 'chat_completions',
      label: 'MiMo Token Plan EU (AMS)',
      url: 'https://token-plan-ams.xiaomimimo.com/v1'
    })
  })
})
