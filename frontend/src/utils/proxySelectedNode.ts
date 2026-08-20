import type { Proxy } from '@/types'

export interface ProxySelectedNodeDisplay {
  status: NonNullable<Proxy['selected_node_status']>
  text: string
  title: string
  observedText?: string
}

const requestExitDisclaimer = '不代表单次请求实际出口'

export const formatProxySelectedNode = (proxy: Proxy): ProxySelectedNodeDisplay => {
  const status = proxy.selected_node_status ?? 'unavailable'
  const nodeName = proxy.selected_node_name?.trim()

  if (status === 'fresh') {
    return {
      status,
      text: nodeName || '节点不可用',
      title: `Mihomo Controller 当前选择节点，${requestExitDisclaimer}`
    }
  }
  if (status === 'stale') {
    const observedAt = proxy.selected_node_observed_at?.trim() || '时间未知'
    return {
      status,
      text: nodeName ? `${nodeName}（缓存）` : '节点不可用',
      observedText: `观测于 ${observedAt}`,
      title: `Mihomo Controller 节点缓存快照，观测于 ${observedAt}，不代表当前或单次请求实际出口`
    }
  }
  if (status === 'not_configured') {
    return {
      status,
      text: '未配置节点观测',
      title: `未配置 Mihomo Controller 当前节点观测，${requestExitDisclaimer}`
    }
  }
  return {
    status: 'unavailable',
    text: '节点不可用',
    title: `Mihomo Controller 当前选择节点不可用，${requestExitDisclaimer}`
  }
}

