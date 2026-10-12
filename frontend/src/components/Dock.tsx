import { useEffect, useState } from 'react'
import { AgentChat } from '../dock/AgentChat'
import { Approvals } from '../dock/Approvals'
import { ContractTab } from '../dock/ContractTab'
import { DebriefTab } from '../dock/DebriefTab'
import { Explorer } from '../dock/Explorer'
import { GapReport } from '../dock/GapReport'
import { GitGraph } from '../dock/GitGraph'
import { IdeTab } from '../dock/IdeTab'
import { LeaderboardTab } from '../dock/LeaderboardTab'
import { Terminal } from '../dock/Terminal'
import type { OfficeModel } from '../model'
import { unreadCount } from '../scenario'

const TABS = ['IDE', 'Debrief', 'Explorer', 'Terminal', 'Agent Chat', 'Approvals', 'Git', 'Leaderboard', 'Contract', 'Gap report'] as const
type Tab = (typeof TABS)[number]

// the Gap report tab only exists for a project that was imported (Finish my project)

interface Props {
  model: OfficeModel
  projectId: string | null
  replay: boolean
  onDecide: (id: string, approve: boolean) => void
  ticker: string
  onSubmit: (task: string) => Promise<void>
  onError: (e: unknown) => void
  onPost: (text: string, to?: string) => Promise<void>
  /** Start the scenario again (the Debrief tab's Try again): the next attempt. */
  onTryAgain: (scenarioId: string) => Promise<void>
  busy: boolean
}

export function Dock({ model, projectId, replay, onDecide, ticker, onSubmit, onError, onPost, onTryAgain, busy }: Props) {
  const [tab, setTab] = useState<Tab>('Explorer')
  const ide = model.humanRoles.size > 0 && !replay // the IDE tab exists while the person plays a role in a live Simulation build
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

  // Finish my project: the gap report brings itself forward when the build waits for the human's choice
  const choosing = !!model.finish?.selecting
  useEffect(() => {
    if (choosing) {
      setTab('Gap report')
      setOpen(true)
    }
  }, [choosing])

  // a task that is yours brings the IDE forward, once
  const mine = model.tasks.find((t) => t.assignee === 'human' && t.worktree && t.status === 'running')?.id ?? ''
  useEffect(() => {
    if (mine && ide) {
      setTab('IDE')
      setOpen(true)
    }
  }, [mine, ide])
  useEffect(() => {
    if (!ide && tab === 'IDE') setTab('Explorer')
  }, [ide, tab])

  // an incident session: the Agent Chat tab counts the channel messages you have not seen yet
  const [seen, setSeen] = useState(0)
  const viewing = open && tab === 'Agent Chat'
  const channelSize = model.channel.length
  const startedAt = model.scenario?.startedAt
  useEffect(() => setSeen(0), [startedAt])
  useEffect(() => {
    if (viewing) setSeen(channelSize)
  }, [viewing, channelSize])
  const unread = model.scenario ? unreadCount(model.channel, seen) : 0

  // the debrief: the meeting brings the channel forward, the report brings the Debrief tab forward (once each)
  const debriefPhase = model.debrief?.phase
  const hasReport = !!model.debrief?.report
  const debrief = !!model.debrief && !replay // the Debrief tab exists from the meeting on
  const [reportSeen, setReportSeen] = useState(false)
  useEffect(() => {
    if (debriefPhase === 'meeting') {
      setTab('Agent Chat')
      setOpen(true)
    }
  }, [debriefPhase])
  useEffect(() => {
    if (hasReport) {
      setTab('Debrief')
      setOpen(true)
    }
  }, [hasReport])
  useEffect(() => setReportSeen(false), [startedAt])
  useEffect(() => {
    if (open && tab === 'Debrief' && hasReport) setReportSeen(true)
  }, [open, tab, hasReport])
  useEffect(() => {
    if (!debrief && tab === 'Debrief') setTab('Explorer')
  }, [debrief, tab])

  const badge = (t: Tab) => (t === 'Approvals' && pending ? pending : t === 'Agent Chat' ? (model.scenario ? unread : model.messages.length) : t === 'Debrief' && hasReport && !reportSeen ? 1 : 0)

  return (
    <section className="flex shrink-0 flex-col border-t border-[var(--line)] bg-[var(--panel)]" style={{ height: open ? (tab === 'IDE' || tab === 'Debrief' ? 'min(560px, 62vh)' : 'min(300px, 36vh)') : 44 }}>
      <div className="flex h-[44px] shrink-0 items-center gap-1 px-3">
        {TABS.filter((t) => (t !== 'Gap report' || model.finish) && (t !== 'IDE' || ide) && (t !== 'Debrief' || debrief)).map((t) => (
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
              <span className="ml-1.5 rounded-full px-1.5 py-[1px] text-[11px] font-bold text-[#0b0d12]" style={{ background: t === 'Approvals' || (t === 'Agent Chat' && model.scenario) ? 'var(--warn)' : '#6ea8ff' }}>
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
          {tab === 'IDE' && <IdeTab projectId={projectId} model={model} replay={replay} onSubmit={onSubmit} onError={onError} />}
          {tab === 'Debrief' && <DebriefTab model={model} projectId={projectId} onTryAgain={onTryAgain} busy={busy} />}
          {tab === 'Explorer' && <Explorer projectId={projectId} model={model} />}
          {tab === 'Terminal' && <Terminal model={model} />}
          {tab === 'Agent Chat' && <AgentChat model={model} onPost={onPost} replay={replay} />}
          {tab === 'Approvals' && <Approvals model={model} replay={replay} onDecide={onDecide} />}
          {tab === 'Git' && <GitGraph projectId={projectId} model={model} />}
          {tab === 'Leaderboard' && <LeaderboardTab />}
          {tab === 'Contract' && <ContractTab projectId={projectId} model={model} />}
          {tab === 'Gap report' && <GapReport projectId={projectId} model={model} />}
        </div>
      )}
    </section>
  )
}
