import type { Toast } from '../useQ'

const COLORS = { info: '#6ea8ff', good: '#4ade80', bad: '#f87171', warn: '#fbbf24' }

export function Toasts({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
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
        </div>
      ))}
    </div>
  )
}
