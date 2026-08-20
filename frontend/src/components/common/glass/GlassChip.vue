<template>
  <span class="glass-chip whitespace-nowrap shrink-0" :class="toneClass"><slot /></span>
</template>

<script setup lang="ts">
/**
 * GlassChip —— 玻璃拟态状态徽标（调度中/已暂停/切卡等）
 *
 * 固定 white-space: nowrap + flex-shrink: 0（tokens css），
 * 在卡片头行右侧任何宽度下不换行、不压缩。
 */
import { computed } from 'vue'

export type GlassChipTone = 'default' | 'ok' | 'stop' | 'swap'

const props = withDefaults(
  defineProps<{
    tone?: GlassChipTone
  }>(),
  {
    tone: 'default'
  }
)

const toneClass = computed(() => (props.tone === 'default' ? null : `glass-chip--${props.tone}`))
</script>
