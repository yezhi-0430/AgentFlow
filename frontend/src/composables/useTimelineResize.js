import { computed, ref } from 'vue'

const storageKey = 'agentflow.timeline-height'
const defaultHeight = 240
const minHeight = 120

export function useTimelineResize({
  getStorage = () => window.localStorage,
  getViewportHeight = () => window.innerHeight,
} = {}) {
  const viewportHeight = ref(getViewportHeight())
  const maxHeight = computed(() => Math.max(minHeight, viewportHeight.value - 120))
  const clamp = value => Math.round(Math.min(maxHeight.value, Math.max(minHeight, value)))
  let initialHeight = defaultHeight
  try {
    const saved = Number(getStorage().getItem(storageKey))
    if (Number.isFinite(saved) && saved > 0) initialHeight = saved
  } catch { /* Resizing remains available when storage is blocked. */ }
  const height = ref(clamp(initialHeight))
  const resizing = ref(false)
  let drag = null

  function persist() {
    try { getStorage().setItem(storageKey, String(height.value)) } catch { /* Optional preference. */ }
  }

  function beginResize(event, currentHeight = height.value) {
    if (drag || event.isPrimary === false || event.button !== 0) return
    event.preventDefault()
    drag = { id: event.pointerId, y: event.clientY, height: currentHeight, target: event.currentTarget }
    resizing.value = true
    event.currentTarget.focus?.({ preventScroll: true })
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function moveResize(event) {
    if (!drag || event.pointerId !== drag.id) return
    height.value = clamp(drag.height + event.clientY - drag.y)
  }

  function endResize(event) {
    if (!drag || (event && event.pointerId !== drag.id)) return
    const previous = drag
    drag = null
    resizing.value = false
    if (previous.target.hasPointerCapture(previous.id)) previous.target.releasePointerCapture(previous.id)
    persist()
  }

  function onResizeKey(event) {
    const sizes = { ArrowUp: height.value - 32, ArrowDown: height.value + 32, Home: minHeight, End: maxHeight.value }
    if (!Object.hasOwn(sizes, event.key)) return
    event.preventDefault()
    height.value = clamp(sizes[event.key])
    persist()
  }

  function resetHeight() {
    endResize()
    height.value = clamp(defaultHeight)
    try { getStorage().removeItem(storageKey) } catch { /* Optional preference. */ }
  }

  function fitViewport() {
    viewportHeight.value = getViewportHeight()
    height.value = clamp(height.value)
  }

  return { height, minHeight, maxHeight, resizing, beginResize, moveResize, endResize, onResizeKey, resetHeight, fitViewport }
}
