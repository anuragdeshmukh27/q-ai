import type { ApprovalView, OfficeModel } from '../model'
import { decidedBy } from '../approvalText'
import { Empty } from './Explorer'

const KIND: Record<string, string> = {
  review_unresolved: 'Review items still open',
  merge_conflict: 'Merge conflict resolution',
  install: 'Dependency install',
  contract_change: 'Contract change',
  delete: 'File deletion',
  command: 'Command',
  write: 'File write',
}

function Details({ d }: { d: Record<string, unknown> }) {
  const rows = Object.entries(d).filter(([, v]) => v !== '' && v != null)
  if (!rows.length) return null
  return (
    <div className="mt-1.5 rounded-md bg-[#080b13] p-2 font-mono text-[12px] leading-relaxed text-[#9fb0d4]">
      {rows.map(([k, v]) => (
        <div key={k} className="whitespace-pre-wrap break-words">
          <span className="text-[var(--muted)]">{k}:</span> {typeof v === 'string' ? v : JSON.stringify(v)}
        </div>
      ))}
    </div>
  )
}

function Card({ a, model, canDecide, onDecide }: { a: ApprovalView; model: OfficeModel; canDecide: boolean; onDecide: (id: string, ok: boolean) => void }) {
  const pending = a.state === 'pending'
  const col = pending ? 'var(--warn)' : a.state === 'approved' ? 'var(--good)' : 'var(--bad)'
  return (
    <div className="rounded-lg border bg-[#10141f] p-3" style={{ borderColor: pending ? col : 'var(--line)' }}>
      <div className="flex items-center gap-2 text-[14px]">
        <span className="rounded-full border px-2 py-[1px] text-[11px] font-bold" style={{ borderColor: col, color: col }}>
          {pending ? 'WAITING FOR YOU' : a.state === 'approved' ? 'APPROVED' : 'REJECTED'}
        </span>
        <span className="font-bold">{model.name(a.agent)}</span>
        <span className="text-[var(--muted)]">· {KIND[a.kind] ?? a.kind}</span>
        {!pending && <span className="ml-auto text-[12px] text-[var(--muted)]">{decidedBy(a.by)}</span>}
      </div>
      <div className="mt-1 text-[14px]">{a.summary}</div>
      <Details d={a.details} />
      {a.note && <div className="mt-1.5 text-[13px] font-semibold text-[var(--warn)]">Note: {a.note}</div>}
      {pending && (
        <div className="mt-2 flex items-center gap-2">
          <button disabled={!canDecide} onClick={() => onDecide(a.id, true)} className="rounded-md bg-[#2f9e5f] px-4 py-1 text-[13px] font-bold text-white disabled:opacity-40">Approve</button>
          <button disabled={!canDecide} onClick={() => onDecide(a.id, false)} className="rounded-md bg-[#b9434f] px-4 py-1 text-[13px] font-bold text-white disabled:opacity-40">Reject</button>
        </div>
      )}
    </div>
  )
}

export function Approvals({ model, onDecide }: { model: OfficeModel; replay?: boolean; onDecide: (id: string, ok: boolean) => void }) {
  const items = [...model.approvals].reverse()
  if (!items.length) {
    return <Empty text={model.mode === 'autonomous' ? 'Autonomous mode: nothing waits for approval.' : 'Nothing needs approval. In Supervised mode the team pauses here for contract changes, installs, deletions, merge conflicts and open review items.'} />
  }
  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto p-3">
      {items.map((a) => (
        <Card key={a.id} a={a} model={model} canDecide onDecide={onDecide} />
      ))}
    </div>
  )
}
