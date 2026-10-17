import test from 'node:test'
import assert from 'node:assert/strict'
import { useTimelineResize } from '../src/composables/useTimelineResize.js'

function setup(saved) {
  const values = new Map(saved == null ? [] : [['agentflow.timeline-height', saved]])
  const storage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  let viewport = 900
  const resize = useTimelineResize({ getStorage: () => storage, getViewportHeight: () => viewport })
  const target = { setPointerCapture() {}, hasPointerCapture: () => true, releasePointerCapture() {} }
  const pointer = (y, id = 1) => ({ clientY: y, pointerId: id, button: 0, isPrimary: true, currentTarget: target, preventDefault() {} })
  return { resize, values, pointer, setViewport: value => { viewport = value } }
}
test('dragging changes height immediately and saves the final size', () => {
  const { resize, values, pointer } = setup()
  resize.beginResize(pointer(300))
  resize.moveResize(pointer(500))
  assert.equal(resize.height.value, 440)
  assert.equal(resize.resizing.value, true)
  assert.equal(values.size, 0)
  resize.endResize(pointer(500))
  assert.equal(resize.resizing.value, false)
  assert.equal(values.get('agentflow.timeline-height'), '440')
  resize.moveResize(pointer(600))
  assert.equal(resize.height.value, 440)
})
test('another pointer cannot resize or end the active drag', () => {
  const { resize, pointer } = setup()
  resize.beginResize(pointer(100))
  resize.moveResize(pointer(300, 2))
  resize.endResize(pointer(300, 2))
  assert.equal(resize.height.value, 240)
  assert.equal(resize.resizing.value, true)
  resize.endResize(pointer(100))
})
test('keyboard resizing respects reading bounds and persists the selection', () => {
  const { resize, values } = setup()
  let prevented = false
  resize.onResizeKey({ key: 'ArrowDown', preventDefault() { prevented = true } })
  assert.equal(resize.height.value, 272)
  assert.equal(prevented, true)
  resize.onResizeKey({ key: 'End', preventDefault() {} })
  assert.equal(resize.height.value, 780)
  resize.onResizeKey({ key: 'Home', preventDefault() {} })
  assert.equal(resize.height.value, 120)
  assert.equal(values.get('agentflow.timeline-height'), '120')
})
test('saved size survives remounting while corrupt storage falls back safely', () => {
  assert.equal(setup('480').resize.height.value, 480)
  assert.equal(setup('not-a-height').resize.height.value, 240)
  assert.equal(setup('Infinity').resize.height.value, 240)
})
test('reset restores default size and clears the remembered size', () => {
  const { resize, values } = setup('500')
  resize.resetHeight()
  assert.equal(resize.height.value, 240)
  assert.equal(values.size, 0)
})
test('shrinking the viewport keeps the panel reachable without overwriting the preferred size', () => {
  const { resize, values, setViewport } = setup('700')
  setViewport(500)
  resize.fitViewport()
  assert.equal(resize.height.value, 380)
  assert.equal(resize.maxHeight.value, 380)
  assert.equal(values.get('agentflow.timeline-height'), '700')
})
test('blocked browser storage does not break resize interactions', () => {
  const resize = useTimelineResize({ getStorage: () => { throw new Error('storage blocked') }, getViewportHeight: () => 900 })
  assert.doesNotThrow(() => resize.onResizeKey({ key: 'ArrowDown', preventDefault() {} }))
  assert.equal(resize.height.value, 272)
  assert.doesNotThrow(() => resize.resetHeight())
})
