// Turns unified diff text (a file_changed event, `git show`, `git diff`) into original/modified pairs for Monaco's diff editor.

export interface FileDiff {
  path: string
  original: string
  modified: string
  added: number
  removed: number
}

const HUNK = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/
const GAP = '⋯'

function cleanPath(p: string): string {
  const t = p.trim().replace(/\t.*$/, '')
  return t === '/dev/null' ? '' : t.replace(/^[ab]\//, '')
}

interface Building extends FileDiff {
  o: string[]
  m: string[]
  hunks: number
}

export function parseUnified(text: string): FileDiff[] {
  const files: Building[] = []
  let cur: Building | null = null
  let oldLeft = 0
  let newLeft = 0
  let pendingOld = ''

  const start = (path: string): Building => {
    const b: Building = { path, original: '', modified: '', added: 0, removed: 0, o: [], m: [], hunks: 0 }
    files.push(b)
    return b
  }

  for (const line of text.replace(/\r\n/g, '\n').split('\n')) {
    if (cur && (oldLeft > 0 || newLeft > 0)) {
      const b: Building = cur
      const c = line[0]
      if (c === '\\') continue
      if (c === '+') {
        b.m.push(line.slice(1))
        b.added++
        newLeft--
      } else if (c === '-') {
        b.o.push(line.slice(1))
        b.removed++
        oldLeft--
      } else {
        const body = line.startsWith(' ') ? line.slice(1) : line // some tools strip the blank context marker
        b.o.push(body)
        b.m.push(body)
        oldLeft--
        newLeft--
      }
      continue
    }
    if (line.startsWith('diff --git ')) {
      const m = / b\/(.+)$/.exec(line)
      cur = start(m ? m[1] : '')
      pendingOld = ''
    } else if (line.startsWith('--- ')) {
      const cp = cleanPath(line.slice(4))
      const b: Building | null = cur
      if (!b || b.hunks > 0) cur = start(cp) // a plain `---/+++` diff has no `diff --git` header
      pendingOld = cp
    } else if (line.startsWith('+++ ') && cur) {
      const b: Building = cur
      b.path = cleanPath(line.slice(4)) || pendingOld || b.path
    } else {
      const h = HUNK.exec(line)
      const b: Building | null = cur
      if (h && b) {
        if (b.hunks > 0) {
          b.o.push(GAP)
          b.m.push(GAP)
        }
        b.hunks++
        oldLeft = h[2] === undefined ? 1 : Number(h[2])
        newLeft = h[4] === undefined ? 1 : Number(h[4])
      }
    }
  }
  return files.filter((f) => f.hunks > 0).map((f) => ({ path: f.path, added: f.added, removed: f.removed, original: f.o.join('\n'), modified: f.m.join('\n') }))
}

const LANGS: Record<string, string> = {
  py: 'python', js: 'javascript', mjs: 'javascript', ts: 'typescript', tsx: 'typescript', json: 'json', html: 'html', css: 'css',
  md: 'markdown', yaml: 'yaml', yml: 'yaml', sql: 'sql', txt: 'plaintext', toml: 'ini', ini: 'ini',
}

export function languageFor(path: string): string {
  return LANGS[path.split('.').pop()?.toLowerCase() ?? ''] ?? 'plaintext'
}
