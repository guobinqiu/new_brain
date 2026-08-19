export async function copyText(value) {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = value
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
}

export function shortTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function ms(value) {
  if (value === null || value === undefined) return '-'
  return `${Number(value).toFixed(1)}`
}

export function parseFileIds(value) {
  return Array.from(new Set(value.split(',').map(item => item.trim()).filter(Boolean)))
}

export function escapeHtml(text) {
  const el = document.createElement('div')
  el.textContent = text
  return el.innerHTML
}
