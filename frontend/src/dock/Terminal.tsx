import { FitAddon } from '@xterm/addon-fit'
import { Terminal as XTerm } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { useEffect, useRef } from 'react'
import type { OfficeModel, TermLine } from '../model'

const COLOR: Record<TermLine['kind'], string> = {
  cmd: '\x1b[1;36m',
  out: '\x1b[90m',
  ok: '\x1b[32m',
  bad: '\x1b[31m',
  info: '\x1b[37m',
}

/** Live terminal: commands the agents run, their output, test and merge results. Written incrementally from the model. */
export function Terminal({ model }: { model: OfficeModel }) {
  const host = useRef<HTMLDivElement>(null)
  const term = useRef<XTerm | null>(null)
  const written = useRef(0)

  useEffect(() => {
    const t = new XTerm({
      fontSize: 13,
      fontFamily: '"Cascadia Mono", Consolas, monospace',
      theme: { background: '#080b13', foreground: '#c9d3ee' },
      convertEol: true,
      disableStdin: true,
      cursorBlink: false,
      cursorStyle: 'underline',
      scrollback: 5000,
    })
    const fit = new FitAddon()
    t.loadAddon(fit)
    t.open(host.current!)
    const refit = () => {
      try {
        fit.fit()
      } catch {
        /* hidden for a moment */
      }
    }
    refit()
    term.current = t
    written.current = 0
    const ro = new ResizeObserver(refit)
    ro.observe(host.current!)
    return () => {
      ro.disconnect()
      t.dispose()
      term.current = null
    }
  }, [])

  const lines = model.terminal
  useEffect(() => {
    const t = term.current
    if (!t) return
    if (lines.length < written.current) {
      t.reset()
      written.current = 0
    }
    if (written.current === 0 && lines.length === 0) t.write('\x1b[90mCommands, test runs and merges will stream here.\x1b[0m\r\n')
    for (let i = written.current; i < lines.length; i++) {
      const l = lines[i]
      const tag = l.kind === 'cmd' ? `\x1b[90m[${model.name(l.agent)}]\x1b[0m ` : ''
      t.write(`${tag}${COLOR[l.kind]}${l.text}\x1b[0m\r\n`)
    }
    written.current = lines.length
  }, [lines, model])

  return <div ref={host} className="h-full w-full bg-[#080b13] p-2" />
}
