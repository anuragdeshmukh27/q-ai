// Read-only Monaco viewers. This file (and Monaco with it) is loaded lazily, the first time a code tab is opened.
import { DiffEditor, Editor } from '@monaco-editor/react'
import { languageFor } from '../diff'
import { MONACO_THEME } from './monaco'

const BASE = { readOnly: true, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false, automaticLayout: true, renderLineHighlight: 'none', padding: { top: 8 } } as const

export function CodeView({ path, content }: { path: string; content: string }) {
  return <Editor height="100%" theme={MONACO_THEME} path={path} language={languageFor(path)} value={content} options={BASE} loading={<Loading />} />
}

export function DiffView({ path, original, modified }: { path: string; original: string; modified: string }) {
  return (
    <DiffEditor
      height="100%"
      theme={MONACO_THEME}
      language={languageFor(path)}
      original={original}
      keepCurrentOriginalModel
      keepCurrentModifiedModel
      modified={modified}
      options={{ ...BASE, renderSideBySide: true, renderSideBySideInlineBreakpoint: 700, originalEditable: false }}
      loading={<Loading />}
    />
  )
}

function Loading() {
  return <div className="p-4 text-[13px] text-[var(--muted)]">Loading the code viewer…</div>
}
