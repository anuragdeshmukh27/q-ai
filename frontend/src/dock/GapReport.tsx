import { useEffect, useState } from 'react'
import { api } from '../api'
import type { OfficeModel } from '../model'
import { Empty } from './Explorer'

const KIND: Record<string, string> = {
  todo_body: 'placeholder body',
  missing_endpoint: 'missing endpoint',
  failing_test: 'failing test',
  todo_comment: 'TODO / FIXME',
  readme_feature: 'README feature',
}

/** Finish my project: what the analyst found in the imported project, the choice of what to fix, and the result (gaps closed, the diff of the finishing branch). */
export function GapReport({ projectId, model }: { projectId: string | null; model: OfficeModel }) {
  const f = model.finish
  const [ticked, setTicked] = useState<Set<string>>(new Set())
  const [sent, setSent] = useState(false)
  const key = f ? f.gaps.map((g) => g.id).join(',') : ''
  useEffect(() => {
    setTicked(new Set(f ? f.gaps.map((g) => g.id) : []))
    setSent(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  if (!f) return <Empty text="Import a half-built project (left panel, “Finish my project”): the analyst's gap report appears here." />
  const choosing = f.selecting && !sent
  const toggle = (id: string) => setTicked((t) => { const n = new Set(t); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const send = async () => {
    if (!projectId) return
    setSent(true)
    await api.finishPick(projectId, [...ticked]).catch(() => setSent(false))
  }
  const state = (id: string) => (f.fixed.includes(id) ? 'fixed' : f.open.includes(id) ? 'open' : f.selected.includes(id) ? 'queued' : '')
  return (
    <div className="h-full overflow-auto p-3 text-[13px]">
      <div className="mb-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="text-[14px] font-bold">Gap report</span>
        <span className="text-[var(--muted)]">
          {f.framework} app {f.entry} · {f.routes} routes · tables: {f.tables.join(', ') || 'none'} · tests before: {f.tests || 'not run'}
        </span>
        {choosing && (
          <button onClick={send} disabled={ticked.size === 0} className="ml-auto rounded-md bg-[#2f9e5f] px-3 py-1 text-[13px] font-bold text-white disabled:opacity-40">
            Fix {ticked.size} selected gap{ticked.size === 1 ? '' : 's'}
          </button>
        )}
      </div>
      {f.gaps.length === 0 && <Empty text="No gaps found: nothing to finish." />}
      <ul className="flex flex-col gap-1">
        {f.gaps.map((g) => (
          <li key={g.id} className="flex items-start gap-2 rounded-md border border-[var(--line)] bg-[#0b0e17] px-2.5 py-1.5">
            {choosing ? <input type="checkbox" checked={ticked.has(g.id)} onChange={() => toggle(g.id)} className="mt-[3px]" aria-label={g.title} /> : <span className="w-4" />}
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold">{g.title}</div>
              <div className="text-[11.5px] text-[var(--muted)]">{KIND[g.kind] ?? g.kind} · {g.file}</div>
            </div>
            {state(g.id) && (
              <span className="rounded-full px-2 py-[1px] text-[11px] font-bold" style={{ background: state(g.id) === 'fixed' ? '#1d4d32' : state(g.id) === 'open' ? '#5a2a2a' : '#243055', color: 'var(--text)' }}>
                {state(g.id)}
              </span>
            )}
          </li>
        ))}
      </ul>
      {f.summary && (
        <div className="mt-3" data-testid="finish-summary">
          <div className="mb-1 font-bold">
            What changed on the branch {f.summary.branch} (your folder and {f.summary.base} are untouched): {f.summary.files.length} file{f.summary.files.length === 1 ? '' : 's'}, +{f.summary.insertions} −{f.summary.deletions}
          </div>
          <div className="mb-1 text-[12px] text-[var(--muted)]">{f.summary.files.map((x) => `${x.path} (+${x.added} −${x.deleted})`).join(', ')}</div>
          <pre className="max-h-[260px] overflow-auto rounded-md border border-[var(--line)] bg-[#0b0e17] p-2 text-[11.5px] leading-snug">{f.summary.diff}{f.summary.truncated ? '\n… (cut)' : ''}</pre>
        </div>
      )}
    </div>
  )
}
