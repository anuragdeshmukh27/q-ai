import { api, type CostRow } from '../api'
import { Empty } from './Explorer'
import { useRefetch } from './hooks'

const inr = (n: number) => (n >= 100 ? `₹${Math.round(n)}` : n >= 1 ? `₹${n.toFixed(1)}` : `₹${n.toFixed(2)}`)

/** What each recorded build used: tokens, the GPU electricity here, and the same tokens at the cloud prices of config/pricing.yaml. */
export function CostPanel() {
  const costs = useRefetch(() => api.costs(), 'costs', 0, 0)
  if (!costs.data) return <Empty text={costs.error || 'Loading…'} />
  const rows: CostRow[] = costs.data.rows
  if (!rows.length) return <Empty text="No cost numbers yet: they appear with every finished build and every recording." />
  const models = rows[0].cloud.map((c) => c.name)
  const total = rows.reduce((a, r) => a + r.total_tokens, 0)
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[12.5px] text-[var(--muted)]">
        <span className="text-[14px] font-bold text-[var(--text)]">Cost of a build</span>
        <span>
          {rows.length} builds, {(total / 1000).toFixed(0)}k tokens in all. Electricity: GPU power from nvidia-smi over the build at ₹{rows[0].inr_per_kwh}/kWh. Cloud columns: the same tokens at the prices in config/pricing.yaml (₹{rows[0].inr_per_usd}/$).
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] border-collapse text-left text-[12.5px]">
          <thead>
            <tr className="text-[11px] uppercase tracking-wide text-[var(--muted)]">
              <th className="p-2">Build</th>
              <th className="p-2">Tokens</th>
              <th className="p-2">Time</th>
              <th className="p-2" title="Electricity the GPU used here">On this laptop</th>
              {models.map((m) => (
                <th key={m} className="p-2">{m}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className="border-t border-[var(--line)]">
                <td className="p-2 font-semibold">{r.title}</td>
                <td className="p-2 tabular-nums">{(r.total_tokens / 1000).toFixed(0)}k</td>
                <td className="p-2 tabular-nums">{Math.round(r.seconds)} s</td>
                <td className="p-2 tabular-nums" style={{ color: 'var(--good)' }} title={`${r.electricity.kwh.toFixed(4)} kWh, average ${r.electricity.avg_watts} W, ${r.electricity.measured ? 'measured' : 'estimated (recorded before the meter)'}`}>
                  {inr(r.electricity.inr)}
                  {!r.electricity.measured && <span className="ml-1 text-[11px] text-[var(--muted)]">est.</span>}
                </td>
                {r.cloud.map((c) => (
                  <td key={c.id} className="p-2 tabular-nums text-[var(--muted)]" title={`$${c.usd.toFixed(3)}`}>
                    {inr(c.inr)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 max-w-[900px] text-[12px] leading-relaxed text-[var(--muted)]">
        How to read this: tokens are counted exactly. The cloud prices are hypothetical: those models would write different amounts and would not run offline. The laptop figure covers GPU power only (not the CPU or the screen); for recordings made before the meter it is estimated from the average draw measured in a live build.
      </p>
    </div>
  )
}
