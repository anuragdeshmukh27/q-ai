import { Suspense, lazy } from 'react'

const Code = lazy(() => import('./CodeView').then((m) => ({ default: m.CodeView })))
const Diff = lazy(() => import('./CodeView').then((m) => ({ default: m.DiffView })))

const fallback = <div className="p-4 text-[13px] text-[var(--muted)]">Loading the code viewer…</div>

export const LazyCode = (p: { path: string; content: string }) => (
  <Suspense fallback={fallback}>
    <Code {...p} />
  </Suspense>
)

export const LazyDiff = (p: { path: string; original: string; modified: string }) => (
  <Suspense fallback={fallback}>
    <Diff {...p} />
  </Suspense>
)

const Edit = lazy(() => import('./CodeView').then((m) => ({ default: m.EditView })))

export const LazyEdit = (p: { path: string; value: string; readOnly: boolean; onChange: (text: string) => void; onSave: () => void }) => (
  <Suspense fallback={fallback}>
    <Edit {...p} />
  </Suspense>
)
