import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { api, type IdeFile } from '../api'
import { acceptanceMark, ideRole, IdeController, otherFailures, type Mark } from '../ide'
import { parseMarkdown, type Block, type Inline } from '../markdown'
import type { OfficeModel } from '../model'
import { Branch, buildTree, Empty, type Decor, type Node } from './Explorer'
import { useRefetch } from './hooks'
import { LazyEdit } from './lazy'

interface Props {
  projectId: string | null
  model: OfficeModel
  replay: boolean
  onSubmit: (task: string) => Promise<void>
  onError: (e: unknown) => void
}

const BTN = 'rounded-md border px-3 py-1 text-[12.5px] font-semibold disabled:opacity-40'

/** The in-app IDE of Simulation mode: the files of your folder, an editor, the tests and the task document. No shell: the test panel is the terminal. */
export function IdeTab({ projectId, model, replay, onSubmit, onError }: Props) {
  const [pickRole, setPickRole] = useState('')
  const role = pickRole && model.humanRoles.has(pickRole) ? pickRole : ideRole(model.tasks, model.humanRoles)
  const fail = useRef(onError)
  useEffect(() => {
    fail.current = onError
  }, [onError])
  const ctl = useMemo(
    () =>
      new IdeController(
        {
          tree: (r) => api.ideTree(projectId!, r),
          read: (r, p) => api.ideRead(projectId!, r, p),
          write: (r, p, c) => api.ideWrite(projectId!, r, p, c),
          runTests: (r) => api.ideTests(projectId!, r),
        },
        (e) => fail.current(e),
      ),
    [projectId],
  )
  useSyncExternalStore(ctl.subscribe, ctl.getVersion)
  const [checking, setChecking] = useState(false)
  const [closed, setClosed] = useState<Set<string>>(new Set())
  const [adding, setAdding] = useState<string | null>(null)

  // reload the tree when the role, the project, the files of the build or the state of the tasks change
  const taskKey = model.tasks.map((t) => `${t.id}${t.status}`).join()
  useEffect(() => {
    ctl.setRole(role)
    if (projectId && role && !replay) void ctl.refresh()
  }, [ctl, projectId, role, replay, model.filesVersion, taskKey])

  const tree = ctl.tree
  const taskId = tree?.task ?? null
  const task = model.tasks.find((t) => t.id === taskId)

  // show a first file when the folder is ready: the first one that is yours and is not a test
  useEffect(() => {
    if (!tree?.ready || ctl.open) return
    const first = tree.files.find((f) => f.writable && !f.path.startsWith('tests/') && !f.path.endsWith('__init__.py')) ?? tree.files.find((f) => f.writable)
    if (first) void ctl.openFile(first.path)
  }, [ctl, tree, ctl.open])

  const root = useMemo(() => buildTree(tree?.files ?? []), [tree])
  const info = useMemo(() => {
    const files = new Map<string, IdeFile>((tree?.files ?? []).map((f) => [f.path, f]))
    const folders = new Map<string, { writable: number; owners: Set<string> }>()
    for (const f of tree?.files ?? []) {
      const parts = f.path.split('/')
      for (let i = 1; i < parts.length; i++) {
        const p = parts.slice(0, i).join('/')
        const e = folders.get(p) ?? { writable: 0, owners: new Set<string>() }
        e.writable += f.writable ? 1 : 0
        e.owners.add(f.owner)
        folders.set(p, e)
      }
    }
    return { files, folders }
  }, [tree])
  const open = useMemo(() => {
    const all = new Set<string>()
    const walk = (n: Node) => n.children.forEach((c) => { if (!c.file) { if (!closed.has(c.path)) all.add(c.path); walk(c) } })
    walk(root)
    return all
  }, [root, closed])
  const decor = (n: Node): Decor => {
    if (!tree?.task) return {}
    if (n.file) return { dim: !info.files.get(n.path)?.writable, dot: ctl.isDirty(n.path) ? 'Unsaved changes' : undefined }
    const f = info.folders.get(n.path)
    if (!f || f.writable) return {}
    const owner = f.owners.size === 1 ? [...f.owners][0] : ''
    return { dim: true, lock: owner ? (tree.names[owner] ?? owner) : 'read-only' }
  }

  const doc = useRefetch(projectId && taskId && !replay ? () => api.taskDoc(projectId, taskId) : null, `${projectId}:${taskId}`, 0, 50)
  const blocks = useMemo(() => (doc.data ? parseMarkdown(doc.data) : []), [doc.data])

  if (replay) return <Empty text="The IDE is for a live Simulation build. Turn Demo mode off to play a role yourself." />
  if (!projectId) return <Empty text="Start the build: your task and your folder appear here when it is your turn." />
  if (!role) return <Empty text="In Simulation mode you play one or more engineers. Pick the roles in the left panel before the build starts." />
  if (!tree) return <Empty text="Loading your folder…" />
  if (!tree.ready) return <Empty text="Your task has not started yet. Your folder appears when the tasks it waits for have been merged." />

  const writable = !!tree.task && ctl.writable(ctl.open)
  const dirty = ctl.open ? ctl.isDirty(ctl.open) : false
  const busy = model.ide.running || checking || ctl.saving
  const owner = ctl.file(ctl.open)?.owner
  const run = async () => {
    await ctl.run()
  }
  const submit = async () => {
    if (!tree.task) return
    setChecking(true)
    try {
      await ctl.submit(tree.task, onSubmit)
    } finally {
      setChecking(false)
    }
  }

  return (
    <div
      className="flex h-full min-h-0"
      onKeyDown={(e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
          e.preventDefault()
          void ctl.save()
        }
      }}
    >
      <div className="flex w-[240px] shrink-0 flex-col border-r border-[var(--line)]">
        <div className="flex shrink-0 items-center gap-2 border-b border-[var(--line)] px-2 py-1.5">
          {model.humanRoles.size > 1 ? (
            <div className="seg">
              {[...model.humanRoles].map((r) => (
                <button key={r} aria-pressed={role === r} onClick={() => setPickRole(r)}>{r}</button>
              ))}
            </div>
          ) : (
            <span className="text-[12px] font-bold uppercase tracking-wide text-[var(--muted)]">Your folder · {role}</span>
          )}
          <button onClick={() => setAdding(adding === null ? '' : null)} disabled={!tree.task} title="New file" aria-label="New file" className="ml-auto rounded px-1.5 text-[16px] leading-none text-[var(--muted)] hover:bg-[#1a2033] hover:text-white disabled:opacity-30">+</button>
        </div>
        {adding !== null && (
          <input
            autoFocus
            value={adding}
            placeholder={`${tree.editable[0]?.replace('**', '') ?? ''}new_file.py`}
            onChange={(e) => setAdding(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setAdding(null)
              if (e.key === 'Enter') void ctl.create(adding).then((ok) => ok && setAdding(null))
            }}
            className="m-2 rounded border border-[var(--accent)] bg-[#0b0e17] px-2 py-1 font-mono text-[12.5px] outline-none"
          />
        )}
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <Branch
            node={root}
            depth={0}
            open={open}
            toggle={(p) => setClosed((s) => { const n = new Set(s); if (n.has(p)) n.delete(p); else n.add(p); return n })}
            selected={ctl.open}
            onPick={(p) => void ctl.openFile(p)}
            changed={new Set()}
            decor={decor}
          />
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-2 border-b border-[var(--line)] px-3 py-1.5 text-[13px]">
          {ctl.open ? (
            <>
              <span className="truncate font-mono text-[#b9c4e0]">{ctl.open}</span>
              {dirty && <span className="text-[11px] text-[var(--warn)]" title="Unsaved changes" aria-label="Unsaved changes">●</span>}
              {ctl.loaded && !writable && (
                <span className="shrink-0 rounded border border-[var(--line)] px-1.5 py-[1px] text-[11px] text-[var(--muted)]">
                  🔒 read-only{owner && tree.task ? ` · ${tree.names[owner] ?? owner}'s file` : ''}
                </span>
              )}
            </>
          ) : (
            <span className="text-[var(--muted)]">{tree.task ? 'Pick a file from your folder.' : 'You have no open task right now.'}</span>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <button onClick={() => void ctl.save()} disabled={!dirty || !writable || ctl.saving} title="Save (Ctrl+S)" className={`${BTN} border-[var(--line)] text-[var(--text)] hover:border-[var(--accent)]`}>
              Save
            </button>
            <button onClick={run} disabled={!tree.task || busy} className={`${BTN} border-[var(--accent)] text-[var(--text)]`}>
              {model.ide.running && !checking ? 'Running…' : 'Run tests'}
            </button>
            <button onClick={submit} disabled={!tree.task || busy} className={`${BTN} border-transparent bg-[#2f9e5f] text-white hover:bg-[#38b36e]`}>
              {checking ? 'Checking…' : 'Submit for review'}
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1">
          {ctl.open && ctl.loaded ? (
            <LazyEdit path={ctl.open} value={ctl.text} readOnly={!writable} onChange={(t) => ctl.edit(t)} onSave={() => void ctl.save()} />
          ) : (
            <Empty text={ctl.loading ? 'Loading…' : tree.task ? 'Pick a file to edit it. The files of other roles are there to read.' : 'Waiting for your next task.'} />
          )}
        </div>
        <TestPanel model={model} />
      </div>

      <div className="flex w-[300px] shrink-0 flex-col border-l border-[var(--line)]">
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {taskId ? (doc.data ? <Doc blocks={blocks} /> : <div className="text-[13px] text-[var(--muted)]">{doc.error || 'Loading the task document…'}</div>) : <div className="text-[13px] text-[var(--muted)]">No open task. When the tasks before yours are merged, the task document appears here.</div>}
        </div>
        {task && <Acceptance model={model} entries={task.tests ?? []} />}
      </div>
    </div>
  )
}

function lineTone(line: string): string {
  if (/\b(FAILED|ERROR)\b|^E\s|Traceback/.test(line)) return 'var(--bad)'
  if (/\bPASSED\b|\b\d+ passed\b/.test(line)) return 'var(--good)'
  return '#9fb0d6'
}

function TestPanel({ model }: { model: OfficeModel }) {
  const { running, lines, cut, result } = model.ide
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [lines.length])
  return (
    <div className="flex h-[30%] min-h-[110px] shrink-0 flex-col border-t border-[var(--line)] bg-[#080b13]">
      <div className="flex shrink-0 items-center gap-2 border-b border-[var(--line)] px-3 py-1 text-[12px]">
        <span className="font-bold uppercase tracking-wide text-[var(--muted)]">Tests</span>
        {running && <span className="text-[var(--accent)]">running…</span>}
        {!running && result && (
          <span style={{ color: result.ok ? 'var(--good)' : 'var(--bad)' }}>
            {result.ok ? '✓' : '✗'} {result.summary}
          </span>
        )}
        {!running && !result && <span className="text-[var(--muted)]">Run tests to see the output here. There is no shell: this panel is your terminal.</span>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-1.5 font-mono text-[12.5px] leading-[1.45]" aria-label="Test output">
        {cut && <div className="text-[var(--muted)]">… older lines were dropped</div>}
        {lines.map((l, i) => (
          <div key={i} className="whitespace-pre-wrap break-all" style={{ color: lineTone(l) }}>{l || ' '}</div>
        ))}
        <div ref={end} />
      </div>
    </div>
  )
}

const MARK: Record<Mark, { icon: string; color: string; label: string }> = {
  pass: { icon: '✓', color: 'var(--good)', label: 'passed' },
  fail: { icon: '✗', color: 'var(--bad)', label: 'failed' },
  todo: { icon: '·', color: 'var(--muted)', label: 'not run yet' },
}

function Acceptance({ model, entries }: { model: OfficeModel; entries: string[] }) {
  const run = model.ide.result
  const extra = otherFailures(entries, run)
  return (
    <div className="max-h-[45%] shrink-0 overflow-y-auto border-t border-[var(--line)] p-3">
      <div className="mb-1.5 text-[12px] font-bold uppercase tracking-wide text-[var(--muted)]">Acceptance tests</div>
      {entries.length === 0 && <div className="text-[13px] text-[var(--muted)]">No test was written for this task. The whole suite has to pass.</div>}
      <ul className="space-y-1">
        {entries.map((e) => {
          const m = MARK[acceptanceMark(e, run)]
          return (
            <li key={e} className="flex items-start gap-2 font-mono text-[12.5px]">
              <span className="w-3 shrink-0 text-center font-bold" style={{ color: m.color }} title={m.label} aria-label={m.label}>{m.icon}</span>
              <span className="break-all text-[#b9c4e0]">{e}</span>
            </li>
          )
        })}
      </ul>
      {extra.length > 0 && (
        <div className="mt-2 text-[12.5px]">
          <div className="text-[var(--muted)]">Also failing in the suite:</div>
          {extra.slice(0, 6).map((t) => (
            <div key={t} className="flex gap-2 font-mono"><span className="w-3 shrink-0 text-center font-bold text-[var(--bad)]">✗</span><span className="break-all text-[#b9c4e0]">{t}</span></div>
          ))}
        </div>
      )}
      {run && <div className="mt-2 text-[12px] text-[var(--muted)]">Last run: {run.passed} passed, {run.failed} failed</div>}
    </div>
  )
}

function Spans({ spans }: { spans: Inline[] }) {
  return (
    <>
      {spans.map((s, i) =>
        s.code ? <code key={i} className="rounded bg-[#0b0e17] px-1 font-mono text-[12.5px] text-[#b9c4e0]">{s.text}</code> : s.bold ? <strong key={i} className="text-white">{s.text}</strong> : <span key={i}>{s.text}</span>,
      )}
    </>
  )
}

function Doc({ blocks }: { blocks: Block[] }) {
  return (
    <div className="space-y-2 text-[13.5px] leading-snug text-[var(--text)]">
      {blocks.map((b, i) =>
        b.kind === 'h' ? (
          <div key={i} className={b.level === 1 ? 'text-[15px] font-bold text-white' : 'mt-3 text-[12px] font-bold uppercase tracking-wide text-[var(--muted)]'}><Spans spans={b.spans} /></div>
        ) : b.kind === 'ul' ? (
          <ul key={i} className="list-disc space-y-0.5 pl-5">{b.items.map((it, j) => <li key={j}><Spans spans={it} /></li>)}</ul>
        ) : (
          <p key={i}><Spans spans={b.spans} /></p>
        ),
      )}
    </div>
  )
}
