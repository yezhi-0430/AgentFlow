/**
 * 工作流定义的浏览器传输：下载 / 剪贴板 / 手动复制降级，以及本地文件读取。
 *
 * 这里只处理文本，不知道任何密钥；浏览器 API 通过 env 注入，便于单元测试。
 */

/**
 * 尝试下载文本文件；不可用时依次降级到剪贴板、手动复制。
 * 返回 { method: 'download' | 'clipboard' | 'manual', text? }。
 */
export async function saveDefinitionText(text, filename, env = globalThis) {
  try {
    const { document, URL, Blob } = env || {}
    if (typeof Blob === 'function' && typeof document?.createElement === 'function' && typeof URL?.createObjectURL === 'function') {
      const blob = new Blob([text], { type: 'application/json;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.rel = 'noopener'
      document.body?.appendChild?.(link)
      link.click?.()
      link.remove?.()
      URL.revokeObjectURL?.(url)
      return { method: 'download' }
    }
  } catch {
    // 下载失败时继续尝试剪贴板。
  }

  try {
    const clipboard = env?.navigator?.clipboard
    if (clipboard && typeof clipboard.writeText === 'function') {
      await clipboard.writeText(text)
      return { method: 'clipboard' }
    }
  } catch {
    // 剪贴板权限被拒绝时继续降级。
  }

  return { method: 'manual', text }
}

/** 读取用户选择的 JSON 文件为文本；不支持时给出可粘贴的提示。 */
export async function readDefinitionFile(file) {
  if (file && typeof file.text === 'function') return await file.text()
  if (typeof FileReader === 'function') {
    return await new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result || ''))
      reader.onerror = () => reject(new Error('读取文件失败，请重试或直接粘贴 JSON 文本。'))
      reader.readAsText(file)
    })
  }
  throw new Error('当前浏览器不支持读取本地文件，请直接粘贴 JSON 文本。')
}
