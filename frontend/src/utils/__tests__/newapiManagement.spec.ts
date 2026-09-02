import { describe, expect, it } from 'vitest'
import { suggestNewAPIManagementBaseUrl } from '../newapiManagement'

describe('suggestNewAPIManagementBaseUrl', () => {
  it('removes common model API suffixes', () => {
    expect(suggestNewAPIManagementBaseUrl('https://aimoniker.top/v1')).toBe('https://aimoniker.top')
    expect(suggestNewAPIManagementBaseUrl('https://relay.example.com/anthropic/')).toBe('https://relay.example.com')
  })

  it('preserves a deployment subpath', () => {
    expect(suggestNewAPIManagementBaseUrl('https://example.com/newapi/v1')).toBe('https://example.com/newapi')
  })
})
