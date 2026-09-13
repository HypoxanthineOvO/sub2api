export function rootBaseUrl(value: string): string {
  const url = new URL(value.trim())
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error('Invalid API base URL')
  }
  url.pathname = url.pathname.replace(/\/+$/, '').replace(/\/v1$/i, '')
  return url.toString().replace(/\/+$/, '')
}

export function protocolBaseUrl(value: string, protocol = 'openai'): string {
  const root = rootBaseUrl(value)
  return protocol === 'anthropic' ? root : `${root}/v1`
}

export function catalogUrl(value: string): string {
  return new URL('/vsp/models', rootBaseUrl(value)).toString()
}

export function combinedCredentials(baseUrl: string, apiKey: string): string {
  if (!apiKey.trim()) return ''
  return `BaseURL: ${rootBaseUrl(baseUrl)}, APIKey: ${apiKey}`
}

// JSON basic-string escapes are also valid for the TOML strings emitted here.
export const tomlString = (value: string): string => JSON.stringify(value).replace(/\u007f/g, '\\u007f')
export const shellString = (value: string): string => `'${value.replace(/'/g, `'"'"'`)}'`
export const powershellString = (value: string): string => `'${value.replace(/'/g, "''")}'`
