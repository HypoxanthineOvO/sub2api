import { catalogUrl } from './credentials'

export interface CatalogModel {
  id: string
  name?: string
  protocol?: string
  contextWindow?: number
  maxTokens?: number
  input?: string[]
  capabilities?: string[]
  reasoning?: boolean
  cost?: Record<string, unknown>
  [key: string]: unknown
}
export interface ModelCatalog {
  version?: number
  models: CatalogModel[]
  [key: string]: unknown
}

export function parseCatalog(payload: unknown): ModelCatalog {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('Invalid catalog')
  const catalog = payload as ModelCatalog
  if (catalog.version !== undefined && catalog.version !== 1) throw new Error('Unsupported catalog version')
  if (!Array.isArray(catalog.models) || catalog.models.length > 10000) throw new Error('Invalid model list')
  const ids = new Set<string>()
  for (const model of catalog.models) {
    if (!model || typeof model !== 'object' || typeof model.id !== 'string' || !model.id.trim() || model.id.length > 200 || ids.has(model.id.trim())) {
      throw new Error('Invalid or duplicate model ID')
    }
    ids.add(model.id.trim())
    for (const field of ['name', 'protocol'] as const) {
      const value = model[field]
      if (value !== undefined && (typeof value !== 'string' || !value.trim())) throw new Error('Invalid model metadata')
    }
    if (model.reasoning !== undefined && typeof model.reasoning !== 'boolean') throw new Error('Invalid reasoning flag')
    for (const field of ['input', 'capabilities'] as const) {
      const value = model[field]
      if (value !== undefined && (!Array.isArray(value) || value.some(item => typeof item !== 'string' || !item))) throw new Error('Invalid model capabilities')
    }
    for (const field of ['contextWindow', 'maxTokens'] as const) {
      const value = model[field]
      if (value !== undefined && (!Number.isSafeInteger(value) || value <= 0)) throw new Error('Invalid model limits')
    }
  }
  // Preserve unknown fields, hidden entries and offline models. This is metadata, not admission control.
  return catalog
}

export async function fetchCatalog(baseUrl: string, signal: AbortSignal): Promise<ModelCatalog> {
  const response = await fetch(catalogUrl(baseUrl), {
    signal, credentials: 'omit', redirect: 'error', headers: { Accept: 'application/json' }
  })
  if (!response.ok) throw new Error('Catalog request failed')
  const reader = response.body?.getReader()
  if (!reader) throw new Error('Missing catalog body')
  const chunks: Uint8Array[] = []
  let length = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      length += value.byteLength
      if (length > 4 * 1024 * 1024) throw new Error('Catalog too large')
      chunks.push(value)
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined)
    throw error
  } finally {
    reader.releaseLock()
  }
  const bytes = new Uint8Array(length)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
  return parseCatalog(JSON.parse(new TextDecoder().decode(bytes)))
}
