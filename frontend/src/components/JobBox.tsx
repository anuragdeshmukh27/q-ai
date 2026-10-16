import { useEffect, useState } from 'react'
import { api } from '../api'
import { MAX_JD_CHARS, clipJd, counter, jobRequest, readerLabel, readerNote, seniorityLabel, type JobAnalysis, type JobRequest, type JobSample } from '../jobs'
import type { ScenarioInfo } from '../scenario'
import { ROLE_LABEL } from './ScenarioPicker'

export interface JobViewProps {
  samples: JobSample[]
  text: string
  sampleId: string
  reading: boolean
  error: string
  analysis: JobAnalysis | null
  scenarios: ScenarioInfo[]
  busy: boolean
  onText: (text: string) => void
  onSample: (s: JobSample) => void
  onRead: () => void
  onStart: (id: string) => void
}

/** Below this score nothing really fits the job: the top row says "closest match", not "best fit". */
export const FIT_FLOOR = 30

const chip = 'rounded-full border border-[var(--line)] px-2 py-[1px]'

/** The "Start from a job description" box: paste a posting (or pick a sample), see how Q read it, and which scenario fits it and why. Presentational: JobBox holds the state. */
export function JobBoxView({ samples, text, sampleId, reading, error, analysis, scenarios, busy, onText, onSample, onRead, onStart }: JobViewProps) {
  const e = analysis?.extraction
  const byId = new Map(scenarios.map((s) => [s.id, s]))
  return (
    <section aria-label="Start from a job description" className="mb-3 rounded-lg border border-[var(--line)] bg-[#0b0e17] p-3">
      <div className="text-[11px] font-semibold tracking-wider text-[var(--muted)]">START FROM A JOB DESCRIPTION</div>
      <div className="mt-1 text-[12.5px] leading-snug text-[var(--muted)]">Paste a posting. Q reads it, picks the scenario that fits the job and adapts the briefing. Your score stays the standard one; a Role fit number is added.</div>
      <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Sample job descriptions">
        {samples.map((s) => (
          <button
            key={s.id}
            onClick={() => onSample(s)}
            aria-pressed={sampleId === s.id}
            title={`Fill the box with the sample “${s.title}”`}
            className={`rounded-full border px-2.5 py-0.5 text-[12px] ${sampleId === s.id ? 'border-[var(--accent)] text-[var(--text)]' : 'border-[var(--line)] text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--text)]'}`}
          >
            {s.title}
          </button>
        ))}
      </div>
      <textarea
        value={text}
        onChange={(ev) => onText(ev.target.value)}
        maxLength={MAX_JD_CHARS}
        rows={5}
        aria-label="Job description"
        placeholder="Paste a job description here (up to 5,000 characters)"
        className="mt-2 h-[108px] w-full resize-y rounded-lg border border-[var(--line)] bg-[#080b13] px-3 py-1.5 text-[13px] leading-snug text-[var(--text)] outline-none focus:border-[var(--accent)]"
      />
      <div className="mt-1 flex items-center gap-2">
        <span className="text-[11.5px] tabular-nums text-[var(--muted)]" aria-label="Characters">{counter(text)}</span>
        <button
          onClick={onRead}
          disabled={reading || busy || !text.trim()}
          className="ml-auto rounded-md border border-[var(--accent)] px-3 py-1 text-[13px] font-bold text-[var(--text)] hover:bg-[#16213f] disabled:opacity-40"
        >
          {reading ? 'Reading…' : 'Read this job description'}
        </button>
      </div>
      {error && <div role="alert" className="mt-2 text-[12.5px] text-[var(--bad)]">{error}</div>}
      {analysis && e && (
        <div className="mt-3 border-t border-[var(--line)] pt-2.5" aria-label="How Q read it">
          <div className="flex flex-wrap items-center gap-1.5 text-[11.5px]">
            <span className={`${chip} font-bold ${e.source === 'model' ? 'border-[var(--good)] text-[var(--good)]' : 'border-[var(--warn)] text-[var(--warn)]'}`} title={readerNote(e)}>Read by: {readerLabel(e)}</span>
            {analysis.job.clipped && <span className={`${chip} text-[var(--warn)]`}>cut at {MAX_JD_CHARS.toLocaleString('en-US')} characters</span>}
          </div>
          <div className="mt-1 text-[12px] leading-snug text-[var(--muted)]">{readerNote(e)}</div>
          <div className="mt-2 text-[13.5px] font-bold leading-snug">{e.role}</div>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[11.5px] text-[var(--muted)]">
            <span className={chip}>{seniorityLabel(e.seniority)}</span>
            <span className={chip}>domain: {e.domain}</span>
            <span className={chip}>{ROLE_LABEL[e.role_family] ?? e.role_family}</span>
          </div>
          {e.skills.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5 text-[11.5px]" aria-label="Skills it asks for">
              {e.skills.map((s) => <span key={s} className="rounded-md bg-[#151a2b] px-1.5 py-[1px] text-[#c9d3ee]">{s}</span>)}
            </div>
          )}
          {e.soft_skills.length > 0 && <div className="mt-1.5 text-[12px] text-[var(--muted)]">Also asks for: {e.soft_skills.join(', ')}</div>}
          <div className="mt-1.5 text-[12px] text-[var(--muted)]">App idea for this domain: {e.app_idea}</div>

          <div className="mt-3 text-[11px] font-semibold tracking-wider text-[var(--muted)]">SCENARIOS RANKED FOR THIS JOB</div>
          <ol className="mt-1.5 flex flex-col gap-2" aria-label="Ranking">
            {analysis.ranking.map((m) => {
              const s = byId.get(m.scenario)
              const best = m.scenario === analysis.recommended
              return (
                <li key={m.scenario} className={`rounded-md border p-2 ${best ? 'border-[var(--good)]' : 'border-[var(--line)]'}`} aria-label={`${m.rank}. ${m.title} ${m.score} of 100`}>
                  <div className="flex items-baseline gap-2">
                    <span className="text-[12px] tabular-nums text-[var(--muted)]">{m.rank}.</span>
                    <span className="text-[13.5px] font-bold leading-snug">{m.title}</span>
                    <span className="ml-auto shrink-0 text-[13px] font-bold tabular-nums">{m.score}/100</span>
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11.5px] text-[var(--muted)]">
                    {best && <span className="rounded border border-[var(--good)] px-1 text-[10.5px] font-bold uppercase text-[var(--good)]">{m.score >= FIT_FLOOR ? 'best fit' : 'closest match'}</span>}
                    {s && <span>You play: {ROLE_LABEL[s.role] ?? s.role}</span>}
                    <span title="role / skills / domain">role {m.parts.role} · skills {m.parts.skills} · domain {m.parts.domain}</span>
                  </div>
                  <div className="mt-1 text-[12px] leading-snug text-[#c9d3ee]">{m.reason}</div>
                  <button
                    onClick={() => onStart(m.scenario)}
                    disabled={busy}
                    title="Starts the incident now with the briefing and the Role fit adapted to this job"
                    className={`mt-2 w-full rounded-md px-3 py-1 text-[13px] font-bold disabled:opacity-40 ${best ? 'bg-[#2f5bd6] text-white hover:bg-[#3b6af0]' : 'border border-[var(--line)] text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--text)]'}`}
                  >
                    {busy ? 'Starting…' : best ? 'Start this scenario for this job' : 'Pick this one instead'}
                  </button>
                </li>
              )
            })}
          </ol>
        </div>
      )}
    </section>
  )
}

interface Props {
  scenarios: ScenarioInfo[]
  busy: boolean
  /** Start `id` for the posting that was read. */
  onStart: (id: string, job: JobRequest) => void
}

export function JobBox({ scenarios, busy, onStart }: Props) {
  const [samples, setSamples] = useState<JobSample[]>([])
  const [text, setText] = useState('')
  const [sampleId, setSampleId] = useState('')
  const [reading, setReading] = useState(false)
  const [error, setError] = useState('')
  const [analysis, setAnalysis] = useState<JobAnalysis | null>(null)
  useEffect(() => {
    let live = true
    api.jdSamples().then((s) => live && setSamples(s)).catch(() => {})
    return () => { live = false }
  }, [])
  const read = async () => {
    setReading(true)
    setError('')
    try {
      setAnalysis(await api.analyzeJd(sampleId ? { sample_id: sampleId } : { text }))
    } catch (e) {
      setAnalysis(null)
      setError(e instanceof Error ? e.message : 'The job description could not be read.')
    } finally {
      setReading(false)
    }
  }
  return (
    <JobBoxView
      samples={samples}
      text={text}
      sampleId={sampleId}
      reading={reading}
      error={error}
      analysis={analysis}
      scenarios={scenarios}
      busy={busy}
      onText={(t) => { setText(clipJd(t)); setSampleId(''); setAnalysis(null) }} // typing changes the posting: the earlier reading no longer belongs to it
      onSample={(s) => { setText(s.text); setSampleId(s.id); setAnalysis(null); setError('') }}
      onRead={() => void read()}
      onStart={(id) => analysis && onStart(id, jobRequest(analysis, text))}
    />
  )
}
