export function moveOptionIndex(current, length, key) {
  if (!length) return -1
  if (key === 'Home') return 0
  if (key === 'End') return length - 1
  if (key === 'ArrowDown') return (current + 1 + length) % length
  if (key === 'ArrowUp') return (current < 0 ? length - 1 : current + length - 1) % length
  return current
}

export function findOptionMatch(options, query, current = -1) {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return -1
  for (let offset = 1; offset <= options.length; offset++) {
    const index = (current + offset + options.length) % options.length
    const option = options[index]
    if (option.label.toLowerCase().startsWith(normalized) || String(option.value || '').toLowerCase().startsWith(normalized)) return index
  }
  return -1
}
