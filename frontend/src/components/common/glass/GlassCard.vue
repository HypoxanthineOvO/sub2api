<template>
  <component :is="as" class="glass glass-card" :class="{ 'glass-card--flush': flush }">
    <slot />
  </component>
</template>

<script setup lang="ts">
/**
 * GlassCard —— 玻璃拟态基础卡片（C7-M2 设计基线）
 *
 * 表面样式（背景/边框/模糊/圆角/阴影）全部来自
 * src/styles/glass.tokens.css 的 --glass-* 变量，组件内不写死色值。
 * 主题由现有暗色机制驱动：html.dark → 主题 A（深空）；亮色 → 主题 B（晨雾）。
 */
import '@/styles/glass.tokens.css'

withDefaults(
  defineProps<{
    /** 根元素标签（默认 div，可传 section/article 等语义标签） */
    as?: string
    /** 紧凑内边距（8px 10px），用于内嵌表格的卡片容器 */
    flush?: boolean
  }>(),
  {
    as: 'div',
    flush: false
  }
)
</script>
