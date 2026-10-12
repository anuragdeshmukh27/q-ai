import type { ScenarioInfo } from '../scenario'

const ROLE_LABEL: Record<string, string> = { backend: 'Backend engineer', frontend: 'Frontend engineer', database: 'Database engineer' }

interface Props {
  scenarios: ScenarioInfo[]
  busy: boolean
  onStart: (id: string) => void
}

/** The scenarios of Simulation mode: a finished app with a planted problem and a scripted team. One card for now. */
export function ScenarioPicker({ scenarios, busy, onStart }: Props) {
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
          </div>
        ))}
      </div>
      <div className="mt-2 text-[11.5px] leading-tight text-[var(--muted)]">Or give the team a goal below and play a role in that build.</div>
    </div>
  )
}
