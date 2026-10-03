// Monaco runs from the local package (no CDN), so the code viewer works offline. Only the base editor worker is bundled:
// syntax colouring comes from the worker-free Monarch grammars, which is all a read-only viewer needs.
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor/editor/editor.api'
import 'monaco-editor/basic-languages/monaco.contribution'
import EditorWorker from 'monaco-editor/editor/editor.worker?worker'

;(self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = { getWorker: () => new EditorWorker() }

monaco.editor.defineTheme('q-dark', {
  base: 'vs-dark',
  inherit: true,
  rules: [],
  colors: { 'editor.background': '#080b13', 'editorGutter.background': '#080b13', 'diffEditor.insertedTextBackground': '#1f6f4a40', 'diffEditor.removedTextBackground': '#8f2f3a40' },
})

loader.config({ monaco: monaco as never })

export const MONACO_THEME = 'q-dark'
