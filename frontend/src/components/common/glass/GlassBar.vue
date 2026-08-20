<template>
  <div
    class="glass-bar-track"
    :class="{ 'glass-bar-mini': mini }"
    role="progressbar"
    :aria-valuenow="clampedValue"
    :aria-valuemin="0"
    :aria-valuemax="100"
  >
    <div class="glass-bar-fill" :class="fillClass" :style="{ width: `${clampedValue}%` }"></div>
  </div>
</template>

<script setup lang="ts">
/**
 * GlassBar —— 玻璃拟态进度条（配额水位、调度概率）
 *
 * variant="auto" 时按 warnAt 阈值（默认 75%）自动切换告警渐变；
 * "mute" 用于暂停卡的 0% 占位。填充色取自 --glass-accent 等 tokens 变量。
 */
import { computed } from 'vue'

export type GlassBarVariant = 'auto' | 'default' | 'warn' | 'mute'

const props = withDefaults(
  defineProps<{
    /** 百分比 0-100，越界自动收敛 */
    value?: number
    variant?: GlassBarVariant
    /** auto 模式下的告警阈值（含），默认 75 */
    warnAt?: number
    /** 行内迷你条（状态表使用，90px × 6px） */
    mini?: boolean
  }>(),
  {
    value: 0,
    variant: 'auto',
    warnAt: 75,
    mini: false
  }
)

const clampedValue = computed(() => {
  const n = Number(props.value)
  if (!Number.isFinite(n)) return 0
  return Math.min(100, Math.max(0, n))
})

const fillClass = computed(() => {
  if (props.variant === 'mute') return 'glass-bar-fill--mute'
  const warn = props.variant === 'warn' || (props.variant === 'auto' && clampedValue.value >= props.warnAt)
  return warn ? 'glass-bar-fill--warn' : null
})
</script>
