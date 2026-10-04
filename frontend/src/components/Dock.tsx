import { useEffect, useState } from 'react'
import { AgentChat } from '../dock/AgentChat'
import { Approvals } from '../dock/Approvals'
import { ContractTab } from '../dock/ContractTab'
import { Explorer } from '../dock/Explorer'
import { GitGraph } from '../dock/GitGraph'
import { LeaderboardTab } from '../dock/LeaderboardTab'
import { Terminal } from '../dock/Terminal'
import type { OfficeModel } from '../model'

const TABS = ['Explorer', 'Terminal', 'Agent Chat', 'Approvals', 'Git', 'Leaderboard', 'Contract'] as const
type Tab = (typeof TABS)[number]

interface Props {
  model: OfficeModel
  projectId: string | null
  replay: boolean
  onDecide: (id: string, approve: boolean) => void
  ticker: string
}

export function Dock({ model, projectId, replay, onDecide, ticker }: Props) {
  const [tab, setTab] = useState<Tab>('Explorer')
  const [open, setOpen] = useState(true)
  const pending = model.approvals.filter((a) => a.state === 'pending').length

  // A build that needs a decision brings the Approvals tab forward. In a replay only an approval that stays open does (the recording's own ones resolve within a second).
  useEffect(() => {
    if (pending === 0) return
    const go = () => {
      setTab('Approvals')
      setOpen(true)
    }
    if (!replay) {
      go()
      return
    }
    const t = window.setTimeout(go, 900)
    return () => window.clearTimeout(t)
  }, [pending, replay])

  const badge = (t: Tab) => (t === 'Approvals' && pending ? pending : t === 'Agent Chat' && model.messages.length ? model.messages.length : 0)

  return (
    <section className="flex shrink-0 flex-col border-t border-[var(--line)] bg-[var(--panel)]" style={{ height: open ? 'min(300px, 36vh)' : 44 }}>
      <div className="flex h-[44px] shrink-0 items-center gap-1 px-3">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => {
              setTab(t)
              setOpen(true)
            }}
            aria-pressed={open && tab === t}
            className="relative rounded-md px-3 py-1.5 text-[13.5px] font-semibold text-[var(--muted)] hover:text-white aria-pressed:bg-[#243055] aria-pressed:text-white"
          >
            {t}
            {badge(t) > 0 && (
              <span className="ml-1.5 rounded-full px-1.5 py-[1px] text-[11px] font-bold text-[#0b0d12]" style={{ background: t === 'Approvals' ? 'var(--warn)' : '#6ea8ff' }}>
                {badge(t)}
              </span>
            )}
          </button>
        ))}
        <div className="ml-3 flex min-w-0 flex-1 items-center gap-2 text-[13.5px] text-[var(--muted)]" aria-live="polite">
          <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: ticker ? 'var(--accent)' : '#2a3350' }} />
          <span className="truncate">{ticker || (projectId ? 'Waiting for the first event…' : 'Give the team a goal and watch them build it.')}</span>
        </div>
        <button onClick={() => setOpen(!open)} aria-label={open ? 'Collapse the dock' : 'Expand the dock'} className="rounded-md px-2 py-1 text-[var(--muted)] hover:bg-[#1a2033] hover:text-white">
          {open ? '▾' : '▴'}
        </button>
      </div>
      {open && (
        <div className="min-h-0 flex-1 border-t border-[var(--line)]">
          {tab === 'Explorer' && <Explorer projectId={projectId} model={model} />}
          {tab === 'Terminal' && <Terminal model={model} />}
          {tab === 'Agent Chat' && <AgentChat model={model} />}
          {tab === 'Approvals' && <Approvals model={model} replay={replay} onDecide={onDecide} />}
          {tab === 'Git' && <GitGraph projectId={projectId} model={model} />}
          {tab === 'Leaderboard' && <LeaderboardTab />}
          {tab === 'Contract' && <ContractTab projectId={projectId} model={model} />}
        </div>
      )}
    </section>
  )
}
