import { useState } from 'react'
import { api } from '../api'
import type { OfficeModel } from '../model'
import { Empty } from './Explorer'
import { useRefetch } from './hooks'
import { LazyCode } from './lazy'

interface Field {
  name: string
  type: string
  description?: string
  options?: string[]
}
interface Endpoint {
  method: string
  path: string
  summary?: string
  request?: { fields?: Field[] }
  response?: { status?: number; fields?: Field[] }
  errors?: { status: number; detail: string }[]
}

const METHOD: Record<string, string> = { GET: '#4ade80', POST: '#6ea8ff', PUT: '#fbbf24', PATCH: '#fbbf24', DELETE: '#f87171' }

const fields = (f?: Field[]) => (f?.length ? f.map((x) => `${x.name}: ${x.options?.length ? x.options.join(' | ') : x.type}`).join(', ') : '—')

/** The spec text without its title and summary lines (the card shows those itself). */
const specBody = (text: string) => text.split(String.fromCharCode(10)).slice(3).join(String.fromCharCode(10)).trim()

export function ContractTab({ projectId, model }: { projectId: string | null; model: OfficeModel }) {
  const file = useRefetch(projectId ? () => api.file(projectId, '.q/api_contract.json') : null, projectId ?? '', model.filesVersion)
  const [raw, setRaw] = useState(false)
  if (!projectId) return <Empty text="The Architect's product spec and API contract appear here, versioned." />
  if (!file.data) return <Empty text={file.error ? 'The contract is not written yet.' : 'Loading…'} />
  let contract: { version?: number; endpoints?: Endpoint[]; error_format?: unknown } = {}
  try {
    contract = JSON.parse(file.data.content)
  } catch {
    return <Empty text="The contract file could not be read." />
  }
  const hist = model.contractHistory
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b border-[var(--line)] px-3 py-1.5 text-[13px]">
        <span className="rounded-full bg-[#243055] px-3 py-0.5 text-[12px] font-bold">Contract v{contract.version ?? model.contractVersion}</span>
        <span className="text-[var(--muted)]">{contract.endpoints?.length ?? 0} endpoints · the source of truth for every engineer and for QA</span>
        {hist.length > 1 && <span className="text-[var(--warn)]">amended {hist.length - 1}×</span>}
        <div className="seg ml-auto">
          <button aria-pressed={!raw} onClick={() => setRaw(false)}>Endpoints</button>
          <button aria-pressed={raw} onClick={() => setRaw(true)}>JSON</button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {raw ? (
          <LazyCode path="api_contract.json" content={file.data.content} />
        ) : (
          <div className="grid gap-2 p-3 [grid-template-columns:repeat(auto-fill,minmax(360px,1fr))]">
            {model.spec && (
              <div className="rounded-lg border border-[#3b4f8f] bg-[#121a33] p-3 [grid-column:1/-1]" data-testid="spec-card">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-[#6ea8ff] px-2 py-0.5 font-mono text-[12px] font-bold text-[#0b0d12]">SPEC</span>
                  <span className="text-[14px] font-semibold">{model.spec.title}</span>
                  <span className="text-[12px] text-[var(--muted)]">the Architect expanded your goal into this MVP</span>
                </div>
                <div className="mt-1 text-[13px] text-[#c9d3ee]">{model.spec.summary}</div>
                <pre className="mt-2 whitespace-pre-wrap font-mono text-[12px] leading-snug text-[#9fb0d4]">{specBody(model.spec.text)}</pre>
              </div>
            )}
            {(contract.endpoints ?? []).map((e) => (
              <div key={`${e.method} ${e.path}`} className="rounded-lg border border-[var(--line)] bg-[#10141f] p-3">
                <div className="flex items-center gap-2">
                  <span className="rounded px-2 py-0.5 font-mono text-[12px] font-bold text-[#0b0d12]" style={{ background: METHOD[e.method] ?? '#8a93aa' }}>{e.method}</span>
                  <span className="font-mono text-[14px] font-semibold">{e.path}</span>
                </div>
                {e.summary && <div className="mt-1 text-[13px] text-[#c9d3ee]">{e.summary}</div>}
                <div className="mt-2 grid grid-cols-[64px_1fr] gap-x-2 gap-y-1 font-mono text-[12px] text-[#9fb0d4]">
                  <span className="text-[var(--muted)]">request</span>
                  <span>{fields(e.request?.fields)}</span>
                  <span className="text-[var(--muted)]">response</span>
                  <span>{e.response?.status ? `${e.response.status} ` : ''}{fields(e.response?.fields)}</span>
                  {!!e.errors?.length && (
                    <>
                      <span className="text-[var(--muted)]">errors</span>
                      <span>{e.errors.map((x) => `${x.status} ${x.detail}`).join(' · ')}</span>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
