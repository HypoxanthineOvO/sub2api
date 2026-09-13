import type { ModelCatalog } from './catalog'
import { catalogUrl, protocolBaseUrl, rootBaseUrl, tomlString, shellString, powershellString } from './credentials'

export const clients = [
  { id: 'codex', name: 'Codex', path: '~/.codex/config.toml', docs: 'https://learn.chatgpt.com/docs/config-file/config-reference' },
  { id: 'pi', name: 'Pi', path: '~/.pi/agent/models.json', docs: 'https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md' },
  { id: 'zcode', name: 'ZCode', path: 'Settings → Model Providers → Add Provider', docs: 'https://zcode.z.ai/en/docs/configuration' },
  { id: 'kimi', name: 'Kimi Code', path: '~/.kimi/config.toml', docs: 'https://moonshotai.github.io/kimi-code/en/configuration/providers' },
  { id: 'vsp-codex', name: 'VSP-Codex', path: '~/.vsp-codex/config.toml', docs: '' },
  { id: 'vspi', name: 'VSPi', path: '~/.vspi/config.toml', docs: '' }
] as const
export type ClientId = typeof clients[number]['id']
export interface ConfigBlock { label: string; content: string }

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
  if (id === 'codex' || id === 'vsp-codex') {
    const provider = id === 'codex' ? 'vsplab' : 'vsp'
    return [{ label: clients.find(client => client.id === id)!.path, content:
      `model_provider = ${q(provider)}\n\n[model_providers.${provider}]\nname = "VSP Lab"\nbase_url = ${q(base)}\nwire_api = "responses"\nrequires_openai_auth = false\nenv_key = "VSP_API_KEY"\n` }, ...credentialBlocks]
  }
  if (id === 'vspi') {
    return [{ label: '~/.vspi/config.toml', content:
      `[providers.vsplab]\ntype = "vsplab"\nbase_url = ${q(base)}\napi_key = ${q(apiKey)}\n\n[providers.vsplab.source]\nkind = "vsp-models"\nurl = ${q(catalogUrl(root))}\n` }]
  }
  if (id === 'zcode') {
    return [{ label: 'Provider', content: `Name: VSP Lab\nOpenAI Base URL: ${base}\nAnthropic Base URL: ${root}\nAPI Key: ${apiKey}` },
      { label: 'Model IDs', content: catalog?.models.map(model => model.id).join('\n') ?? '' }]
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
  return [{ label: '~/.kimi/config.toml', content: sections.join('\n\n') + '\n' }]
}
