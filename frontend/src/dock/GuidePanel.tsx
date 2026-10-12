import { useState } from 'react'
import type { GuideView } from '../scenario'

const MARK = { done: { icon: '✓', color: 'var(--good)' }, current: { icon: '▶', color: 'var(--accent)' }, todo: { icon: '○', color: 'var(--muted)' } } as const

/** Priya's guide in the IDE's side panel: the steps of the incident, the current one open. It moves by itself when you run the tests, open a file, post in the channel or submit. */
export function GuidePanel({ guide, initiallyOpen = true }: { guide: GuideView; initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen)
  const finished = guide.current === null
  return (
    <div className="max-h-[38%] shrink-0 overflow-y-auto border-t border-[var(--line)] p-3" aria-label="Priya's guide">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center gap-2 text-left text-[12px] font-bold uppercase tracking-wide text-[var(--muted)] hover:text-white">
        <span>Priya's guide</span>
        <span className="ml-auto font-normal normal-case tabular-nums" aria-label="Guide progress">{finished ? 'all steps done' : `step ${guide.done + 1} of ${guide.steps.length}`}</span>
        <span aria-hidden>{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <ol className="mt-2 space-y-1.5">
          {guide.steps.map((s, i) => (
            <li key={s.id} aria-current={s.state === 'current' ? 'step' : undefined} className="flex gap-2 text-[13px] leading-snug">
              <span className="w-3 shrink-0 pt-[1px] text-center font-bold" style={{ color: MARK[s.state].color }} aria-label={s.state === 'done' ? 'done' : s.state === 'current' ? 'current step' : 'not yet'}>
                {MARK[s.state].icon}
              </span>
              <span className="min-w-0">
                <span className={s.state === 'done' ? 'text-[var(--muted)]' : s.state === 'current' ? 'font-bold text-white' : 'text-[#b9c4e0]'}>
                  {i + 1}. {s.title}
                </span>
                {s.state === 'current' && <span className="mt-0.5 block text-[12.5px] text-[#c9d3ee]">{s.text}</span>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
