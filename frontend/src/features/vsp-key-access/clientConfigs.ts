import type { ModelCatalog } from './catalog'
import { catalogUrl, protocolBaseUrl, rootBaseUrl, tomlString, shellString, powershellString } from './credentials'

export const clients = [
  { id: 'codex', name: 'Codex', path: '~/.codex/config.toml', docs: 'https://learn.chatgpt.com/docs/config-file/config-reference' },
  { id: 'pi', name: 'Pi', path: '~/.pi/agent/models.json', docs: 'https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md' },
  { id: 'zcode', name: 'ZCode', path: '~/.zcode/v2/config.json', docs: 'https://zcode.z.ai/en/docs/configuration' },
  { id: 'kimi', name: 'Kimi Code', path: '~/.kimi-code/config.toml', docs: 'https://moonshotai.github.io/kimi-code/en/configuration/data-locations.html' },
  { id: 'vsp-codex', name: 'VSP-Codex', path: '~/.vsp-codex/config.toml', docs: '' },
  { id: 'vspi', name: 'VSPi', path: '~/.vspi/config.toml', docs: '' },
  { id: 'claude', name: 'Claude Code', path: '~/.claude/settings.json', docs: 'https://code.claude.com/docs/en/settings' },
  { id: 'opencode', name: 'OpenCode', path: '~/.config/opencode/opencode.json', docs: 'https://opencode.ai/docs/config/' }
] as const
export type ClientId = typeof clients[number]['id']
export interface ConfigBlock { label: string; content: string }
export const isDiscouraged = (id: ClientId): boolean => id === 'claude' || id === 'opencode'
export function defaultLocations(id: ClientId): ConfigBlock[] {
  const path = clients.find(client => client.id === id)!.path
  const locations = [
    { label: 'macOS / Linux', content: path },
    { label: 'Windows', content: path.replace('~/', '%USERPROFILE%/').replace(/\//g, '\\') }
  ]
  if (id === 'opencode') locations.push(
    { label: 'Auth · macOS / Linux', content: '~/.local/share/opencode/auth.json' },
    { label: 'Auth · Windows', content: '%USERPROFILE%\\.local\\share\\opencode\\auth.json' }
  )
  return locations
}

const piProtocols: Record<string, string> = {
  openai: 'openai-completions', openai_responses: 'openai-responses', anthropic: 'anthropic-messages'
}

export function clientConfig(id: ClientId, baseUrl: string, apiKey: string, catalog?: ModelCatalog): ConfigBlock[] {
  const root = rootBaseUrl(baseUrl)
  const base = protocolBaseUrl(baseUrl)
  const q = tomlString
  const credentialBlocks = [
    { label: 'Bash / Zsh', content: `export VSP_API_KEY=${shellString(apiKey)}` },
    { label: 'PowerShell', content: `$env:VSP_API_KEY = ${powershellString(apiKey)}` }
  ]
  if (id === 'vsp-codex') {
    return [{ label: '~/.vsp-codex/config.toml', content:
      `model_provider = "vsp"\n\n[model_providers.vsp]\nname = "VSP Provider"\nbase_url = ${q(base)}\nexperimental_bearer_token = ${q(apiKey)}\nwire_api = "responses"\nrequires_openai_auth = false\nsupports_websockets = false\n` }]
  }
  if (id === 'codex') {
    const provider = 'vsplab'
    return [{ label: clients.find(client => client.id === id)!.path, content:
      `model_provider = ${q(provider)}\n\n[model_providers.${provider}]\nname = "VSP Lab"\nbase_url = ${q(base)}\nwire_api = "responses"\nrequires_openai_auth = false\nenv_key = "VSP_API_KEY"\n` }, ...credentialBlocks]
  }
  if (id === 'vspi') {
    return [{ label: '~/.vspi/config.toml', content:
      `[providers.vsplab]\ntype = "vsplab"\nbase_url = ${q(base)}\napi_key = ${q(apiKey)}\n\n[providers.vsplab.source]\nkind = "vsp-models"\nurl = ${q(catalogUrl(root))}\n` }]
  }
  if (id === 'zcode') {
    return [{ label: 'Settings → Model Providers → Add Provider', content: `Name: VSP Lab\nOpenAI Base URL: ${base}\nAnthropic Base URL: ${root}\nAPI Key: ${apiKey}` },
      { label: 'Model IDs', content: catalog?.models.map(model => model.id).join('\n') ?? '' }]
  }
  if (id === 'claude') {
    return [{ label: '~/.claude/settings.json', content: JSON.stringify({ env: {
      ANTHROPIC_BASE_URL: root, ANTHROPIC_AUTH_TOKEN: apiKey
    } }, null, 2) }]
  }
  if (id === 'opencode') {
    const sdks: Record<string, string> = { openai: '@ai-sdk/openai-compatible', openai_responses: '@ai-sdk/openai', anthropic: '@ai-sdk/anthropic' }
    const provider: Record<string, { npm: string; name: string; options: { baseURL: string }; models: Record<string, { name: string }> }> = {}
    const auth: Record<string, { type: string; key: string }> = {}
    for (const model of catalog?.models ?? []) {
      const protocol = model.protocol ?? 'openai'
      if (!Object.prototype.hasOwnProperty.call(sdks, protocol)) throw new Error('Unsupported OpenCode protocol')
      const id = `vsplab_${protocol}`
      if (!provider[id]) provider[id] = { npm: sdks[protocol], name: `VSP Lab (${protocol})`, options: { baseURL: base }, models: Object.create(null) }
      provider[id].models[model.id] = { name: model.name ?? model.id }
      auth[id] = { type: 'api', key: apiKey }
    }
    return [{ label: '~/.config/opencode/opencode.json', content: JSON.stringify({ $schema: 'https://opencode.ai/config.json', provider }, null, 2) },
      { label: '~/.local/share/opencode/auth.json', content: JSON.stringify(auth, null, 2) }]
  }
  if (id === 'pi') {
    const providers: Record<string, unknown> = {}
    for (const model of catalog?.models ?? []) {
      const protocol = model.protocol ?? 'openai'
      if (!Object.prototype.hasOwnProperty.call(piProtocols, protocol)) throw new Error('Unsupported Pi protocol')
      const providerId = `vsplab_${protocol}`
      if (!providers[providerId]) providers[providerId] = {
        baseUrl: protocolBaseUrl(root, protocol), api: piProtocols[protocol], apiKey: '$VSP_API_KEY', models: []
      }
      const provider = providers[providerId] as { models: unknown[] }
      provider.models.push({
        id: model.id, name: model.name, reasoning: model.reasoning,
        input: model.input?.filter(input => input === 'text' || input === 'image'),
        contextWindow: model.contextWindow, maxTokens: model.maxTokens
      })
    }
    // Environment references avoid Pi's command/literal expansion of arbitrary API keys.
    return [{ label: '~/.pi/agent/models.json', content: JSON.stringify({ providers }, null, 2) }, ...credentialBlocks]
  }
  const models = catalog?.models ?? []
  const protocols = [...new Set(models.map(model => model.protocol ?? 'openai'))]
  if (!protocols.length) protocols.push('openai')
  const sections: string[] = []
  for (const protocol of protocols) {
    if (!['openai', 'openai_responses', 'anthropic'].includes(protocol)) throw new Error('Unsupported Kimi protocol')
    const provider = `vsplab_${protocol}`
    sections.push(`[providers.${provider}]\ntype = ${q(protocol)}\nbase_url = ${q(protocolBaseUrl(root, protocol))}\napi_key = ${q(apiKey)}`)
    for (const model of models.filter(model => (model.protocol ?? 'openai') === protocol)) {
      let section = `[models.${q(`vsplab/${model.id}`)}]\nprovider = ${q(provider)}\nmodel = ${q(model.id)}`
      if (model.contextWindow !== undefined) section += `\nmax_context_size = ${model.contextWindow}`
      if (model.maxTokens !== undefined) section += `\nmax_output_size = ${model.maxTokens}`
      if (model.capabilities !== undefined) section += `\ncapabilities = ${JSON.stringify(model.capabilities)}`
      sections.push(section)
    }
  }
  return [{ label: '~/.kimi-code/config.toml', content: sections.join('\n\n') + '\n' }]
}
