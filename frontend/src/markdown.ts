// A small markdown reader for the task document Q writes (headings, bullet lists, paragraphs, `code`, **bold**). Nothing else is needed, and nothing is ever injected as HTML.

export type Inline = { text: string; code?: boolean; bold?: boolean }
export type Block =
  | { kind: 'h'; level: 1 | 2 | 3; spans: Inline[] }
  | { kind: 'ul'; items: Inline[][] }
  | { kind: 'p'; spans: Inline[] }

export function inline(text: string): Inline[] {
  const out: Inline[] = []
  const re = /`([^`]+)`|\*\*([^*]+)\*\*/g
  let last = 0
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index) })
    out.push(m[1] !== undefined ? { text: m[1], code: true } : { text: m[2], bold: true })
    last = m.index + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last) })
  return out
}

export function parseMarkdown(src: string): Block[] {
  const blocks: Block[] = []
  let para: string[] = []
  const flush = () => {
    if (para.length) blocks.push({ kind: 'p', spans: inline(para.join(' ')) })
    para = []
  }
  for (const raw of src.replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.trimEnd()
    const h = /^(#{1,3})\s+(.*)$/.exec(line)
    const li = /^\s*[-*]\s+(.*)$/.exec(line)
    if (h) {
      flush()
      blocks.push({ kind: 'h', level: h[1].length as 1 | 2 | 3, spans: inline(h[2]) })
    } else if (li) {
      flush()
      const last = blocks[blocks.length - 1]
      if (last?.kind === 'ul') last.items.push(inline(li[1]))
      else blocks.push({ kind: 'ul', items: [inline(li[1])] })
    } else if (!line.trim()) {
      flush()
    } else {
      para.push(line.trim())
    }
  }
  flush()
  return blocks
}
