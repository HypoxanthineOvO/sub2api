import { describe, expect, it } from 'vitest'

import { formatProxySelectedNode } from '../proxySelectedNode'
import type { Proxy } from '@/types'

const makeProxy = (overrides: Partial<Proxy>): Proxy => ({
  id: 1,
  name: 'llm-mihomo-slot-a',
  protocol: 'http',
  host: '127.0.0.1',
  port: 7890,
  username: null,
  status: 'active',
  expires_at: null,
  fallback_mode: 'none',
  expiry_warn_days: 7,
  created_at: '2026-08-17T00:00:00Z',
  updated_at: '2026-08-17T00:00:00Z',
  ...overrides
})

describe('formatProxySelectedNode', () => {
  it('shows a fresh Controller selection without claiming a request exit', () => {
    const result = formatProxySelectedNode(makeProxy({
      selected_node_status: 'fresh',
      selected_node_name: '香港-HKT-01'
    }))

    expect(result).toMatchObject({ status: 'fresh', text: '香港-HKT-01' })
    expect(result.title).toContain('Mihomo Controller 当前选择节点')
    expect(result.title).toContain('不代表单次请求实际出口')
  })

  it('marks stale data as a cache snapshot and includes observed_at', () => {
    const result = formatProxySelectedNode(makeProxy({
      selected_node_status: 'stale',
      selected_node_name: '新加坡-SG-02',
      selected_node_observed_at: '2026-08-17T08:00:00Z'
    }))

    expect(result).toMatchObject({
      status: 'stale',
      text: '新加坡-SG-02（缓存）',
      observedText: '观测于 2026-08-17T08:00:00Z'
    })
    expect(result.title).toContain('缓存快照')
    expect(result.title).toContain('2026-08-17T08:00:00Z')
  })

  it('does not leak an old node when Controller status is unavailable', () => {
    const result = formatProxySelectedNode(makeProxy({
      selected_node_status: 'unavailable',
      selected_node_name: '旧节点不得显示'
    }))

    expect(result).toMatchObject({ status: 'unavailable', text: '节点不可用' })
    expect(result.text).not.toContain('旧节点不得显示')
  })

  it('distinguishes a proxy without node observation configuration', () => {
    const result = formatProxySelectedNode(makeProxy({
      selected_node_status: 'not_configured',
      selected_node_name: '旧节点不得显示'
    }))

    expect(result).toMatchObject({ status: 'not_configured', text: '未配置节点观测' })
  })
})

