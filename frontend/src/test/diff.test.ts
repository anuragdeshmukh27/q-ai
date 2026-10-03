import { describe, expect, it } from 'vitest'
import { languageFor, parseUnified } from '../diff'
import { layoutGraph } from '../gitgraph'

describe('parseUnified', () => {
  it('reads a plain file_changed diff into original and modified text', () => {
    const d = parseUnified('--- a/backend/api/calc.py\n+++ b/backend/api/calc.py\n@@ -1,3 +1,3 @@\n def f(a, b):\n-    return a - b\n+    return a + b\n \n')
    expect(d).toHaveLength(1)
    expect(d[0].path).toBe('backend/api/calc.py')
    expect(d[0].original).toBe('def f(a, b):\n    return a - b\n')
    expect(d[0].modified).toBe('def f(a, b):\n    return a + b\n')
    expect([d[0].added, d[0].removed]).toEqual([1, 1])
  })

  it('handles a created file (empty original) and several files from git show', () => {
    const text = [
      'abc123', '[backend] POST /calc', 'Rohan', '', ' a.py | 2 ++', ' 2 files changed', '',
      'diff --git a/a.py b/a.py', 'new file mode 100644', 'index 0000000..1111111', '--- /dev/null', '+++ b/a.py', '@@ -0,0 +1,2 @@', '+x = 1', '+y = 2',
      'diff --git a/b.py b/b.py', 'index 1..2 100644', '--- a/b.py', '+++ b/b.py', '@@ -1 +1 @@', '-old', '+new',
    ].join('\n')
    const d = parseUnified(text)
    expect(d.map((f) => f.path)).toEqual(['a.py', 'b.py'])
    expect(d[0].original).toBe('')
    expect(d[0].modified).toBe('x = 1\ny = 2')
    expect([d[1].original, d[1].modified]).toEqual(['old', 'new'])
  })

  it('does not mistake a removed line that starts with "-- " for a file header, and joins hunks with a gap marker', () => {
    const d = parseUnified('--- a/q.sql\n+++ b/q.sql\n@@ -1,2 +1,1 @@\n--- comment\n keep\n@@ -9 +8 @@\n-a\n+b\n')
    expect(d).toHaveLength(1)
    expect(d[0].original).toBe('-- comment\nkeep\n⋯\na')
    expect(d[0].modified).toBe('keep\n⋯\nb')
  })

  it('returns nothing for text without hunks', () => {
    expect(parseUnified('')).toEqual([])
    expect(parseUnified('Binary files differ')).toEqual([])
  })

  it('picks a language from the extension', () => {
    expect([languageFor('static/app.js'), languageFor('backend/main.py'), languageFor('x.unknown')]).toEqual(['javascript', 'python', 'plaintext'])
  })
})

describe('layoutGraph', () => {
  const c = (hash: string, parents: string[]) => ({ hash, parents, refs: [], subject: hash, author: '' })

  it('keeps a straight history in one lane', () => {
    const { rows, lanes } = layoutGraph([c('c', ['b']), c('b', ['a']), c('a', [])])
    expect(rows.map((r) => r.lane)).toEqual([0, 0, 0])
    expect(lanes).toBe(1)
    expect(rows[0].edges).toEqual([{ to: 1, via: 0 }])
  })

  it('puts a merged branch in its own lane and brings it back at the fork point', () => {
    // m merges main (a2) and an agent branch (b1); both start from a1
    const { rows, lanes } = layoutGraph([c('m', ['a2', 'b1']), c('b1', ['a1']), c('a2', ['a1']), c('a1', [])])
    expect(rows.map((r) => r.lane)).toEqual([0, 1, 0, 0])
    expect(rows[0].edges.map((e) => e.via)).toEqual([0, 1])
    expect(rows[1].edges).toEqual([{ to: 3, via: 1 }])
    expect(lanes).toBe(2)
  })
})
