import { describe, expect, it } from 'vitest'

import {
  CN_BASE_URL_PRESETS,
  cnProviderSupportsResponses,
  cnProtocolSiblingBaseUrl,
  defaultCNAdaptiveBaseUrls,
  mimoTokenPlanBaseUrls,
  mimoTokenPlanRegionFromURL
} from '../credentialsBuilder'

describe('defaultCNAdaptiveBaseUrls', () => {
  it('resolves Kimi endpoints by account mode', () => {
    expect(defaultCNAdaptiveBaseUrls('kimi', 'payg')).toEqual({
      chat_completions: 'https://api.moonshot.cn/v1',
      anthropic: 'https://api.moonshot.cn/anthropic',
      responses: ''
    })
    expect(defaultCNAdaptiveBaseUrls('kimi', 'coding')).toEqual({
      chat_completions: 'https://api.kimi.com/coding/v1',
      anthropic: 'https://api.kimi.com/coding',
      responses: ''
    })
  })

  it('resolves GLM endpoints by account mode', () => {
    expect(defaultCNAdaptiveBaseUrls('zhipu', 'payg')).toEqual({
      chat_completions: 'https://open.bigmodel.cn/api/paas/v4',
      anthropic: 'https://open.bigmodel.cn/api/anthropic',
      responses: ''
    })
    expect(defaultCNAdaptiveBaseUrls('zhipu', 'coding')).toEqual({
      chat_completions: 'https://open.bigmodel.cn/api/coding/paas/v4',
      anthropic: 'https://open.bigmodel.cn/api/anthropic',
      responses: ''
    })
  })

  it('includes all three native DeepSeek endpoints', () => {
    expect(defaultCNAdaptiveBaseUrls('deepseek', 'payg')).toEqual({
      chat_completions: 'https://api.deepseek.com',
      anthropic: 'https://api.deepseek.com/anthropic',
      responses: 'https://api.deepseek.com'
    })
  })

  it('includes all three native MiniMax endpoints for PAYG and Token Plan', () => {
    for (const mode of ['payg', 'coding'] as const) {
      expect(defaultCNAdaptiveBaseUrls('minimax', mode)).toEqual({
        chat_completions: 'https://api.minimaxi.com/v1',
        anthropic: 'https://api.minimaxi.com/anthropic',
        responses: 'https://api.minimaxi.com/v1'
      })
    }
  })

  it('uses all three native endpoints for MiMo PAYG and Token Plan', () => {
    expect(defaultCNAdaptiveBaseUrls('mimo', 'payg')).toEqual({
      chat_completions: 'https://api.xiaomimimo.com/v1',
      anthropic: 'https://api.xiaomimimo.com/anthropic',
      responses: 'https://api.xiaomimimo.com/v1'
    })
    expect(defaultCNAdaptiveBaseUrls('mimo', 'coding')).toEqual({
      chat_completions: 'https://token-plan-cn.xiaomimimo.com/v1',
      anthropic: 'https://token-plan-cn.xiaomimimo.com/anthropic',
      responses: 'https://token-plan-cn.xiaomimimo.com/v1'
    })
  })

  it('keeps Hunyuan and Qwen on their verified Chat Completions endpoints', () => {
    expect(defaultCNAdaptiveBaseUrls('hunyuan', 'payg')).toEqual({
      chat_completions: 'https://tokenhub.tencentmaas.com/v1',
      anthropic: '',
      responses: ''
    })
    expect(defaultCNAdaptiveBaseUrls('qwen', 'payg')).toEqual({
      chat_completions: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      anthropic: '',
      responses: ''
    })
    expect(cnProviderSupportsResponses('hunyuan')).toBe(false)
    expect(cnProviderSupportsResponses('qwen')).toBe(false)
    expect(CN_BASE_URL_PRESETS.hunyuan).toHaveLength(2)
    expect(CN_BASE_URL_PRESETS.qwen).toHaveLength(1)
  })

  it('preserves the MiMo Token Plan region when switching native protocols', () => {
    expect(cnProtocolSiblingBaseUrl(
      'https://token-plan-sgp.xiaomimimo.com/v1',
      'mimo',
      'coding',
      'anthropic'
    )).toBe('https://token-plan-sgp.xiaomimimo.com/anthropic')
    expect(cnProtocolSiblingBaseUrl(
      'https://token-plan-ams.xiaomimimo.com/anthropic',
      'mimo',
      'coding',
      'chat_completions'
    )).toBe('https://token-plan-ams.xiaomimimo.com/v1')
    expect(cnProtocolSiblingBaseUrl(
      'https://token-plan-sgp.xiaomimimo.com/anthropic',
      'mimo',
      'coding',
      'responses'
    )).toBe('https://token-plan-sgp.xiaomimimo.com/v1')
  })

  it('resolves and detects each MiMo Token Plan region as one endpoint group', () => {
    expect(mimoTokenPlanBaseUrls('eu')).toEqual({
      chat_completions: 'https://token-plan-ams.xiaomimimo.com/v1',
      anthropic: 'https://token-plan-ams.xiaomimimo.com/anthropic',
      responses: 'https://token-plan-ams.xiaomimimo.com/v1'
    })
    expect(mimoTokenPlanRegionFromURL('https://token-plan-sgp.xiaomimimo.com/v1')).toBe('sgp')
    expect(mimoTokenPlanRegionFromURL('https://relay.example.com/v1')).toBe('cn')
  })
})
