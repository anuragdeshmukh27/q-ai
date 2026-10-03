import type { ReactNode } from 'react'
import { STATE_COLOR, STATE_LABEL } from '../office/palette'
import type { AgentView } from '../model'

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-[11px] font-semibold tracking-wider text-[var(--muted)]">{k}</div>
      <div className="mt-0.5 text-[14px] leading-snug">{children}</div>
    </div>
  )
}

export function Inspector({ agent, onClose }: { agent: AgentView; onClose: () => void }) {
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

      <Row k="MODEL">{agent.model ?? <span className="text-[var(--muted)]">not used yet</span>}</Row>
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
