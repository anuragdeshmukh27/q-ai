import type { ScenarioInfo } from '../scenario'

export const ROLE_LABEL: Record<string, string> = { backend: 'Backend engineer', frontend: 'Frontend engineer', database: 'Database engineer' }

interface Props {
  scenarios: ScenarioInfo[]
  busy: boolean
  onStart: (id: string) => void
  /** "Watch a run": a script plays the scenario (variant "strong" or "weak"), nobody types. */
  onWatch?: (id: string, variant: 'strong' | 'weak') => void
}

/** The scenarios of Simulation mode: a finished app with a planted problem and a scripted team, one card each. */
export function ScenarioPicker({ scenarios, busy, onStart, onWatch }: Props) {
  if (scenarios.length === 0) return null
  return (
    <div aria-label="Scenarios">
      <div className="mb-1 text-[11px] font-semibold tracking-wider text-[var(--muted)]">SCENARIOS</div>
      <div className="flex flex-col gap-2">
        {scenarios.map((s) => (
          <div key={s.id} className="rounded-lg border border-[var(--line)] bg-[#0b0e17] p-3">
            <div className="text-[14.5px] font-bold leading-snug">{s.title}</div>
            <div className="mt-1 text-[12.5px] leading-snug text-[var(--muted)]">{s.summary}</div>
            <div className="mt-2 flex flex-wrap gap-1.5 text-[11.5px] text-[var(--muted)]">
              <span className="rounded-full border border-[var(--line)] px-2 py-[1px]">You play: {ROLE_LABEL[s.role] ?? s.role}</span>
              <span className="rounded-full border border-[var(--line)] px-2 py-[1px]">about {s.minutes} min</span>
              {s.level && <span className="rounded-full border border-[var(--line)] px-2 py-[1px]">{s.level}</span>}
              <span className="rounded-full border border-[var(--line)] px-2 py-[1px]">{s.channel}</span>
            </div>
            <button
              onClick={() => onStart(s.id)}
              disabled={busy}
              title="Starts the incident now: the session timer runs and every action you take is logged"
              className="mt-2.5 w-full rounded-md bg-[#2f5bd6] px-3 py-1.5 text-[13.5px] font-bold text-white hover:bg-[#3b6af0] disabled:opacity-40"
            >
              {busy ? 'Starting…' : 'Start the incident'}
            </button>
            {onWatch && (
              <div className="mt-2.5 border-t border-[var(--line)] pt-2" aria-label="Watch a run">
                <div className="text-[11px] font-semibold tracking-wider text-[var(--muted)]">WATCH A RUN · about 3 minutes, nobody types</div>
                <div className="mt-1.5 grid grid-cols-2 gap-2">
                  <button
                    onClick={() => onWatch(s.id, 'strong')}
                    disabled={busy}
                    title="A scripted engineer: runs the tests first, reads the code and the data before editing, keeps the channel informed, adds a regression test and fixes it properly. Scores 100."
                    className="rounded-md border border-[var(--good)] px-2 py-1.5 text-[13px] font-bold text-[var(--good)] hover:bg-[#10281a] disabled:opacity-40"
                  >
                    Strong run
                  </button>
                  <button
                    onClick={() => onWatch(s.id, 'weak')}
                    disabled={busy}
                    title="A scripted engineer: edits first, no update until nudged, a red submit, asks for help. Scores clearly lower; the debrief shows why."
                    className="rounded-md border border-[var(--warn)] px-2 py-1.5 text-[13px] font-bold text-[var(--warn)] hover:bg-[#2a210a] disabled:opacity-40"
                  >
                    Weak run
                  </button>
                </div>
                <div className="mt-1 text-[11.5px] leading-tight text-[var(--muted)]">The real scoring and debrief. Marked demo: it does not count in your attempts.</div>
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="mt-2 text-[11.5px] leading-tight text-[var(--muted)]">Or give the team a goal below and play a role in that build.</div>
    </div>
  )
}
