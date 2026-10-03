import { useEffect, useRef } from 'react'
import { OfficeScene } from '../office/scene'
import type { OfficeModel } from '../model'

declare global {
  interface Window {
    __q?: { scene: OfficeScene; model: OfficeModel }
  }
}

interface Props {
  model: OfficeModel
  selected: string | null
  tempo: number
  onSelect: (id: string | null) => void
}

export function OfficeCanvas({ model, selected, tempo, onSelect }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const scene = useRef<OfficeScene | null>(null)
  const pick = useRef(onSelect)
  useEffect(() => {
    pick.current = onSelect
  }, [onSelect])

  useEffect(() => {
    const el = host.current!
    const s = new OfficeScene(el, model, { onSelect: (id) => pick.current(id) })
    scene.current = s
    let alive = true
    s.start().then(() => {
      // handy for rehearsal and screenshots: __q.scene.forceState('backend', 'typing')
      if (alive) window.__q = { scene: s, model }
    })
    return () => {
      alive = false
      if (window.__q?.scene === s) window.__q = undefined
      s.destroy()
      scene.current = null
    }
  }, [model])

  useEffect(() => scene.current?.select(selected), [selected])
  useEffect(() => scene.current?.setTempo(tempo), [tempo])

  return <div ref={host} className="absolute inset-0" />
}
