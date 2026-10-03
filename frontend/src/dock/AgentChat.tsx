import { useEffect, useRef } from 'react'
import type { OfficeModel, Tone } from '../model'
import { Empty } from './Explorer'

const TONE: Record<Tone, string> = { info: '#6ea8ff', good: '#4ade80', bad: '#f87171', warn: '#fbbf24' }

export function AgentChat({ model }: { model: OfficeModel }) {
  const end = useRef<HTMLDivElement>(null)
  const msgs = model.messages
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [msgs.length])
  if (!msgs.length) return <Empty text="Messages between employees (task hand-offs, review comments, bug reports) appear here as they happen." />
  return (
    <div className="h-full overflow-y-auto px-4 py-2">
      {msgs.map((m, i) => (
        <div key={`${m.seq}-${i}`} className="flex gap-3 border-b border-[#161c2d] py-1.5 text-[14px] leading-snug">
          <div className="w-[190px] shrink-0 font-semibold">
            <span style={{ color: TONE[m.tone] }}>{model.name(m.from)}</span> <span className="text-[var(--muted)]">→</span> {model.name(m.to)}
          </div>
          <div className="min-w-0 flex-1 text-[#c9d3ee]">{m.text}</div>
        </div>
      ))}
      <div ref={end} />
    </div>
  )
}
