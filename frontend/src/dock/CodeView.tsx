// Read-only Monaco viewers. This file (and Monaco with it) is loaded lazily, the first time a code tab is opened.
import { DiffEditor, Editor } from '@monaco-editor/react'
import { useRef } from 'react'
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

/** The IDE's editor: the same Monaco and theme, editable when the file is the person's. `onSave` is Ctrl+S inside the editor. */
export function EditView({ path, value, readOnly, onChange, onSave }: { path: string; value: string; readOnly: boolean; onChange: (text: string) => void; onSave: () => void }) {
  const save = useRef(onSave)
  save.current = onSave
  return (
    <Editor
      height="100%"
      theme={MONACO_THEME}
      path={path}
      language={languageFor(path)}
      value={value}
      onChange={(v) => onChange(v ?? '')}
      onMount={(editor, monaco) => editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => save.current())}
      options={{ ...BASE, readOnly, renderLineHighlight: 'line', domReadOnly: readOnly }}
      loading={<Loading />}
    />
  )
}
