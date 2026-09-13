import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchCatalog } from '../catalog'

afterEach(() => vi.unstubAllGlobals())
describe('public catalog transport', () => {
  it('sends no credentials or authorization and preserves all model declarations', async () => {
    const payload = { version: 1, models: [{ id: 'offline', hidden: true }], vendorExtension: 'keep' }
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload)))
    vi.stubGlobal('fetch', fetch)
    const signal = new AbortController().signal
    expect(await fetchCatalog('https://example.test/v1', signal)).toEqual(payload)
    expect(fetch).toHaveBeenCalledWith('https://example.test/vsp/models', {
      signal, credentials: 'omit', redirect: 'error', headers: { Accept: 'application/json' }
    })
  })
  it('rejects HTTP failures, invalid JSON and oversized bodies', async () => {
    for (const response of [new Response('unavailable', { status: 503 }), new Response('{bad'), new Response(' '.repeat(4 * 1024 * 1024 + 1))]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
      await expect(fetchCatalog('https://example.test', new AbortController().signal)).rejects.toThrow()
    }
  })
})
