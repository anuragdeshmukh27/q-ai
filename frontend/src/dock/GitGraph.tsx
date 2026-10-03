import { useMemo, useState } from 'react'
import { api } from '../api'
import { parseUnified } from '../diff'
import { layoutGraph } from '../gitgraph'
import type { OfficeModel } from '../model'
import { useRefetch } from './hooks'
import { Empty } from './Explorer'
import { LazyDiff } from './lazy'

const ROW = 30
const LANE = 18
const COLORS = ['#6ea8ff', '#4ade80', '#fbbf24', '#f472b6', '#a78bfa', '#2dd4bf', '#fb923c']

export function GitGraph({ projectId, model }: { projectId: string | null; model: OfficeModel }) {
  const commits = useRefetch(projectId ? () => api.commits(projectId) : null, projectId ?? '', model.filesVersion)
  const [sha, setSha] = useState('')
  const [file, setFile] = useState(0)
  const diff = useRefetch(projectId && sha ? () => api.commit(projectId, sha) : null, `${projectId}:${sha}`, 0, 0)
  const graph = useMemo(() => layoutGraph(commits.data ?? []), [commits.data])
  const files = useMemo(() => (diff.data ? parseUnified(diff.data.diff) : []), [diff.data])
  const cur = files[Math.min(file, Math.max(files.length - 1, 0))]

  if (!projectId) return <Empty text="Start a build to see its branches and merges." />
  if (!commits.data) return <Empty text={commits.error || 'Loading…'} />
  if (!commits.data.length) return <Empty text="No commits yet." />

  const x = (l: number) => 14 + l * LANE
  const y = (r: number) => ROW / 2 + r * ROW
  const width = 14 + graph.lanes * LANE + 8

  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-[0_0_52%] overflow-y-auto border-r border-[var(--line)]">
        <div className="relative" style={{ height: graph.rows.length * ROW }}>
          <svg width={width} height={graph.rows.length * ROW} className="absolute left-0 top-0">
            {graph.rows.map((r, i) =>
              r.edges.map((e, k) => {
                const col = COLORS[e.via % COLORS.length]
                const d = `M${x(r.lane)},${y(i)} L${x(e.via)},${y(i) + ROW * 0.5} L${x(e.via)},${y(e.to) - ROW * 0.5} L${x(graph.rows[e.to].lane)},${y(e.to)}`
                return <path key={`${i}-${k}`} d={d} stroke={col} strokeWidth={2} fill="none" opacity={0.85} />
              }),
            )}
            {graph.rows.map((r, i) => (
              <circle key={r.commit.hash} cx={x(r.lane)} cy={y(i)} r={r.commit.parents.length > 1 ? 6 : 4.5} fill={r.commit.parents.length > 1 ? '#0b0e17' : COLORS[r.lane % COLORS.length]} stroke={COLORS[r.lane % COLORS.length]} strokeWidth={2} />
            ))}
          </svg>
          {graph.rows.map((r, i) => (
            <button key={r.commit.hash} onClick={() => { setSha(r.commit.hash); setFile(0) }} className="absolute flex w-full items-center gap-2 text-left text-[13px] hover:bg-[#1a2033]" style={{ top: i * ROW, height: ROW, paddingLeft: width, background: sha === r.commit.hash ? '#243055' : undefined }}>
              {r.commit.refs.map((ref) => (
                <span key={ref} className="shrink-0 rounded-full border border-[#35508f] bg-[#16213f] px-2 text-[11px] font-semibold text-[#9cc0ff]">
                  {ref.replace('HEAD -> ', '')}
                </span>
              ))}
              <span className="truncate">{r.commit.subject}</span>
              <span className="ml-auto shrink-0 pr-3 font-mono text-[11px] text-[var(--muted)]">{r.commit.hash.slice(0, 7)}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        {!sha ? (
          <Empty text="Click a commit or a merge to see what it changed. A merge shows the whole task it brought into main." />
        ) : !diff.data ? (
          <Empty text={diff.error || 'Loading…'} />
        ) : !cur ? (
          <Empty text="This commit has no text changes." />
        ) : (
          <>
            <div className="flex shrink-0 flex-wrap items-center gap-1 border-b border-[var(--line)] px-2 py-1.5">
              {diff.data.merge && <span className="rounded bg-[#243055] px-2 py-0.5 text-[11px] font-bold">MERGE</span>}
              {files.map((f, i) => (
                <button key={f.path} onClick={() => setFile(i)} className="rounded px-2 py-0.5 font-mono text-[12px]" style={{ background: i === file ? '#243055' : 'transparent', color: i === file ? '#fff' : '#9fb0d4' }}>
                  {f.path} <span className="text-[var(--good)]">+{f.added}</span> <span className="text-[var(--bad)]">-{f.removed}</span>
                </button>
              ))}
            </div>
            <div className="min-h-0 flex-1">
              <LazyDiff path={cur.path} original={cur.original} modified={cur.modified} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
