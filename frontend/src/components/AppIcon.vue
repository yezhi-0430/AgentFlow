<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path v-for="(path, index) in (paths[name] || paths.grid)" :key="index" :d="path" />
  </svg>
</template>
<script setup>
defineProps({ name: String, size: { type: [Number, String], default: 18 } })
const paths = {
  key: ['M15 3a6 6 0 1 1-4.9 9.5L3 20v-4l2-2h3l2.5-2.5A6 6 0 0 1 15 3Z M16 7h.01'],
  eye: ['M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z'],
  eyeOff: ['M3 3l18 18 M10 5a13 13 0 0 1 2 0c6.5 0 10 7 10 7a20 20 0 0 1-3 4 M6 6a21 21 0 0 0-4 6s3.5 7 10 7a12 12 0 0 0 5-1 M10 10a3 3 0 0 0 4 4'],
  grid: ['M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z'],
  flow: ['M3 3h6v6H3z M15 15h6v6h-6z M6 9v9h9 M15 3h6v6h-6z M9 6h6'],
  plus: ['M12 5v14 M5 12h14'], minus: ['M5 12h14'],
  arrow: ['M5 12h14 M13 6l6 6-6 6'], chevron: ['M9 5l7 7-7 7'], down: ['M6 9l6 6 6-6'],
  close: ['M6 6l12 12 M18 6L6 18'], panel: ['M3 4h18v16H3z M15 4v16'],
  message: ['M21 11a8 8 0 0 1-8 8H7l-5 3V5a2 2 0 0 1 2-2h9a8 8 0 0 1 8 8Z M7 8h8 M7 12h5'],
  terminal: ['M4 7l5 5-5 5 M12 17h8'], play: ['M8 5l11 7-11 7z'],
  pause: ['M8 5v14 M16 5v14'], step: ['M5 5l10 7-10 7z M19 5v14'], stop: ['M6 6h12v12H6z'],
  fit: ['M8 3H3v5 M16 3h5v5 M21 16v5h-5 M3 16v5h5'],
  reset: ['M3 10a9 9 0 1 1 2 8 M3 4v6h6'],
  history: ['M3 12a9 9 0 1 0 3-6.7 M3 4v5h5 M12 7v5l3 2'],
  experiment: ['M9 3h6 M10.5 3v5.5L4.8 18a2 2 0 0 0 1.7 3h11a2 2 0 0 0 1.7-3L13.5 8.5V3 M7.5 15h9'],
  refresh: ['M20 11a8 8 0 0 0-14-5 M4 4v5h5 M4 13a8 8 0 0 0 14 5 M20 20v-5h-5'],
  download: ['M12 3v12 M7 10l5 5 5-5 M4 21h16'],
  upload: ['M12 21V9 M7 14l5-5 5 5 M4 3h16'],
  agent: ['M7 6h10a4 4 0 0 1 4 4v7a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3v-7a4 4 0 0 1 4-4Z M12 3v3 M8 11v2 M16 11v2 M9 17h6'],
  sliders: ['M4 7h9 M17 7h3 M4 17h3 M11 17h9 M13 4v6 M7 14v6'],
  layers: ['M12 3l10 6-10 6L2 9z M2 14l10 6 10-6'], check: ['M5 12l4 4L19 6'],
  trash: ['M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7'],
  parallel: ['M4 6h16 M4 12h16 M4 18h16'],
  hierarchy: ['M9 2h6v6H9z M2 16h6v6H2z M16 16h6v6h-6z M12 8v4 M5 16v-4h14v4'],
}
</script>
