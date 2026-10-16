import { useState } from 'react'
import type { OfficeModel } from '../model'
import { ROLE_LABEL } from './ScenarioPicker'

interface Props {
  model: OfficeModel
  replay: boolean
  projectId: string | null
  /** Set when the run is over: the way back to the scenario picker. */
  onBack?: () => void
  onSubmit: (task: string) => Promise<void>
  onCopyPath: (path: string) => void
}

function Heading({ children }: { children: string }) {
  return <div className="mb-1 text-[11px] font-semibold tracking-wider text-[var(--muted)]">{children}</div>
}

/** The left panel while a scenario runs (a real attempt or a script playing it): the scenario, the task with Submit, Priya's progress and the hints used.
 *  A normal build keeps the goal column (LeftPanel); this replaces it for the length of the incident. */
export function ScenarioPanel({ model, replay, projectId, onBack, onSubmit, onCopyPath }: Props) {
  const [submitting, setSubmitting] = useState<string | null>(null)
  const s = model.scenario
  if (!s) return null
  const task = model.tasks.find((t) => t.assignee === 'human') ?? model.tasks.find((t) => t.owner === s.role)
  const script = !!model.autoplay // a script plays this run: its Submit is the script's
  const ended = !!onBack
  const yourTurn = !!task && task.assignee === 'human' && task.status === 'running' && !replay && !script && !ended
  const guide = model.guide
  const at = guide ? guide.steps.findIndex((x) => x.id === guide.current) + 1 : 0
  const current = guide?.steps.find((x) => x.id === guide.current)
  const submit = async (id: string) => {
    setSubmitting(id)
    try {
      await onSubmit(id)
    } finally {
      setSubmitting(null)
    }
  }
  return (
    <aside aria-label="Scenario" className="flex w-[318px] shrink-0 flex-col gap-3 overflow-y-auto border-r border-[var(--line)] bg-[var(--panel)] p-3">
      <div>
        <Heading>SCENARIO</Heading>
        <div className="rounded-lg border border-[var(--line)] bg-[#0b0e17] p-3">
          <div className="flex items-start gap-2">
            <div className="text-[14.5px] font-bold leading-snug">{s.title}</div>
            {s.kind === 'demo' && <span className="ml-auto shrink-0 rounded border border-[var(--warn)] px-1 text-[10.5px] font-bold uppercase text-[var(--warn)]" title="A script plays this run: it is not one of your attempts">demo{s.variant ? ` · ${s.variant}` : ''}</span>}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5 text-[11.5px] text-[var(--muted)]">
            <span className="rounded-full border border-[var(--line)] px-2 py-[1px]">You play: {ROLE_LABEL[s.role] ?? s.role}</span>
            <span className="rounded-full border border-[var(--line)] px-2 py-[1px]">time box {s.minutes} min</span>
            <span className="rounded-full border border-[var(--line)] px-2 py-[1px]">{s.channelName}</span>
            {s.attempt > 0 && s.kind !== 'demo' && <span className="rounded-full border border-[var(--line)] px-2 py-[1px]">attempt {s.attempt}</span>}
          </div>
        </div>
      </div>

      <div>
        <Heading>YOUR TASK</Heading>
        {!task ? (
          <div className="text-[13px] text-[var(--muted)]">Your task appears when the incident starts.</div>
        ) : (
          <div className="rounded-md border border-[var(--line)] bg-[#0b0e17] px-2.5 py-1.5 text-[13px]">
            <div className="flex items-center gap-2">
              <span className="font-bold text-[var(--accent)]">{task.id}</span>
              <span className="truncate" title={task.title}>{task.title}</span>
              <span className="ml-auto shrink-0 text-[11px] font-bold" style={{ color: yourTurn ? '#fbbf24' : ({ done: '#4ade80', running: '#6ea8ff', failed: '#f87171' }[task.status] ?? '#8a93aa') }}>
                {yourTurn ? 'YOUR TURN' : task.status.toUpperCase()}
              </span>
            </div>
            {yourTurn && (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <button
                  onClick={() => void submit(task.id)}
                  disabled={submitting !== null}
                  title="Run the tests in your folder; when they pass the Reviewer reads your change and the Integrator merges it"
                  className="rounded-md border border-[var(--accent)] px-2.5 py-0.5 text-[12px] font-bold text-[var(--text)] disabled:opacity-40"
                >
                  {submitting === task.id ? 'Checking…' : 'Submit'}
                </button>
                {task.worktree && (
                  <button onClick={() => onCopyPath(task.worktree!)} title={task.worktree} className="rounded-md border border-[var(--line)] px-2.5 py-0.5 text-[12px] text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--text)]">
                    Copy folder path
                  </button>
                )}
                {task.doc && projectId && (
                  <a href={`/api/projects/${projectId}/tasks/${task.id}/doc`} target="_blank" rel="noreferrer" className="rounded-md border border-[var(--line)] px-2.5 py-0.5 text-[12px] text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--text)]">
                    Task document
                  </a>
                )}
              </div>
            )}
            {script && <div className="mt-1 text-[11.5px] leading-tight text-[var(--muted)]">A script plays this run: it presses Submit itself.</div>}
          </div>
        )}
      </div>

      {s.job && (
        <div aria-label="Why this scenario fits this job">
          <Heading>WHY THIS SCENARIO FITS THIS JOB</Heading>
          <div className="rounded-md border border-[var(--line)] bg-[#0b0e17] px-2.5 py-2 text-[13px] leading-snug">
            <div className="text-[12px] text-[var(--muted)]">{s.job.role} · {s.job.domain}</div>
            <p className="mt-1 text-[#c9d3ee]">{s.job.briefing.text}</p>
            <div className="mt-1 text-[11px] text-[var(--muted)]" title={s.job.briefing.reason || undefined}>
              {s.job.briefing.source === 'model' ? 'Wording by the local model, checked against the job description and the scenario.' : 'Template wording, built from the job description and the scenario.'}
            </div>
            {s.job.keySkills.length > 0 && (
              <div className="mt-2" aria-label="Key skills of the job">
                <div className="text-[11px] font-semibold tracking-wider text-[var(--muted)]">KEY SKILLS OF THE JOB</div>
                <div className="mt-1 flex flex-wrap gap-1.5 text-[11.5px]">
                  {s.job.keySkills.map((k) => <span key={k} className="rounded-md bg-[#151a2b] px-1.5 py-[1px] text-[#c9d3ee]">{k}</span>)}
                </div>
              </div>
            )}
            <div className="mt-2 text-[11.5px] leading-snug text-[var(--muted)]">Your score stays the standard 0 to 100. The debrief adds a Role fit number, weighted by this job.</div>
          </div>
        </div>
      )}

      <div>
        <Heading>PRIYA'S GUIDE</Heading>
        <div className="rounded-md border border-[var(--line)] bg-[#0b0e17] px-2.5 py-1.5 text-[13px]" aria-label="Guide progress">
          {!guide || guide.steps.length === 0 ? (
            <span className="text-[var(--muted)]">The guide starts with the incident.</span>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <span className="font-bold">{guide.current === null ? 'All steps done' : `Step ${at} of ${guide.steps.length}`}</span>
                <span className="ml-auto tabular-nums text-[12px] text-[var(--muted)]">{guide.done} of {guide.steps.length} done</span>
              </div>
              <div className="mt-1 h-[5px] overflow-hidden rounded-full bg-[#1a2033]" role="progressbar" aria-label="Guide steps done" aria-valuenow={guide.done} aria-valuemin={0} aria-valuemax={guide.steps.length}>
                <div className="h-full rounded-full bg-[var(--good)] transition-all duration-500" style={{ width: `${Math.round((guide.done / guide.steps.length) * 100)}%` }} />
              </div>
              {current && <div className="mt-1.5 text-[12.5px] leading-snug text-[#c9d3ee]">{current.title}</div>}
            </>
          )}
        </div>
        <div className="mt-2 text-[12.5px] text-[var(--muted)]" title="Every answer a teammate gives to a question of yours, and every pointer they volunteer, counts as a hint and is logged">
          Hints used: <span className="font-bold tabular-nums" style={{ color: model.hints ? 'var(--warn)' : 'var(--text)' }}>{model.hints}</span>
        </div>
      </div>

      {ended && (
        <div>
          <div className="mb-2 text-[12.5px] leading-snug text-[var(--muted)]">The incident is over. The debrief is in the dock below.</div>
          <button onClick={onBack} className="h-9 w-full rounded-lg border border-[var(--accent)] text-[13.5px] font-bold text-[var(--text)] hover:bg-[#16213f]">
            Back to the scenarios
          </button>
        </div>
      )}
    </aside>
  )
}
