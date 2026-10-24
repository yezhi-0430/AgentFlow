/**
 * 剪贴板写入与降级。
 *
 * 优先使用 navigator.clipboard；不可用或权限被拒绝时返回 manual，
 * 由调用方展示可手动复制的文本（不静默失败）。
 */

/**
 * @param {string} text 要复制的文本
 * @param {object} env 注入的全局对象，便于单元测试
 * @returns {Promise<{method: 'clipboard'|'manual'|'none', text: string}>}
 */
export async function copyText(text, env = globalThis) {
  const value = typeof text === 'string' ? text : String(text ?? '')
  if (!value) return { method: 'none', text: '' }

  try {
    const clipboard = env?.navigator?.clipboard
    if (clipboard && typeof clipboard.writeText === 'function') {
      await clipboard.writeText(value)
      return { method: 'clipboard', text: value }
    }
  } catch {
    // 权限被拒绝或浏览器不支持时继续降级为手动复制。
  }

  return { method: 'manual', text: value }
}
