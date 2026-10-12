import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { api, type IdeFile, type IdeTree } from '../api'
import { acceptanceMark, ideRole, IdeController, otherFailures, type Mark } from '../ide'
import { parseMarkdown, type Block, type Inline } from '../markdown'
import type { OfficeModel } from '../model'
import type { ScoringCriterion } from '../scenario'
import { Branch, buildTree, Empty, type Decor, type Node } from './Explorer'
import { useRefetch } from './hooks'
import { GuidePanel } from './GuidePanel'
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
          read: (r, p, a) => api.ideRead(projectId!, r, p, a),
          write: (r, p, c) => api.ideWrite(projectId!, r, p, c),
          runTests: (r) => api.ideTests(projectId!, r),
          search: (r, q) => api.ideSearch(projectId!, r, q),
        },
        (e) => fail.current(e),
      ),
    [projectId],
  )
  useSyncExternalStore(ctl.subscribe, ctl.getVersion, ctl.getVersion)
  const [checking, setChecking] = useState(false)
  const [closed, setClosed] = useState<Set<string>>(new Set())
  const [adding, setAdding] = useState<string | null>(null)
  const [left, setLeft] = useState<'files' | 'search'>('files') // the left column: the file tree, or the project-wide search (Ctrl+Shift+F)
  const [pending, setPending] = useState<Pending | null>(null) // a switch or a close that waits for the answer about unsaved edits
  const searchBox = useRef<HTMLInputElement>(null)
  const [scoringChoice, setScoringChoice] = useState<boolean | null>(null) // "How you are scored": open until your first test run, unless you opened or closed it yourself

  // leaving the page with edits that are not saved: the browser asks first
  const unsaved = ctl.dirty.length
  useEffect(() => {
    if (!unsaved) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [unsaved])

  /** Show a file (and a line of it). Leaving a file with unsaved edits asks first: save, switch and keep the edits unsaved, or stay. */
  const go = (target: string, line?: number) => {
    const from = ctl.unsavedBeforeSwitch(target)
    if (from) {
      setPending({ kind: 'switch', from, target, line })
      return
    }
    void show(target, line)
  }
  const show = async (target: string, line?: number) => {
    setPending(null)
    await ctl.pick(target, line)
  }
  const askClose = (path: string) => {
    if (ctl.isDirty(path)) setPending({ kind: 'close', path })
    else ctl.closeTab(path)
  }
  const answer = async (choice: 'save' | 'keep' | 'discard' | 'cancel') => {
    const p = pending
    setPending(null)
    if (!p || choice === 'cancel') return
    if (p.kind === 'switch') {
      if (choice === 'save' && !(await ctl.save(p.from))) return
      await show(p.target, p.line)
    } else if (choice === 'save') {
      if (await ctl.save(p.path)) ctl.closeTab(p.path)
    } else if (choice === 'discard') ctl.discardTab(p.path)
  }

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
    if (first) void ctl.openFile(first.path, true) // the IDE's own first file: logged as automatic, so it is not the guide's "open the failing route"
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
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'f') {
          e.preventDefault()
          setLeft('search')
          searchBox.current?.focus()
          searchBox.current?.select()
        } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
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
          ) : null}
          <div className="seg" role="group" aria-label="Left panel">
            <button aria-pressed={left === 'files'} onClick={() => setLeft('files')} title={`Your folder · ${role}`}>Files</button>
            <button aria-pressed={left === 'search'} onClick={() => setLeft('search')} title="Search every file of the project (Ctrl+Shift+F)">Search</button>
          </div>
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
        {left === 'search' ? (
          <SearchPanel ctl={ctl} tree={tree} box={searchBox} onPick={(p, l) => go(p, l)} />
        ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <Branch
            node={root}
            depth={0}
            open={open}
            toggle={(p) => setClosed((s) => { const n = new Set(s); if (n.has(p)) n.delete(p); else n.add(p); return n })}
            selected={ctl.open}
            onPick={(p) => go(p)}
            changed={new Set()}
            decor={decor}
          />
        </div>
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <Tabs ctl={ctl} tree={tree} onPick={(p) => go(p)} onClose={askClose} />
        {pending && <Unsaved pending={pending} onAnswer={(c) => void answer(c)} />}
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
            <LazyEdit path={ctl.open} value={ctl.text} readOnly={!writable} onChange={(t) => ctl.edit(t)} onSave={() => void ctl.save()} reveal={ctl.reveal?.path === ctl.open ? ctl.reveal : null} />
          ) : (
            <Empty text={ctl.loading ? 'Loading…' : tree.task ? 'Pick a file to edit it. The files of other roles are there to read.' : 'Waiting for your next task.'} />
          )}
        </div>
        <TestPanel model={model} />
      </div>

      <div className="flex w-[300px] shrink-0 flex-col border-l border-[var(--line)]">
        <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="p-3">
          {taskId ? (doc.data ? <Doc blocks={blocks} /> : <div className="text-[13px] text-[var(--muted)]">{doc.error || 'Loading the task document…'}</div>) : <div className="text-[13px] text-[var(--muted)]">No open task. When the tasks before yours are merged, the task document appears here.</div>}
          {model.scenario && model.scenario.scoring.length > 0 && (
            <ScoringPanel scoring={model.scenario.scoring} name={(id) => model.name(id) || id} open={scoringChoice ?? model.ide.result === null} onToggle={setScoringChoice} />
          )}
        </div>
        {model.guide && <GuidePanel guide={model.guide} />}
        {task && <Acceptance model={model} entries={task.tests ?? []} />}
        </div>
      </div>
    </div>
  )
}

type Pending = { kind: 'switch'; from: string; target: string; line?: number } | { kind: 'close'; path: string }

const base = (p: string) => p.split('/').pop() ?? p

/** The open files as tabs: a dot for unsaved edits, a lock for files you may not edit, a cross to close. */
export function Tabs({ ctl, tree, onPick, onClose }: { ctl: IdeController; tree: IdeTree; onPick: (p: string) => void; onClose: (p: string) => void }) {
  if (ctl.tabs.length === 0) return null
  return (
    <div className="flex shrink-0 overflow-x-auto border-b border-[var(--line)] bg-[#0b0e17]" role="tablist" aria-label="Open files">
      {ctl.tabs.map((p) => {
        const active = p === ctl.open
        const dirty = ctl.isDirty(p)
        const locked = !!tree.task && !ctl.writable(p)
        return (
          <div key={p} role="presentation" className={`group flex shrink-0 items-center gap-1.5 border-r border-[var(--line)] px-2.5 py-1.5 text-[12.5px] ${active ? 'bg-[var(--panel)] text-white' : 'text-[var(--muted)] hover:text-white'}`} style={active ? { boxShadow: 'inset 0 -2px 0 var(--accent)' } : undefined}>
            <button role="tab" aria-selected={active} title={p} onClick={() => onPick(p)} className="flex items-center gap-1.5 font-mono">
              {locked && <span aria-label="read-only" title="read-only">🔒</span>}
              <span>{base(p)}</span>
              {dirty && <span className="text-[11px] text-[var(--warn)]" title="Unsaved changes" aria-label="Unsaved changes">●</span>}
            </button>
            <button onClick={() => onClose(p)} aria-label={`Close ${base(p)}`} title="Close" className="rounded px-1 text-[14px] leading-none text-[var(--muted)] hover:bg-[#1a2033] hover:text-white">×</button>
          </div>
        )
      })}
    </div>
  )
}

/** The question when leaving or closing a file whose edits are not saved. */
export function Unsaved({ pending, onAnswer }: { pending: Pending; onAnswer: (c: 'save' | 'keep' | 'discard' | 'cancel') => void }) {
  const path = pending.kind === 'switch' ? pending.from : pending.path
  const B = 'rounded-md border px-2.5 py-1 text-[12.5px] font-semibold'
  return (
    <div role="alertdialog" aria-label="Unsaved changes" className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[var(--warn)] bg-[#2a210a] px-3 py-1.5 text-[13px] text-[var(--warn)]">
      <span><b className="font-mono">{base(path)}</b> has changes that are not saved.</span>
      <div className="ml-auto flex gap-2">
        <button onClick={() => onAnswer('save')} className={`${B} border-transparent bg-[#2f9e5f] text-white hover:bg-[#38b36e]`}>{pending.kind === 'switch' ? 'Save and switch' : 'Save and close'}</button>
        {pending.kind === 'switch' ? (
          <button onClick={() => onAnswer('keep')} className={`${B} border-[var(--line)] text-[var(--text)] hover:border-[var(--accent)]`} title="The edits stay in their tab, with the dot">Switch, keep unsaved</button>
        ) : (
          <button onClick={() => onAnswer('discard')} className={`${B} border-[var(--bad)] text-[var(--bad)] hover:bg-[#2a1013]`}>Discard changes</button>
        )}
        <button onClick={() => onAnswer('cancel')} className={`${B} border-[var(--line)] text-[var(--text)] hover:border-[var(--accent)]`}>Cancel</button>
      </div>
    </div>
  )
}

/** Project-wide search (Ctrl+Shift+F): every file of the folder, the ones you may not edit included; results by file and line, a click opens the line. */
export function SearchPanel({ ctl, tree, box, onPick }: { ctl: IdeController; tree: IdeTree; box: React.RefObject<HTMLInputElement | null>; onPick: (path: string, line: number) => void }) {
  const [text, setText] = useState(ctl.query)
  const found = ctl.found
  const locked = (p: string) => !!tree.files.find((f) => f.path === p && !f.writable)
  return (
    <div className="flex min-h-0 flex-1 flex-col" aria-label="Search">
      <form
        className="shrink-0 p-2"
        onSubmit={(e) => {
          e.preventDefault()
          void ctl.search(text)
        }}
      >
        <input
          ref={box}
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Search all files…"
          aria-label="Search all files"
          maxLength={200}
          className="w-full rounded border border-[var(--line)] bg-[#0b0e17] px-2 py-1 font-mono text-[12.5px] outline-none focus:border-[var(--accent)]"
        />
      </form>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 text-[12.5px]" aria-label="Search results">
        {ctl.searching && <div className="text-[var(--muted)]">Searching…</div>}
        {!ctl.searching && !found && <div className="text-[var(--muted)]">Press Enter to search every file of the project, the read-only ones too.</div>}
        {!ctl.searching && found && (
          <div className="mb-1.5 text-[var(--muted)]" aria-live="polite">
            {found.matches === 0 ? `No match for “${found.query}”.` : `${found.matches} match${found.matches === 1 ? '' : 'es'} in ${found.files} file${found.files === 1 ? '' : 's'}`}
            {found.truncated && ' (the first files are listed)'}
          </div>
        )}
        {found?.results.map((f) => (
          <div key={f.path} className="mb-2">
            <div className="flex items-center gap-1.5 font-mono font-semibold text-[#b9c4e0]" title={f.path}>
              {locked(f.path) && <span aria-label="read-only">🔒</span>}
              <span className="truncate">{f.path}</span>
              <span className="ml-auto shrink-0 rounded-full bg-[#1a2033] px-1.5 text-[11px] text-[var(--muted)]">{f.count}</span>
            </div>
            {f.lines.map((l) => (
              <button key={l.line} onClick={() => onPick(f.path, l.line)} className="flex w-full gap-2 rounded px-1 py-[1px] text-left font-mono hover:bg-[#1a2033]" title={`${f.path}:${l.line}`}>
                <span className="w-8 shrink-0 text-right tabular-nums text-[var(--muted)]">{l.line}</span>
                <span className="truncate text-[#c9d3ee]">{l.text}</span>
              </button>
            ))}
            {f.count > f.lines.length && <div className="pl-10 text-[var(--muted)]">… {f.count - f.lines.length} more in this file</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

/** "How you are scored": the 20 rules of the debrief in plain words, by criterion and judge, shown with the task so that nothing in the report is a surprise. */
export function ScoringPanel({ scoring, name, open = true, onToggle }: { scoring: ScoringCriterion[]; name: (employee: string) => string; open?: boolean; onToggle?: (open: boolean) => void }) {
  const rules = scoring.reduce((n, c) => n + c.rules.length, 0)
  return (
    <details open={open} onToggle={(e) => onToggle?.((e.currentTarget as HTMLDetailsElement).open)} className="mt-4 border-t border-[var(--line)] pt-3" aria-label="How you are scored">
      <summary className="cursor-pointer text-[12px] font-bold uppercase tracking-wide text-[var(--muted)] hover:text-white">
        How you are scored <span className="ml-1 font-normal normal-case">· {rules} rules, {new Set(scoring.map((c) => c.judge)).size} judges, 100 marks</span>
      </summary>
      <p className="mt-1.5 text-[12.5px] leading-snug text-[var(--muted)]">Each rule is worth one point (5 marks); every criterion has 4. The judges give their scores in the meeting room after your fix is accepted, and each point quotes a moment of your session.</p>
      <div className="mt-2 space-y-2.5">
        {scoring.map((c) => (
          <section key={c.id} aria-label={c.name}>
            <h4 className="text-[13px] font-bold text-white">
              {c.name} <span className="font-normal text-[var(--muted)]">· judge {name(c.judge)}</span>
            </h4>
            <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-[12.5px] leading-snug text-[#c9d3ee]">
              {c.rules.map((r) => (
                <li key={r.id}>{r.plain}</li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </details>
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
