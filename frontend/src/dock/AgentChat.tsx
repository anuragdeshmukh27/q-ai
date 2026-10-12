import { useEffect, useRef, useState } from 'react'
import type { OfficeModel, Tone } from '../model'
import { formatClock, recipients, SOURCE_LABEL } from '../scenario'
import { Empty } from './Explorer'

const TONE: Record<Tone, string> = { info: '#6ea8ff', good: '#4ade80', bad: '#f87171', warn: '#fbbf24' }

interface Props {
  model: OfficeModel
  /** Post in the incident channel (a scenario session). `to` is the teammate picked in the box, if any. */
  onPost?: (text: string, to?: string) => Promise<void>
  replay?: boolean
}

export function AgentChat({ model, onPost, replay }: Props) {
  const [view, setView] = useState<'channel' | 'all'>('channel')
  if (!model.scenario) return <Traffic model={model} />
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b border-[var(--line)] px-3 py-1.5">
        <div className="seg" role="group" aria-label="Chat view">
          <button aria-pressed={view === 'channel'} onClick={() => setView('channel')}>
            {model.scenario.channelName}
          </button>
          <button aria-pressed={view === 'all'} onClick={() => setView('all')}>
            All traffic
          </button>
        </div>
        <span className="ml-auto text-[12.5px] text-[var(--muted)]" title="Every answer a teammate gives to a question of yours, and every pointer they volunteer, counts as a hint and is logged">
          Hints used: <span className="font-bold tabular-nums" style={{ color: model.hints ? 'var(--warn)' : 'var(--text)' }}>{model.hints}</span>
        </span>
      </div>
      <div className="min-h-0 flex-1">{view === 'channel' ? <Channel model={model} onPost={onPost} replay={!!replay} /> : <Traffic model={model} />}</div>
    </div>
  )
}

/** The incident channel: what the team said (and what you said), with the box to post and to ask a teammate. */
export function Channel({ model, onPost, replay }: { model: OfficeModel; onPost?: Props['onPost']; replay: boolean }) {
  const sc = model.scenario!
  const end = useRef<HTMLDivElement>(null)
  const [text, setText] = useState('')
  const [to, setTo] = useState('')
  const [sending, setSending] = useState(false)
  const msgs = model.channel
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [msgs.length])
  const people = recipients(sc.teammates, (id) => model.name(id))
  const send = async () => {
    const body = text.trim()
    if (!body || sending || !onPost || replay) return
    setSending(true)
    try {
      await onPost(body, to || undefined)
      setText('')
    } finally {
      setSending(false)
    }
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2" aria-label={`${sc.channelName} messages`}>
        {msgs.length === 0 && <div className="py-3 text-[13.5px] text-[var(--muted)]">{sc.channelName} is quiet. The first report arrives in a few seconds.</div>}
        {msgs.map((m) => {
          const mine = m.source === 'learner'
          return (
            <div key={m.id} className="flex gap-3 border-b border-[#161c2d] py-1.5 text-[14px] leading-snug">
              <div className="w-[150px] shrink-0">
                <div className="font-semibold" style={{ color: mine ? TONE.good : TONE.info }}>{mine ? 'You' : model.name(m.from)}</div>
                <div className="text-[11.5px] tabular-nums text-[var(--muted)]">{formatClock(m.t)}</div>
              </div>
              <div className="min-w-0 flex-1 text-[#c9d3ee]">
                {m.to.length > 0 && <span className="mr-1 text-[var(--muted)]">{m.to.map((id) => `@${model.name(id)}`).join(' ')}</span>}
                {m.text}
                <span className="ml-2 inline-flex gap-1.5 align-middle">
                  {m.hint && !mine && <span className="rounded border border-[var(--warn)] px-1.5 py-[0px] text-[10.5px] font-bold uppercase tracking-wide text-[var(--warn)]">hint</span>}
                  {SOURCE_LABEL[m.source] && <span className="text-[11px] text-[var(--muted)]">{SOURCE_LABEL[m.source]}</span>}
                </span>
              </div>
            </div>
          )
        })}
        <div ref={end} />
      </div>
      <form
        className="flex shrink-0 items-center gap-2 border-t border-[var(--line)] px-3 py-2"
        onSubmit={(e) => {
          e.preventDefault()
          void send()
        }}
      >
        <label className="sr-only" htmlFor="channel-to">Ask</label>
        <select id="channel-to" value={to} onChange={(e) => setTo(e.target.value)} className="rounded-md border border-[var(--line)] bg-[#0b0e17] px-2 py-1.5 text-[13px] text-[var(--text)]">
          <option value="">Everyone</option>
          {people.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={replay}
          maxLength={1000}
          aria-label="Message"
          placeholder={`Post an update, or ask ${people.map((p) => p.name).join(', ') || 'a teammate'}…`}
          className="min-w-0 flex-1 rounded-md border border-[var(--line)] bg-[#0b0e17] px-3 py-1.5 text-[14px] text-[var(--text)] outline-none focus:border-[var(--accent)]"
        />
        <button type="submit" disabled={!text.trim() || sending || replay} className="rounded-md bg-[#2f5bd6] px-4 py-1.5 text-[13.5px] font-bold text-white hover:bg-[#3b6af0] disabled:opacity-40">
          {sending ? 'Sending…' : 'Send'}
        </button>
      </form>
    </div>
  )
}

function Traffic({ model }: { model: OfficeModel }) {
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
