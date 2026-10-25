const PALETTE = ['#2F6F78', '#B45309', '#6D28D9', '#BE123C', '#0369A1', '#4D7C0F', '#9A3412', '#475569']

export function avatarFor(name = 'member', model = '') {
  const seed = `${name}|${model}`
  let hash = 0
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0
  }
  const cleaned = String(name || 'member').replace(/^member_?/i, '')
  const initials = (cleaned.match(/[A-Za-z0-9]/)?.[0] || cleaned.slice(0, 1) || 'A').toUpperCase()
  return { initials, color: PALETTE[hash % PALETTE.length] }
}
