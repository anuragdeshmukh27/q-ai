import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ApiError, api, type ModelInfo } from '../api'
import { STATE_COLOR, STATE_LABEL } from '../office/palette'
import type { AgentView, OfficeModel } from '../model'

const ENGINEERS = ['backend', 'frontend', 'database']

interface Props {
  agent: AgentView
  model: OfficeModel
  projectId: string | null
  replay: boolean
  models: ModelInfo[]
  onClose: () => void
  onError: (e: unknown) => void
}

function ModelPicker({ agent, model, projectId, replay, models, onError }: Omit<Props, 'onClose'>) {
  const value = model.overrides.get(agent.id) ?? ''
  const off = !projectId || replay
  return (
    <div>
      <select
        value={value}
        disabled={off}
        onChange={(e) => projectId && api.override(projectId, agent.id, e.target.value || null).catch(onError)}
        title={replay ? 'Demo mode replays a recording; model changes apply to live builds' : 'Choose which model this employee uses from its next task'}
        className="h-9 w-full rounded-lg border border-[var(--line)] bg-[#0b0e17] px-2 text-[14px] text-[var(--text)] disabled:opacity-60"
      >
        <option value="">Auto (router){agent.model ? ` · now ${agent.model}` : ''}</option>
        {models.map((m) => (
          <option key={m.id} value={m.id} disabled={!m.available}>
            {m.name} · {m.local ? 'local' : 'cloud'}{m.available ? '' : ' (unavailable)'}
          </option>
        ))}
      </select>
      {replay && <div className="mt-1 text-[12px] text-[var(--muted)]">Replay: the recorded model is shown.</div>}
    </div>
  )
}

function AskBox({ agent, model, projectId, replay }: Omit<Props, 'onClose' | 'models' | 'onError'>) {
  const [text, setText] = useState('')
  const [task, setTask] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [err, setErr] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const chat = model.messages.filter((m) => (m.from === 'human' && m.to === agent.id) || (m.from === agent.id && m.to === 'human'))
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [chat.length, waiting])
  const canTask = ENGINEERS.includes(agent.id)
  const off = !projectId || replay

  const send = async () => {
    const t = text.trim()
    if (!t || waiting || off) return
    setWaiting(true)
    setErr('')
    try {
      await api.ask(projectId!, agent.id, t, task && canTask)
      setText('')
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not reach the employee.')
    } finally {
      setWaiting(false)
    }
  }

  return (
    <div>
      <div className="max-h-[170px] min-h-[56px] overflow-y-auto rounded-lg bg-[#080b13] p-2 text-[13px] leading-snug">
        {chat.length === 0 && !waiting && <span className="text-[var(--muted)]">{off ? (replay ? 'Asking works during a live build, not in a replay.' : 'Start a build to talk to the team.') : `Ask ${agent.name} anything about the project.`}</span>}
        {chat.map((m, i) => (
          <div key={i} className={m.from === 'human' ? 'text-right text-[#9cc0ff]' : 'text-[var(--text)]'}>
            <span className="text-[11px] font-bold text-[var(--muted)]">{m.from === 'human' ? 'You' : agent.name}</span>
            <div>{m.text}</div>
          </div>
        ))}
        {waiting && <div className="text-[var(--muted)]">{agent.name} is thinking…</div>}
        <div ref={end} />
      </div>
      {err && <div className="mt-1 text-[12.5px] text-[var(--bad)]">{err}</div>}
      <div className="mt-2 flex gap-2">
        <input
          value={text}
          disabled={off}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder={task && canTask ? `Give ${agent.name} a task…` : `Ask ${agent.name}…`}
          className="h-9 min-w-0 flex-1 rounded-lg border border-[var(--line)] bg-[#0b0e17] px-3 text-[14px] text-[var(--text)] outline-none focus:border-[var(--accent)] disabled:opacity-50"
        />
        <button onClick={send} disabled={off || waiting || !text.trim()} className="rounded-lg bg-[#3563e6] px-3 text-[14px] font-bold text-white disabled:opacity-40">
          Send
        </button>
      </div>
      {canTask && (
        <label className="mt-1.5 flex items-center gap-2 text-[12.5px] text-[var(--muted)]">
          <input type="checkbox" checked={task} disabled={off} onChange={(e) => setTask(e.target.checked)} />
          Send as a task (only {agent.name} receives it)
        </label>
      )}
    </div>
  )
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-[11px] font-semibold tracking-wider text-[var(--muted)]">{k}</div>
      <div className="mt-0.5 text-[14px] leading-snug">{children}</div>
    </div>
  )
}

export function Inspector(p: Props) {
  const { agent, onClose } = p
  const col = STATE_COLOR[agent.state] ?? '#7c8499'
  return (
    <aside className="flex w-[330px] shrink-0 flex-col gap-4 overflow-y-auto border-l border-[var(--line)] bg-[var(--panel)] p-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[22px] font-extrabold leading-tight">{agent.name}</div>
          <div className="text-[14px] text-[var(--muted)]">{agent.role}</div>
        </div>
        <button onClick={onClose} aria-label="Close" className="rounded-md px-2 py-1 text-[18px] text-[var(--muted)] hover:bg-[#1a2033] hover:text-white">
          ✕
        </button>
      </div>

      <div className="inline-flex w-fit items-center gap-2 rounded-full border px-3 py-1 text-[13px] font-bold" style={{ borderColor: col, color: col }}>
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: col }} />
        {STATE_LABEL[agent.state] ?? agent.state}
      </div>

      <Row k="MODEL">
        <ModelPicker {...p} />
      </Row>
      <Row k={`ASK ${agent.name.toUpperCase()}`}>
        <AskBox agent={agent} model={p.model} projectId={p.projectId} replay={p.replay} />
      </Row>
      <Row k="ITERATION">{agent.maxIterations ? `${agent.iteration} of ${agent.maxIterations}` : <span className="text-[var(--muted)]">—</span>}</Row>
      <Row k="CURRENT TASK">
        {agent.task ? (
          <>
            <span className="font-bold text-[var(--accent)]">{agent.task.id}</span> {agent.task.title}
          </>
        ) : (
          <span className="text-[var(--muted)]">none</span>
        )}
      </Row>
      <Row k="LAST THOUGHT">{agent.thought || <span className="text-[var(--muted)]">nothing yet</span>}</Row>
      <Row k="TESTS">
        {agent.tests ? (
          <span style={{ color: agent.tests.ok ? 'var(--good)' : 'var(--bad)' }}>
            {agent.tests.ok ? '✓ passing' : `✗ ${agent.tests.failed} failing`} <span className="text-[var(--muted)]">· {agent.tests.summary}</span>
          </span>
        ) : (
          <span className="text-[var(--muted)]">not run</span>
        )}
      </Row>
      <Row k={`FILES TOUCHED (${agent.files.length})`}>
        {agent.files.length ? (
          <ul className="m-0 list-none p-0 font-mono text-[12.5px] text-[#b9c4e0]">
            {agent.files.slice(-8).map((f) => (
              <li key={f} className="truncate">
                {f}
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-[var(--muted)]">none</span>
        )}
      </Row>
      <Row k="LOG">
        <div className="rounded-lg bg-[#080b13] p-2 font-mono text-[12px] leading-relaxed text-[#9fb0d4]">
          {agent.log.length ? (
            agent.log.slice(-8).map((l, i) => (
              <div key={i} className="truncate">
                › {l}
              </div>
            ))
          ) : (
            <span className="text-[var(--muted)]">quiet</span>
          )}
        </div>
      </Row>
    </aside>
  )
}
