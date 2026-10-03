import { useMemo, useState } from 'react'
import { api, type TreeFile } from '../api'
import { parseUnified } from '../diff'
import type { OfficeModel } from '../model'
import { useRefetch } from './hooks'
import { LazyCode, LazyDiff } from './lazy'

interface Node {
  name: string
  path: string
  children: Node[]
  file: boolean
}

function buildTree(files: TreeFile[]): Node {
  const root: Node = { name: '', path: '', children: [], file: false }
  for (const f of files) {
    let cur = root
    const parts = f.path.split('/')
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join('/')
      let next = cur.children.find((c) => c.name === part)
      if (!next) {
        next = { name: part, path, children: [], file: i === parts.length - 1 }
        cur.children.push(next)
      }
      cur = next
    })
  }
  const sort = (n: Node) => {
    n.children.sort((a, b) => Number(a.file) - Number(b.file) || Number(a.name.startsWith('.')) - Number(b.name.startsWith('.')) || a.name.localeCompare(b.name))
    n.children.forEach(sort)
  }
  sort(root)
  return root
}

function Branch({ node, depth, open, toggle, selected, onPick, changed }: { node: Node; depth: number; open: Set<string>; toggle: (p: string) => void; selected: string; onPick: (p: string) => void; changed: Set<string> }) {
  return (
    <>
      {node.children.map((c) =>
        c.file ? (
          <button key={c.path} onClick={() => onPick(c.path)} className="flex w-full items-center gap-1 truncate rounded px-1 py-[2px] text-left font-mono text-[12.5px] hover:bg-[#1a2033]" style={{ paddingLeft: 6 + depth * 12, background: selected === c.path ? '#243055' : undefined, color: selected === c.path ? '#fff' : '#b9c4e0' }}>
            <span className="truncate">{c.name}</span>
            {changed.has(c.path) && <span className="ml-auto text-[10px] text-[var(--accent)]" title="Changed in this build">●</span>}
          </button>
        ) : (
          <div key={c.path}>
            <button onClick={() => toggle(c.path)} className="flex w-full items-center gap-1 rounded px-1 py-[2px] text-left font-mono text-[12.5px] text-[var(--muted)] hover:bg-[#1a2033]" style={{ paddingLeft: 6 + depth * 12 }}>
              {open.has(c.path) ? '▾' : '▸'} {c.name}
            </button>
            {open.has(c.path) && <Branch node={c} depth={depth + 1} open={open} toggle={toggle} selected={selected} onPick={onPick} changed={changed} />}
          </div>
        ),
      )}
    </>
  )
}

export function Explorer({ projectId, model }: { projectId: string | null; model: OfficeModel }) {
  const tree = useRefetch(projectId ? () => api.files(projectId) : null, projectId ?? '', model.filesVersion)
  const [selected, setSelected] = useState('')
  const [view, setView] = useState<'file' | 'changes'>('file')
  const [pick, setPick] = useState<number | null>(null)
  const [closed, setClosed] = useState<Set<string>>(new Set())

  const root = useMemo(() => buildTree(tree.data ?? []), [tree.data])
  const open = useMemo(() => {
    const all = new Set<string>()
    const walk = (n: Node) => n.children.forEach((c) => { if (!c.file) { if (!closed.has(c.path)) all.add(c.path); walk(c) } })
    walk(root)
    return all
  }, [root, closed])
  const file = useRefetch(projectId && selected ? () => api.file(projectId, selected) : null, `${projectId}:${selected}`, model.filesVersion, 300)
  const versions = model.changes.get(selected) ?? []
  const shown = versions[pick ?? versions.length - 1]
  const diffs = useMemo(() => (shown ? parseUnified(shown.diff) : []), [shown])
  const changed = new Set(model.changes.keys())

  if (!projectId) return <Empty text="Start a build to browse the project files." />
  if (tree.error && !tree.data) return <Empty text={tree.error} />

  return (
    <div className="flex h-full min-h-0">
      <div className="w-[250px] shrink-0 overflow-y-auto border-r border-[var(--line)] p-2">
        {tree.data?.length ? (
          <Branch node={root} depth={0} open={open} toggle={(p) => setClosed((s) => { const n = new Set(s); if (n.has(p)) n.delete(p); else n.add(p); return n })} selected={selected} onPick={(p) => { setSelected(p); setPick(null) }} changed={changed} />
        ) : (
          <div className="p-2 text-[13px] text-[var(--muted)]">{tree.data ? 'No files yet.' : 'Loading…'}</div>
        )}
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        {selected ? (
          <>
            <div className="flex shrink-0 items-center gap-3 border-b border-[var(--line)] px-3 py-1.5 text-[13px]">
              <span className="truncate font-mono text-[#b9c4e0]">{selected}</span>
              <div className="seg ml-auto">
                <button aria-pressed={view === 'file'} onClick={() => setView('file')}>File</button>
                <button aria-pressed={view === 'changes'} onClick={() => setView('changes')} disabled={!versions.length} style={{ opacity: versions.length ? 1 : 0.4 }}>
                  Changes{versions.length ? ` (${versions.length})` : ''}
                </button>
              </div>
              {view === 'changes' && versions.length > 1 && (
                <select value={pick ?? versions.length - 1} onChange={(e) => setPick(Number(e.target.value))} className="rounded border border-[var(--line)] bg-[#0b0e17] px-2 py-0.5 text-[12px]">
                  {versions.map((v, i) => (
                    <option key={v.seq} value={i}>{`write ${i + 1} by ${model.name(v.agent)}`}</option>
                  ))}
                </select>
              )}
            </div>
            <div className="min-h-0 flex-1">
              {view === 'file' ? (
                file.data ? <LazyCode path={selected} content={file.data.content} /> : <Empty text={file.error || 'Loading…'} />
              ) : diffs.length ? (
                <LazyDiff path={diffs[0].path} original={diffs[0].original} modified={diffs[0].modified} />
              ) : (
                <Empty text="No recorded changes for this file." />
              )}
            </div>
          </>
        ) : (
          <Empty text="Pick a file to read it. Files changed during the build have a blue dot and a Changes view." />
        )}
      </div>
    </div>
  )
}

export function Empty({ text }: { text: string }) {
  return <div className="grid h-full place-items-center p-6 text-center text-[14px] text-[var(--muted)]">{text}</div>
}
