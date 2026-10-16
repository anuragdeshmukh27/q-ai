import { bannerLine, variantLabel, type AutoplayState } from '../autoplay'

interface Props {
  auto: AutoplayState
  /** A recording of an autoplay run is playing: it cannot be stopped or sped up from here (the Demo mode speed switch does that). */
  replay?: boolean
  onStop?: () => void
  onSpeed?: (speed: number) => void
}

/** The strip under the top bar for as long as a script plays the scenario: what it is, which step, how fast, and the Stop button. */
export function AutoplayBanner({ auto, replay = false, onStop, onSpeed }: Props) {
  const ended = !auto.active
  const pct = auto.total ? Math.round((100 * Math.min(auto.step, auto.total)) / auto.total) : 0
  const tone = auto.ended === 'error' ? 'var(--bad)' : 'var(--warn)'
  return (
    <div role="status" aria-label="Autoplay demo" className="flex shrink-0 items-center gap-3 border-b px-4 py-1.5 text-[13px]" style={{ borderColor: tone, background: auto.ended === 'error' ? '#2a1013' : '#241d0a' }}>
      <span className="rounded px-2 py-[1px] text-[11.5px] font-bold uppercase tracking-wide text-[#0b0d12]" style={{ background: tone }}>
        {replay ? 'Recorded autoplay demo' : 'Autoplay demo'}
      </span>
      <span className="min-w-0 truncate text-[var(--text)]">
        {ended
          ? auto.ended === 'error'
            ? `The scripted run failed: ${auto.error || 'an error'}`
            : auto.ended === 'stopped'
              ? `${variantLabel(auto.variant)} · stopped at step ${Math.min(auto.step, auto.total)} of ${auto.total}`
              : `${bannerLine({ ...auto, step: auto.total })} · finished`
          : bannerLine(auto)}
      </span>
      <div className="h-[6px] w-[140px] shrink-0 overflow-hidden rounded-full bg-[#3a3012]" aria-label={`Step ${auto.step} of ${auto.total}`}>
        <div className="h-full rounded-full" style={{ width: `${ended && auto.ended === 'done' ? 100 : pct}%`, background: tone }} />
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-3">
        {!replay && !ended && onSpeed && (
          <div className="seg" role="group" aria-label="Autoplay speed">
            {[1, 2].map((s) => (
              <button key={s} aria-pressed={auto.speed === s} onClick={() => onSpeed(s)}>
                {s}×
              </button>
            ))}
          </div>
        )}
        {!replay && !ended && onStop && (
          <button onClick={onStop} className="rounded-md border border-[var(--bad)] px-3 py-1 text-[12.5px] font-bold text-[var(--bad)] hover:bg-[#2a1013]" title="End the scripted run now; nothing of it is kept">
            ■ Stop
          </button>
        )}
      </div>
    </div>
  )
}
