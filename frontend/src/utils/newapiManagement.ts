export function suggestNewAPIManagementBaseUrl(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return ''
  try {
    const url = new URL(trimmed)
    const path = url.pathname.replace(/\/+$/, '').replace(/\/(?:v1|anthropic)$/i, '')
    return `${url.origin}${path}`.replace(/\/$/, '')
  } catch {
    return trimmed.replace(/\/+$/, '').replace(/\/(?:v1|anthropic)$/i, '')
  }
}
