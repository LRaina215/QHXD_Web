<script setup lang="ts">
// 与小程序头像同一图形（public/brand/yuntuo-avatar.svg），内联以便随 CSS 尺寸缩放、不额外请求
withDefaults(defineProps<{ size?: number; rounded?: number }>(), { size: 40, rounded: 12 })
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 1024 1024" aria-hidden="true" :style="{ borderRadius: `${rounded}px` }">
    <rect width="1024" height="1024" fill="#2f5bff" />
    <path d="M168 846H500V766H856" fill="none" stroke="#fff" stroke-width="44" stroke-linecap="round" stroke-linejoin="round" />
    <g fill="none" stroke="#fff" stroke-width="54" stroke-linecap="round" stroke-linejoin="round">
      <path d="M396 452 292 588 322 712" />
      <path d="M628 452 734 532 702 634" />
    </g>
    <rect x="274" y="618" width="96" height="198" rx="48" fill="#fff" />
    <rect x="654" y="538" width="96" height="198" rx="48" fill="#fff" />
    <circle cx="322" cy="717" r="20" fill="#2f5bff" />
    <circle cx="702" cy="637" r="20" fill="#2f5bff" />
    <rect x="288" y="228" width="448" height="236" rx="104" fill="#fff" />
    <rect x="352" y="290" width="320" height="112" rx="56" fill="#15171a" />
    <circle cx="458" cy="346" r="24" fill="#fff" />
    <circle cx="566" cy="346" r="24" fill="#fff" />
  </svg>
</template>

<style scoped>
svg { display: block; flex: none; }
</style>
