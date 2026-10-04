import { ESCALATION_BUTTONS, type EscalationAction } from '../escalation'
import type { Toast } from '../useQ'

const COLORS = { info: '#6ea8ff', good: '#4ade80', bad: '#f87171', warn: '#fbbf24' }

interface Props {
  toasts: Toast[]
  onDismiss: (id: number) => void
  onDecide: (approvalId: string, approve: boolean) => void
  onEscalate: (action: EscalationAction, agent: string) => void
}

export function Toasts({ toasts, onDismiss, onDecide, onEscalate }: Props) {
  return (
    <div className="pointer-events-none absolute right-4 top-4 z-20 flex w-[380px] flex-col gap-2">
      {toasts.map((t) => (
        <div key={t.id} className="toast pointer-events-auto rounded-lg border bg-[#10141f] p-3 shadow-2xl" style={{ borderColor: COLORS[t.level] }} role="status">
          <div className="flex items-start justify-between gap-3">
            <div className="text-[15px] font-bold" style={{ color: COLORS[t.level] }}>
              {t.title}
            </div>
            <button onClick={() => onDismiss(t.id)} aria-label="Dismiss" className="text-[var(--muted)] hover:text-white">
              ✕
            </button>
          </div>
          {t.text && <div className="mt-1 text-[13.5px] leading-snug text-[var(--text)]">{t.text}</div>}
          {t.action?.type === 'approval' && (
            <div className="mt-2 flex gap-2">
              <button onClick={() => t.action?.type === 'approval' && onDecide(t.action.id, true)} className="rounded-md bg-[#2f9e5f] px-4 py-1 text-[13px] font-bold text-white">
                Approve
              </button>
              <button onClick={() => t.action?.type === 'approval' && onDecide(t.action.id, false)} className="rounded-md bg-[#b9434f] px-4 py-1 text-[13px] font-bold text-white">
                Reject
              </button>
            </div>
          )}
          {t.action?.type === 'escalation' && (
            <div className="mt-2 flex flex-wrap gap-2">
              {ESCALATION_BUTTONS.map((b) => (
                <button
                  key={b.action}
                  title={b.hint}
                  onClick={() => t.action?.type === 'escalation' && onEscalate(b.action, t.action.agent)}
                  className={`rounded-md px-3 py-1 text-[13px] font-bold text-white ${b.action === 'stop' ? 'bg-[#b9434f]' : 'bg-[#3563e6]'}`}
                >
                  {b.label}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
