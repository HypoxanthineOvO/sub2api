import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { ref } from 'vue'
import KeyAccessModal from '../KeyAccessModal.vue'
import { clientConfig, clients } from '../clientConfigs'
import { catalogUrl, combinedCredentials, rootBaseUrl, tomlString, shellString, powershellString } from '../credentials'
import { parseCatalog } from '../catalog'

const { copy, fetchCatalog, showError } = vi.hoisted(() => ({ copy: vi.fn(), fetchCatalog: vi.fn(), showError: vi.fn() }))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copyToClipboard: copy }) }))
vi.mock('@/stores/app', () => ({ useAppStore: () => ({ showError }) }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ locale: ref('zh'), t: (key: string) => key }) }))
vi.mock('../catalog', async importOriginal => ({ ...await importOriginal<object>(), fetchCatalog }))

const catalog = { version: 1, models: [
  { id: 'offline-example', protocol: 'openai', contextWindow: 65536, extraField: { retained: true } },
  { id: 'hidden-example', protocol: 'anthropic', hidden: true },
  { id: 'response-example', protocol: 'openai_responses' },
  { id: 'unknown-default' }
] }
const props = { show: true, apiKey: 'sk-test-only', baseUrl: 'https://api.example.test/v1/', platform: 'anthropic' }
function render() { return mount(KeyAccessModal, { props, global: { stubs: { BaseDialog: { template: '<div><slot /></div>' } } } }) }
function button(wrapper: ReturnType<typeof render>, name: string) { return wrapper.findAll('button').find(node => node.text() === name)! }

beforeEach(() => { vi.clearAllMocks(); copy.mockResolvedValue(true); fetchCatalog.mockResolvedValue(catalog) })
afterEach(() => { vi.useRealTimers() })

describe('VSP key access', () => {
  it('defaults to three copy actions, displays the full key and makes no network request', async () => {
    const wrapper = render()
    expect(wrapper.text()).toContain(props.apiKey)
    expect(wrapper.text()).not.toContain('••••')
    expect(wrapper.findAll('button')).toHaveLength(4)
    expect(fetchCatalog).not.toHaveBeenCalled()
    await button(wrapper, '复制 BaseURL').trigger('click')
    await button(wrapper, '复制 APIKey').trigger('click')
    await button(wrapper, '复制 BaseURL + APIKey').trigger('click')
    expect(copy.mock.calls.map(args => args[0])).toEqual([
      'https://api.example.test', props.apiKey, 'BaseURL: https://api.example.test, APIKey: sk-test-only'
    ])
    const longKey = `sk-example-${'0123456789abcdef'.repeat(4)}`
    await wrapper.setProps({ apiKey: longKey })
    const keyText = wrapper.findAll('p').find(node => node.text() === longKey)!
    expect(keyText.classes()).toContain('break-all')
    await button(wrapper, '复制 APIKey').trigger('click')
    expect(copy).toHaveBeenLastCalledWith(longKey)
    wrapper.unmount()
  })
  it('shows exactly six clients and preserves the complete metadata', async () => {
    const wrapper = render()
    await button(wrapper, '客户端配置').trigger('click'); await flushPromises()
    expect(wrapper.findAll('button[aria-pressed]').map(node => node.text())).toEqual(clients.map(client => client.name))
    expect(wrapper.text()).not.toContain('Claude Code')
    expect(wrapper.text()).not.toContain('OpenCode')
    await button(wrapper, '复制完整目录 JSON').trigger('click')
    expect(JSON.parse(copy.mock.calls.at(-1)![0])).toEqual(catalog)
    await button(wrapper, 'Pi').trigger('click')
    expect(wrapper.text()).toContain('offline-example')
    expect(wrapper.text()).toContain('hidden-example')
    wrapper.unmount()
  })
  it('aborts on closing and never accepts a late response after switching base URL', async () => {
    let resolve!: (value: unknown) => void
    fetchCatalog.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const wrapper = render(); await button(wrapper, '客户端配置').trigger('click')
    const signal = fetchCatalog.mock.calls[0][1] as AbortSignal
    await wrapper.setProps({ baseUrl: 'https://other.example.test' })
    expect(signal.aborted).toBe(true)
    resolve(catalog); await flushPromises()
    expect(wrapper.text()).not.toContain('offline-example')
    await button(wrapper, '客户端配置').trigger('click'); await flushPromises()
    await wrapper.setProps({ show: false })
    expect((fetchCatalog.mock.calls[1][1] as AbortSignal).aborted).toBe(true)
    wrapper.unmount()
  })
  it('retains the last valid catalog on reload failure and exposes retry', async () => {
    const wrapper = render(); await button(wrapper, '客户端配置').trigger('click'); await flushPromises()
    fetchCatalog.mockRejectedValueOnce(new Error('private diagnostic must not be displayed'))
    await button(wrapper, '重新读取目录').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('模型目录读取失败')
    expect(wrapper.text()).not.toContain('private diagnostic')
    await button(wrapper, '复制完整目录 JSON').trigger('click')
    expect(JSON.parse(copy.mock.calls.at(-1)![0])).toEqual(catalog)
    wrapper.unmount()
  })
  it('reports clipboard exceptions and disables empty keys or unsafe endpoints', async () => {
    const wrapper = render(); copy.mockRejectedValueOnce(new Error('clipboard unavailable'))
    await button(wrapper, '复制 APIKey').trigger('click'); await flushPromises()
    expect(showError).toHaveBeenCalledWith('common.copyFailed')
    await wrapper.setProps({ apiKey: '', baseUrl: 'javascript:alert(1)' })
    expect(button(wrapper, '复制 APIKey').attributes('disabled')).toBeDefined()
    expect(button(wrapper, '复制 BaseURL').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})

describe('configuration contract', () => {
  it('normalizes URLs once and correctly quotes credential strings', () => {
    expect(rootBaseUrl('https://example.test/v1///')).toBe('https://example.test')
    expect(catalogUrl('https://example.test/v1')).toBe('https://example.test/vsp/models')
    expect(() => rootBaseUrl('https://secret@example.test')).toThrow()
    expect(() => rootBaseUrl('https://example.test/?secret=x')).toThrow()
    expect(combinedCredentials('https://example.test', '')).toBe('')
    expect(JSON.parse(tomlString('a"\n\\b'))).toBe('a"\n\\b')
    expect(shellString("a'b")).toBe("'a'\"'\"'b'")
    expect(powershellString("a'b")).toBe("'a''b'")
  })
  it('does not introduce model selection or availability checks in provider snippets', () => {
    for (const id of ['codex', 'vsp-codex', 'vspi'] as const) {
      const blocks = clientConfig(id, props.baseUrl, props.apiKey)
      expect(blocks[0].content).not.toMatch(/^model =/m)
      expect(blocks[0].content).not.toContain('/v1/v1')
    }
    expect(clientConfig('codex', props.baseUrl, props.apiKey)[0].label).toBe('~/.codex/config.toml')
    expect(clientConfig('vsp-codex', props.baseUrl, props.apiKey)[0].label).toBe('~/.vsp-codex/config.toml')
    expect(clientConfig('vspi', props.baseUrl, props.apiKey)[0].content).toContain('/vsp/models')
  })
  it('projects every model to Pi and Kimi without filtering hidden/offline entries', () => {
    const pi = JSON.parse(clientConfig('pi', props.baseUrl, '!danger$KEY', catalog)[0].content)
    const providers = Object.values(pi.providers) as { models: { id: string }[]; apiKey: string; baseUrl: string }[]
    expect(providers.flatMap(provider => provider.models.map(model => model.id)).sort()).toEqual(catalog.models.map(model => model.id).sort())
    expect(providers.every(provider => provider.apiKey === '$VSP_API_KEY')).toBe(true)
    expect(pi.providers.vsplab_anthropic.baseUrl).toBe('https://api.example.test')
    const kimi = clientConfig('kimi', props.baseUrl, props.apiKey, catalog)[0].content
    for (const model of catalog.models) expect(kimi).toContain(`model = "${model.id}"`)
    expect(kimi).not.toContain('default_model')
    expect(() => clientConfig('pi', props.baseUrl, props.apiKey, { models: [{ id: 'x', protocol: 'constructor' }] })).toThrow()
  })
  it('rejects malformed catalogs without discarding valid-looking subsets', () => {
    expect(parseCatalog(catalog)).toEqual(catalog)
    for (const payload of [{ version: 2, models: [] }, { models: [{ id: 'a' }, { id: 'a' }] }, { models: [{ id: 'a', contextWindow: -1 }] }, { models: [{ id: 'a', input: 'image' }] }]) {
      expect(() => parseCatalog(payload)).toThrow()
    }
  })
  it('keeps the upstream attachment points explicit', () => {
    const view = readFileSync(resolve('src/views/user/KeysView.vue'), 'utf8')
    const layout = readFileSync(resolve('src/components/layout/AppLayout.vue'), 'utf8')
    expect(view).toContain("import UseKeyModal from '@/features/vsp-key-access/KeyAccessModal.vue'")
    expect(layout).toContain('autoStart: false')
  })
})
