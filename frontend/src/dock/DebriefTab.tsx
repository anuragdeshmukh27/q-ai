import { useState } from 'react'
import type { OfficeModel } from '../model'
import { coachLabel, deltaLabel, eventDetail, formatClock, rowsOf, scoreColor, wordingLabel, type DebriefReport, type ReportRow } from '../scenario'

const DOT: Record<string, string> = { architect: '#818cf8', planner: '#2dd4bf', backend: '#4ade80', frontend: '#f472b6', database: '#fb923c', integrator: '#94a3b8', qa: '#c084fc', reviewer: '#f87171' }

interface Props {
  model: OfficeModel
  projectId: string | null
  /** Start the scenario again: the next attempt. */
  onTryAgain: (scenarioId: string) => void | Promise<void>
  busy?: boolean
  /** The row whose entry is open when the tab first shows (tests; a click opens one). */
  initiallyOpen?: string
}

/** The debrief of an attempt: the total and the score of every criterion with its judge, the evidence rows (each quotes a moment of your session), the fairness checks and what to
 *  focus on next time. A timestamp opens that entry of the session log. */
export function DebriefTab({ model, projectId, onTryAgain, busy, initiallyOpen }: Props) {
  const d = model.debrief
  const report = d?.report ?? null
  const [open, setOpen] = useState<string | null>(initiallyOpen ?? null)
  if (!d || !report) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-[14px] text-[var(--muted)]" aria-label="Debrief">
        {d?.phase === 'meeting' ? 'The team is in the meeting room: Vikram is re-running the whole suite on main, then each judge gives their score.' : d?.phase === 'failed' ? 'The debrief could not be completed. Your session is still in the log.' : 'The debrief starts when your fix has been accepted.'}
      </div>
    )
  }
  return (
    <div className="grid h-full min-h-0 grid-cols-[330px_minmax(0,1fr)_340px] max-[1100px]:grid-cols-[280px_minmax(0,1fr)] max-[1100px]:overflow-y-auto" aria-label="Debrief">
      <Scores report={report} model={model} />
      <Evidence report={report} model={model} open={open} onOpen={(id) => setOpen(open === id ? null : id)} />
      <Side report={report} projectId={projectId} onTryAgain={onTryAgain} busy={!!busy} />
    </div>
  )
}

function Heading({ children }: { children: React.ReactNode }) {
  return <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--muted)]">{children}</div>
}

function Scores({ report, model }: { report: DebriefReport; model: OfficeModel }) {
  const delta = deltaLabel(report)
  const top = Math.max(report.max, ...report.attempts.map((a) => a.total))
  return (
    <div className="min-h-0 overflow-y-auto border-r border-[var(--line)] p-4" aria-label="Scores">
      <div className="flex items-baseline gap-1">
        <span className="text-[56px] font-bold leading-none tabular-nums" aria-label={`Total ${report.total} out of ${report.max}`}>{report.total}</span>
        <span className="text-[20px] text-[var(--muted)]">/{report.max}</span>
        {delta && <span className="ml-3 text-[13.5px] font-bold" style={{ color: delta.startsWith('+') ? 'var(--good)' : delta.startsWith('−') ? 'var(--bad)' : 'var(--muted)' }}>{delta}</span>}
      </div>
      <div className="mt-1 text-[12.5px] text-[var(--muted)]">
        {report.kind === 'demo' ? (
          <>
            <span className="mr-1.5 rounded border border-[var(--warn)] px-1.5 py-[1px] text-[11px] font-bold uppercase text-[var(--warn)]" title="An autoplay run: a script played it. It is not one of your attempts.">demo · {report.variant || 'autoplay'} run</span>
            {formatMinutes(report.elapsed)} on the clock
          </>
        ) : (
          <>attempt {report.attempt} · {formatMinutes(report.elapsed)} on the clock</>
        )}
      </div>
      <div className="mt-4">
        <Heading>Rubric (0 to 4 each)</Heading>
        <ul className="space-y-2.5">
          {report.criteria.map((c) => (
            <li key={c.id} aria-label={`${c.name} ${c.score} of ${c.max}`}>
              <div className="flex items-baseline justify-between text-[14px]">
                <span className="font-semibold">{c.name}</span>
                <span className="font-bold tabular-nums">{c.score}/{c.max}</span>
              </div>
              <div className="mt-1 flex gap-1" aria-hidden>
                {Array.from({ length: c.max }, (_, i) => (
                  <span key={i} className="h-[6px] flex-1 rounded-full" style={{ background: i < c.score ? scoreColor(c.score, c.max) : '#232b44' }} />
                ))}
              </div>
              <div className="mt-1 flex items-center justify-end gap-1.5 text-[12.5px] text-[var(--muted)]">
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: DOT[c.judge] ?? '#94a3b8' }} />
                {model.name(c.judge) || c.judge_name}
              </div>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-4">
        <Heading>Attempts</Heading>
        <div className="flex items-end gap-2" aria-label="Attempt history">
          {report.attempts.map((a) => (
            <div key={a.attempt} className="flex w-[54px] flex-col items-center gap-1" aria-label={`${a.kind === 'demo' ? 'Demo' : 'Attempt'} ${a.attempt}: ${a.total}`}>
              <div className="flex h-[72px] w-full items-end rounded-md bg-[#151a2b]">
                <div className="w-full rounded-md" style={{ height: `${Math.max(4, (a.total / top) * 100)}%`, background: a.attempt === report.attempt ? 'var(--accent)' : '#2f3a5c' }} />
              </div>
              <div className="text-[11.5px] tabular-nums text-[var(--muted)]">{a.kind === 'demo' ? 'demo ' : ''}#{a.attempt} · {a.total}</div>
            </div>
          ))}
          <div className="ml-1 pb-5 text-[12px] leading-tight text-[var(--muted)]">Same rubric every attempt</div>
        </div>
      </div>
    </div>
  )
}

function formatMinutes(seconds: number): string {
  const s = Math.round(seconds)
  return s >= 60 ? `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s` : `${s} s`
}

function Evidence({ report, model, open, onOpen }: { report: DebriefReport; model: OfficeModel; open: string | null; onOpen: (rowId: string) => void }) {
  return (
    <div className="min-h-0 overflow-y-auto px-4 py-3" aria-label="Evidence">
      <div className="mb-1 flex items-baseline gap-2">
        <h2 className="text-[16px] font-bold">Debrief: {report.title}</h2>
        <span className="text-[12.5px] text-[var(--muted)]">every point quotes a timestamped moment from your session</span>
        <span className="ml-auto font-mono text-[11.5px] text-[var(--muted)]">{report.files.md}</span>
      </div>
      <div className="mb-2 mt-2 rounded-lg border border-[var(--line)] bg-[#0b0e17] px-3 py-2" aria-label="Coach">
        <div className="mb-0.5 text-[10.5px] font-bold uppercase tracking-wide text-[var(--accent)]" title={report.coach.source === 'model' ? 'Written by the 7b model from the points below; every time, number and quote in it was checked against them' : 'Built from the points below, without a model'}>{coachLabel(report.coach)}</div>
        <p className="text-[13.5px] leading-snug text-[#dfe5f5]">{report.coach.text}</p>
      </div>
      {report.criteria.map((c) => (
        <section key={c.id} className="border-t border-[var(--line)] py-2.5" aria-label={c.name}>
          <h3 className="text-[14px] font-bold">
            {c.name} <span className="font-normal tabular-nums text-[var(--muted)]">{c.score}/{c.max}</span>
            <span className="ml-2 text-[12px] font-normal text-[var(--muted)]" title={c.descriptor}>{model.name(c.judge) || c.judge_name}: {c.summary}</span>
          </h3>
          <ul className="mt-1.5 space-y-2">
            {rowsOf(report, c.id).map((r) => (
              <Row key={r.id} row={r} report={report} model={model} open={open === r.id} onOpen={() => onOpen(r.id)} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

function Row({ row, report, model, open, onOpen }: { row: ReportRow; report: DebriefReport; model: OfficeModel; open: boolean; onOpen: () => void }) {
  const strength = row.kind === 'strength'
  return (
    <li className="grid grid-cols-[84px_132px_minmax(0,1fr)_74px] gap-x-3 text-[13.5px] leading-snug" aria-label={`${row.kind} ${row.event}`}>
      <span className="mt-0.5 h-fit w-fit rounded px-1.5 py-[1px] text-[10.5px] font-bold uppercase tracking-wide" style={{ background: strength ? '#12301f' : '#33280d', color: strength ? 'var(--good)' : 'var(--warn)' }}>
        {row.kind}
      </span>
      <div className="min-w-0">
        <button onClick={onOpen} aria-expanded={open} title={`Show the log entry ${row.event}`} className="font-mono text-[12.5px] tabular-nums text-[var(--accent)] hover:underline">
          ▸ {formatClock(row.t)}
        </button>
        <div className="truncate text-[11.5px] text-[var(--muted)]">{row.source}</div>
      </div>
      <div className="min-w-0">
        <div className="italic text-[#e8ebf4]">“{row.quote}”</div>
        <div className="text-[#b9c4e0]">{row.note}</div>
        {row.advice && <div className="mt-0.5 text-[var(--accent)]">Next attempt: {row.advice}</div>}
      </div>
      <span className="mt-0.5 text-right text-[12px] leading-tight">
        <span className="block font-semibold text-[var(--good)]" title="The quote was found in this entry of the session log">{row.verified ? '✓ verified' : ''}</span>
        <span className="block text-[10.5px] uppercase tracking-wide text-[var(--muted)]" title="The sentence comes from the rule that scored this point; the 7b does not write the points">{wordingLabel(row)}</span>
      </span>
      {open && (
        <dl className="col-span-4 mt-1.5 grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-0.5 rounded-lg border border-[var(--line)] bg-[#0b0e17] px-3 py-2 text-[12.5px]" aria-label={`Log entry ${row.event}`}>
          {eventDetail(report, row.event, (id) => model.name(id) || id).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="capitalize text-[var(--muted)]">{k}</dt>
              <dd className="break-words text-[#c9d3ee]">{v}</dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  )
}

function Side({ report, projectId, onTryAgain, busy }: { report: DebriefReport; projectId: string | null; onTryAgain: Props['onTryAgain']; busy: boolean }) {
  const f = report.fairness
  const checks: [boolean, string, string][] = [
    [f.quoted === f.points, 'Every point quotes a moment', `${f.quoted}/${f.points}`],
    [f.matched === f.points, 'Quotes matched to the event log', `${f.matched}/${f.points}`],
    [true, f.dropped.length === 1 ? 'Unbacked claim dropped' : 'Unbacked claims dropped', String(f.dropped.length)],
    [!!f.tests_rerun?.ok, 'Tests re-run, not guessed', f.tests_rerun ? `${f.tests_rerun.passed}/${f.tests_rerun.total}` : 'not run'],
    [true, 'Same rubric for every attempt', f.rubric],
  ]
  return (
    <div className="flex min-h-0 flex-col overflow-y-auto border-l border-[var(--line)] p-4 max-[1100px]:col-span-2 max-[1100px]:border-l-0 max-[1100px]:border-t" aria-label="Fairness checks">
      <Heading>Fairness checks</Heading>
      <ul className="space-y-1.5 text-[13.5px]">
        {checks.map(([ok, label, value]) => (
          <li key={label} className="flex items-baseline gap-2">
            <span style={{ color: ok ? 'var(--good)' : 'var(--warn)' }} aria-hidden>{ok ? '✓' : '!'}</span>
            <span className="flex-1">{label}</span>
            <span className="tabular-nums text-[var(--muted)]">{value}</span>
          </li>
        ))}
      </ul>
      {f.voices.reason && <div className="mt-1 text-[12px] leading-snug text-[var(--muted)]">The 7b was not used for the judges and the coach: {f.voices.reason}.</div>}
      {f.dropped.length > 0 && (
        <div className="mt-3 rounded-lg border border-[var(--line)] bg-[#0b0e17] px-3 py-2 text-[12.5px] leading-snug text-[#b9c4e0]">
          {f.dropped.map((d, i) => (
            <p key={i} className={i ? 'mt-1.5' : ''}>
              <b className="text-[var(--text)]">Dropped:</b> “{d.text}” {d.reason}.
            </p>
          ))}
        </div>
      )}
      {f.ai_rejected.length > 0 && (
        <details className="mt-3 rounded-lg border border-[var(--line)] bg-[#0b0e17] px-3 py-2 text-[12.5px] leading-snug text-[#b9c4e0]" aria-label="AI lines not used">
          <summary className="cursor-pointer font-semibold text-[var(--muted)] hover:text-white" title="Texts the 7b wrote that said something the report does not back; the template text is shown instead. They do not touch your score or your evidence.">
            AI lines not used ({f.ai_rejected.length})
          </summary>
          {f.ai_rejected.map((d, i) => (
            <p key={i} className="mt-1.5">
              <b className="text-[var(--text)]">{d.finding === 'coach' ? 'Coach' : (report.criteria.find((c) => c.id === d.finding)?.name ?? d.finding)}:</b> “{d.text}” <span className="text-[var(--muted)]">{d.reason}.</span>
            </p>
          ))}
        </details>
      )}
      <div className="mt-4">
        <Heading>Focus for your next attempt</Heading>
        <ol className="list-decimal space-y-1 pl-5 text-[13.5px] leading-snug">
          {report.focus.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ol>
      </div>
      <div className="mt-auto flex flex-col gap-2 pt-4">
        {report.kind !== 'demo' && <button onClick={() => void onTryAgain(report.scenario)} disabled={busy} className="rounded-lg bg-[#2f5bd6] px-3 py-2.5 text-[14px] font-bold text-white hover:bg-[#3b6af0] disabled:opacity-40">
          ↻ Try again (attempt {Math.max(...report.attempts.map((a) => a.attempt)) + 1})
        </button>}
        <a
          href={projectId ? `/api/projects/${projectId}/report?format=md` : undefined}
          target="_blank"
          rel="noreferrer"
          className="rounded-lg border border-[var(--line)] px-3 py-2.5 text-center text-[14px] font-semibold text-[var(--text)] hover:bg-[#1a2033]"
        >
          Open report file
        </a>
      </div>
    </div>
  )
}
