import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({
  breaks: true,
  gfm: true,
})

export function renderMarkdown(text) {
  const source = (text || '').trim()
  if (!source) return ''
  const html = marked.parse(source, { async: false })
  return DOMPurify.sanitize(html)
}
