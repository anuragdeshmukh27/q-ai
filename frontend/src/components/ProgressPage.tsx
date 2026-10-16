import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { DebriefTab } from '../dock/DebriefTab'
import { OfficeModel } from '../model'
import {
  EXPORT_URL, TREND, canClear, formatAverage, formatDate, linePath, linePoints, reportUrl, resetStep,
  type Progress, type ProgressScenario, type ProgressSkill, type ResetState,
} from '../progress'
import { formatClock, scoreColor, type DebriefReport } from '../scenario'

interface ViewProps {
  data: Progress
  busy?: boolean
  reset: ResetState
  onReset: (action: 'ask' | 'cancel' | 'confirm') => void
  onStart: (scenarioId: string) => void
  onOpenReport: (scenario: string, attempt: number) => void
}

function Heading({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--muted)]">{children}</h2>
}

const card = 'rounded-lg border border-[var(--line)] bg-[#0b0e17]'

/** Score over the attempts of one scenario: a line from the first to the last attempt, 0 at the bottom and full marks at the top. */
export function ScoreLine({ scenario }: { scenario: ProgressScenario }) {
  const w = 280
  const h = 84
  const pts = linePoints(scenario.attempts.map((a) => a.total), scenario.max, w, h)
  return (
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Score over attempts: ${scenario.attempts.map((a) => a.total).join(', ')}`} className="mt-2 w-full">
      <line x1="8" x2={w - 8} y1="8" y2="8" stroke="#222a40" strokeDasharray="3 4" />
      <line x1="8" x2={w - 8} y1={h - 8} y2={h - 8} stroke="#222a40" />
      <text x={w - 8} y="6" textAnchor="end" fontSize="9" fill="#8a93aa">{scenario.max}</text>
      <text x={w - 8} y={h - 10} textAnchor="end" fontSize="9" fill="#8a93aa">0</text>
      {pts.length > 1 && <path d={linePath(pts)} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" />}
      {pts.map((p, i) => (
        <g key={scenario.attempts[i].attempt}>
          <circle cx={p.x} cy={p.y} r="4" fill={scoreColor(scenario.attempts[i].total, scenario.max)} stroke="#0b0e17" strokeWidth="1.5">
            <title>{`Attempt ${scenario.attempts[i].attempt}: ${scenario.attempts[i].total}/${scenario.max}`}</title>
          </circle>
        </g>
      ))}
    </svg>
  )
}

function ScenarioCard({ s, onOpenReport }: { s: ProgressScenario; onOpenReport: ViewProps['onOpenReport'] }) {
  return (
    <section className={`${card} p-3`} aria-label={s.title}>
      <div className="text-[14.5px] font-bold leading-snug">{s.title}</div>
      {s.attempts.length === 0 ? (
        <p className="mt-2 text-[13px] text-[var(--muted)]">Not attempted yet.</p>
      ) : (
        <>
          <div className="mt-1 flex flex-wrap gap-x-4 text-[12.5px] text-[var(--muted)]">
            <span>Best score <b className="tabular-nums text-[var(--text)]">{s.best_score}/{s.max}</b></span>
            <span>Best time <b className="tabular-nums text-[var(--text)]">{formatClock(s.best_time ?? 0)}</b></span>
            <span>{s.count} attempt{s.count === 1 ? '' : 's'}</span>
          </div>
          <ScoreLine scenario={s} />
          <table className="mt-1 w-full text-[12.5px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-[var(--muted)]">
                <th className="py-1 font-semibold">#</th>
                <th className="py-1 font-semibold">Score</th>
                <th className="py-1 font-semibold">Date</th>
                <th className="py-1 text-right font-semibold">Time</th>
              </tr>
            </thead>
            <tbody>
              {s.attempts.map((a) => (
                <tr key={a.attempt} className="border-t border-[var(--line)]">
                  <td className="py-1 tabular-nums">
                    <button onClick={() => onOpenReport(s.id, a.attempt)} title="Open this attempt's report" className="text-[var(--accent)] hover:underline">
                      {a.attempt}
                    </button>
                  </td>
                  <td className="py-1 font-semibold tabular-nums" style={{ color: scoreColor(a.total, a.max) }}>
                    {a.total}/{a.max}
                    {typeof a.role_fit === 'number' && <div className="text-[10.5px] font-normal text-[var(--muted)]" title={`Role fit for ${a.job_role || 'the job description'}: an extra number, the score is ${a.total}`}>role fit {a.role_fit}</div>}
                  </td>
                  <td className="py-1 text-[var(--muted)]">{formatDate(a.date)}</td>
                  <td className="py-1 text-right tabular-nums text-[var(--muted)]">{formatClock(a.elapsed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  )
}

function SkillRow({ k, weakest }: { k: ProgressSkill; weakest: boolean }) {
  const t = TREND[k.trend]
  return (
    <tr className="border-t border-[var(--line)]" aria-label={`${k.name}: latest ${k.latest ?? 'none'}, average ${formatAverage(k.average)}, ${t.label}`}>
      <td className="py-2 pr-3 font-semibold">
        {k.name}
        {weakest && <span className="ml-2 rounded border border-[var(--warn)] px-1.5 py-[1px] text-[10.5px] font-bold uppercase text-[var(--warn)]">weakest</span>}
      </td>
      <td className="py-2 pr-3 tabular-nums">{k.latest === null ? '–' : `${k.latest}/${k.max}`}</td>
      <td className="py-2 pr-3">
        <div className="flex items-center gap-2">
          <span className="w-[44px] tabular-nums">{k.average === null ? '–' : `${formatAverage(k.average)}/${k.max}`}</span>
          <span className="h-[6px] w-[90px] overflow-hidden rounded-full bg-[#232b44]" aria-hidden>
            <span className="block h-full rounded-full" style={{ width: `${k.average === null ? 0 : (k.average / k.max) * 100}%`, background: k.average === null ? '#232b44' : scoreColor(k.average, k.max) }} />
          </span>
        </div>
      </td>
      <td className="py-2 whitespace-nowrap" style={{ color: t.color }} title={t.label}>
        <span aria-hidden>{t.glyph}</span> <span className="text-[12.5px]">{t.label}</span>
      </td>
    </tr>
  )
}

/** The page itself, from the data. The container below loads it; tests render this directly. */
export function ProgressView({ data, busy, reset, onReset, onStart, onOpenReport }: ViewProps) {
  const tried = data.scenarios.filter((s) => s.count > 0).length
  const best = Math.max(0, ...data.scenarios.map((s) => s.best_score ?? 0))
  const w = data.weakest
  const next = data.next_step
  return (
    <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-5 px-5 py-5" aria-label="My progress">
      {data.empty ? (
        <div className={`${card} px-6 py-10 text-center`} aria-label="No attempts yet">
          <div className="text-[18px] font-bold">No attempts yet</div>
          <p className="mx-auto mt-2 max-w-[520px] text-[14px] leading-snug text-[var(--muted)]">
            Your progress is built from the scenarios you finish yourself: start one with <b className="text-[var(--text)]">Start the incident</b>, get your fix accepted and read the debrief. Watching a run
            (Strong run, Weak run) and Demo mode never count here.
          </p>
          <div className="mt-3 text-[13px] text-[var(--muted)]">{data.scenarios.length} scenario{data.scenarios.length === 1 ? '' : 's'} to try:</div>
          <ul className="mt-1 text-[13.5px]">
            {data.scenarios.map((s) => (
              <li key={s.id}>
                <button onClick={() => onStart(s.id)} disabled={busy} className="text-[var(--accent)] hover:underline disabled:opacity-40">{s.title}</button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3 max-[700px]:grid-cols-1" aria-label="Summary">
            {[['Real attempts', String(data.attempts_total)], ['Scenarios tried', `${tried} of ${data.scenarios.length}`], ['Best score', `${best}/${data.scenarios[0]?.max ?? 100}`]].map(([k, v]) => (
              <div key={k} className={`${card} px-4 py-3`}>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--muted)]">{k}</div>
                <div className="text-[26px] font-bold leading-tight tabular-nums">{v}</div>
              </div>
            ))}
          </div>

          <div>
            <Heading>Scenarios</Heading>
            <div className="grid grid-cols-3 gap-3 max-[1000px]:grid-cols-2 max-[700px]:grid-cols-1">
              {data.scenarios.map((s) => <ScenarioCard key={s.id} s={s} onOpenReport={onOpenReport} />)}
            </div>
          </div>

          <div>
            <Heading>Skills across all scenarios</Heading>
            <div className={`${card} overflow-x-auto px-4 py-1`}>
              <table className="w-full text-[13.5px]" aria-label="Skills">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-[var(--muted)]">
                    <th className="py-2 font-semibold">Skill</th>
                    <th className="py-2 font-semibold">Latest</th>
                    <th className="py-2 font-semibold">Average</th>
                    <th className="py-2 font-semibold">Trend</th>
                  </tr>
                </thead>
                <tbody>{data.skills.map((k) => <SkillRow key={k.id} k={k} weakest={w?.skill === k.id} />)}</tbody>
              </table>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 max-[900px]:grid-cols-1">
            <section aria-label="Weakest skill">
              <Heading>Weakest skill</Heading>
              {w ? (
                <div className={`${card} p-4`} style={{ borderColor: 'var(--warn)' }}>
                  <div className="text-[16px] font-bold">{w.name} <span className="text-[13px] font-normal text-[var(--muted)]">average {formatAverage(w.average)}/{w.max} · latest {w.latest}/{w.max}</span></div>
                  {w.gap ? (
                    <button
                      onClick={() => onOpenReport(w.gap!.scenario, w.gap!.attempt)}
                      title="Open that report"
                      aria-label={`Open the report of ${w.gap.title}, attempt ${w.gap.attempt}`}
                      className="mt-2 block w-full rounded-md border border-[var(--line)] bg-[#10141f] p-3 text-left hover:border-[var(--accent)]"
                    >
                      <span className="block text-[11.5px] text-[var(--muted)]">
                        Most recent gap · {w.gap.title}, attempt {w.gap.attempt} · <span className="font-mono tabular-nums text-[var(--accent)]">{w.gap.clock}</span> · {w.gap.source}
                      </span>
                      <span className="mt-1 block italic text-[#e8ebf4]">“{w.gap.quote}”</span>
                      <span className="mt-1 block text-[13px] text-[#b9c4e0]">{w.gap.note}</span>
                      {w.gap.advice && <span className="mt-1 block text-[13px] text-[var(--accent)]">Next attempt: {w.gap.advice}</span>}
                      <span className="mt-2 block text-[12px] font-semibold text-[var(--accent)]">Open that report →</span>
                    </button>
                  ) : (
                    <p className="mt-2 text-[13px] text-[var(--muted)]">{w.reason}</p>
                  )}
                </div>
              ) : (
                <div className={`${card} p-4 text-[13.5px] text-[var(--muted)]`}>None: every attempt scored full marks on every skill.</div>
              )}
            </section>

            <section aria-label="Suggested next step">
              <Heading>Suggested next step</Heading>
              {next && (
                <div className={`${card} flex h-[calc(100%-1.75rem)] flex-col p-4`}>
                  <p className="text-[14px] leading-snug">{next.reason}</p>
                  <button
                    onClick={() => onStart(next.scenario)}
                    disabled={busy}
                    className="mt-auto self-start rounded-md bg-[#2f5bd6] px-4 py-2 text-[13.5px] font-bold text-white hover:bg-[#3b6af0] disabled:opacity-40"
                    style={{ marginTop: 12 }}
                  >
                    {busy ? 'Starting…' : next.kind === 'new' ? 'Start this scenario' : next.kind === 'retry' ? 'Try it again' : 'Start it again'}
                  </button>
                </div>
              )}
            </section>
          </div>
        </>
      )}

      <div className="flex flex-wrap items-center gap-3 border-t border-[var(--line)] pt-4" aria-label="Your data">
        {!data.empty && (
          <>
            <span className="text-[13px] font-semibold">Download my progress</span>
            <a href={EXPORT_URL('md')} download="q-progress.md" className="rounded-md border border-[var(--line)] px-3 py-1.5 text-[13px] font-semibold hover:bg-[#1a2033]">Markdown</a>
            <a href={EXPORT_URL('json')} download="q-progress.json" className="rounded-md border border-[var(--line)] px-3 py-1.5 text-[13px] font-semibold hover:bg-[#1a2033]">JSON</a>
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          {reset === 'idle' ? (
            !data.empty && <button onClick={() => onReset('ask')} className="rounded-md border border-[var(--line)] px-3 py-1.5 text-[13px] font-semibold text-[var(--muted)] hover:border-[var(--bad)] hover:text-[var(--bad)]">Reset progress</button>
          ) : (
            <div role="alertdialog" aria-label="Confirm reset" className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--bad)] bg-[#2a1013] px-3 py-2 text-[13px]">
              <span>Clear your real attempt history? Demo runs and recordings are not touched. This cannot be undone.</span>
              <button onClick={() => onReset('confirm')} disabled={!canClear(reset)} className="rounded-md bg-[#b4272b] px-3 py-1 font-bold text-white hover:bg-[#cf2f34] disabled:opacity-50">{reset === 'busy' ? 'Clearing…' : 'Yes, clear it'}</button>
              <button onClick={() => onReset('cancel')} disabled={reset === 'busy'} className="rounded-md border border-[var(--line)] px-3 py-1 font-semibold hover:bg-[#1a2033] disabled:opacity-50">Cancel</button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

interface PageProps {
  onClose: () => void
  /** Start a scenario (the picker's Start): the page closes after it. */
  onStart: (scenarioId: string) => Promise<void> | void
  busy: boolean
  onError: (e: unknown) => void
}

/** "My progress": full-screen page over the office. Loads /api/progress each time it opens; a report opens inside it with the Debrief layout, read only. */
export function ProgressPage({ onClose, onStart, busy, onError }: PageProps) {
  const [data, setData] = useState<Progress | null>(null)
  const [reset, setReset] = useState<ResetState>('idle')
  const [report, setReport] = useState<DebriefReport | null>(null)
  const load = useCallback(() => api.progress().then(setData).catch(onError), [onError])
  useEffect(() => {
    void load()
  }, [load])

  const openReport = useCallback(
    (scenario: string, attempt: number) => {
      api.progressReport(scenario, attempt).then(setReport).catch(onError)
    },
    [onError],
  )
  const viewModel = useMemo(() => {
    if (!report) return null
    const m = new OfficeModel()
    // the judges' names come from the report (this model has no team), so "architect" reads Aarav
    m.setRoster([...new Map(report.criteria.map((c) => [c.judge, c])).values()].map((c, i) => ({ id: c.judge, name: c.judge_name, role: c.judge, desk: [i, 0] as [number, number], sprite: { palette: 'teal', accessory: 'none' } })))
    m.debrief = { phase: 'done', attempt: report.attempt, judges: [], report }
    return m
  }, [report])

  const onReset = (action: 'ask' | 'cancel' | 'confirm') => {
    const next = resetStep(reset, action)
    setReset(next)
    if (action === 'confirm' && canClear(reset)) {
      api.resetProgress().then(() => load()).catch(onError).finally(() => setReset(resetStep(next, 'done')))
    }
  }
  const start = async (id: string) => {
    await onStart(id)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-[var(--bg)]" role="dialog" aria-modal="true" aria-label="My progress page">
      <header className="flex shrink-0 items-center gap-3 border-b border-[var(--line)] bg-[var(--panel)] px-5 py-3">
        {report && <button onClick={() => setReport(null)} className="rounded-md border border-[var(--line)] px-3 py-1.5 text-[13px] font-semibold hover:bg-[#1a2033]">← My progress</button>}
        <h1 className="text-[17px] font-bold">{report ? `${report.title} · attempt ${report.attempt}` : 'My progress'}</h1>
        {!report && <span className="text-[12.5px] text-[var(--muted)]">real attempts only · demo runs never count</span>}
        <button onClick={onClose} aria-label="Close my progress" className="ml-auto rounded-md px-3 py-1.5 text-[13px] font-semibold text-[var(--muted)] hover:bg-[#1a2033] hover:text-white">Close ✕</button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {report && viewModel ? (
          <div className="h-full" style={{ minHeight: 480 }}>
            <DebriefTab model={viewModel} projectId={null} onTryAgain={() => {}} readOnly reportLink={reportUrl(report.scenario, report.attempt, 'md')} />
          </div>
        ) : data ? (
          <ProgressView data={data} busy={busy} reset={reset} onReset={onReset} onStart={(id) => void start(id)} onOpenReport={openReport} />
        ) : (
          <div className="px-6 py-10 text-center text-[14px] text-[var(--muted)]">Loading your progress…</div>
        )}
      </div>
    </div>
  )
}
