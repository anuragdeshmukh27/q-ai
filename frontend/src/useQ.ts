// The one hook the UI uses: backend connection, the current project's event stream, and the controls.
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { ApiError, api, openStream, type Metrics, type RecordingMeta } from './api'
import { OfficeModel, type Tone } from './model'

export interface Toast {
  id: number
  level: Tone
  title: string
  text: string
}

export function useQ() {
  const model = useMemo(() => new OfficeModel(), [])
  useSyncExternalStore(model.subscribe, model.getVersion)

  const [backend, setBackend] = useState<'checking' | 'ok' | 'down'>('checking')
  const [projectId, setProjectId] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)
  const [demo, setDemo] = useState(true)
  const [speed, setSpeedState] = useState(1)
  const [mode, setModeState] = useState('supervised')
  const [recordings, setRecordings] = useState<RecordingMeta[]>([])
  const [recording, setRecording] = useState('')
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [builds, setBuilds] = useState(0)
  const [busy, setBusy] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const toastId = useRef(0)

  const toast = useCallback((level: Tone, title: string, text = '') => {
    const id = ++toastId.current
    setToasts((t) => [...t.slice(-3), { id, level, title, text }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), level === 'good' ? 6000 : 9000)
  }, [])

  const fail = useCallback((e: unknown) => toast('bad', 'Could not do that', e instanceof ApiError ? e.message : 'Something went wrong. Please try again.'), [toast])

  // The model turns events into visuals; toasts are one kind of visual.
  useEffect(() => model.onVisual((v) => { if (v.kind === 'toast') toast(v.level, v.title, v.text) }), [model, toast])

  // Team + recordings: retry until the backend answers.
  useEffect(() => {
    let stop = false
    let timer: number | undefined
    const load = async () => {
      try {
        const [agents, recs] = await Promise.all([api.agents(), api.recordings()])
        if (stop) return
        model.setRoster(agents)
        setRecordings(recs)
        setRecording((cur) => cur || recs.find((r) => r.ok)?.name || '')
        setBackend('ok')
      } catch {
        if (stop) return
        setBackend('down')
        timer = window.setTimeout(load, 2000)
      }
    }
    load()
    return () => {
      stop = true
      if (timer) clearTimeout(timer)
    }
  }, [model])

  // Machine gauges.
  useEffect(() => {
    if (backend !== 'ok') return
    let stop = false
    const poll = () => api.metrics().then((m) => !stop && setMetrics(m)).catch(() => {})
    poll()
    const t = window.setInterval(poll, 2500)
    return () => {
      stop = true
      clearInterval(t)
    }
  }, [backend])

  // Event stream of the current project.
  useEffect(() => {
    if (!projectId) return
    return openStream(
      projectId,
      (events, catchUp) => events.forEach((e) => model.apply(e, !catchUp)),
      setConnected,
    )
  }, [projectId, model])

  const start = useCallback(
    async (goal: string) => {
      setBusy(true)
      try {
        const s = await api.create({ goal, mode, demo, recording: demo ? recording || undefined : undefined, speed })
        model.reset()
        model.setGoal(goal)
        model.setMode(s.mode)
        setProjectId(s.id)
        setBuilds((await api.projects().catch(() => [])).length || builds + 1)
      } catch (e) {
        fail(e)
      } finally {
        setBusy(false)
      }
    },
    [mode, demo, recording, speed, model, fail, builds],
  )

  const setMode = useCallback(
    async (m: string) => {
      setModeState(m)
      model.setMode(m)
      if (projectId) await api.setMode(projectId, m).catch(fail)
    },
    [projectId, model, fail],
  )

  const setSpeed = useCallback(
    async (s: number) => {
      setSpeedState(s)
      if (projectId && demo) await api.setSpeed(projectId, s).catch(fail)
    },
    [projectId, demo, fail],
  )

  return {
    model, backend, projectId, connected, demo, setDemo, speed, setSpeed, mode, setMode, recordings, recording, setRecording,
    metrics, builds, busy, start, toasts, dismissToast: (id: number) => setToasts((t) => t.filter((x) => x.id !== id)),
  }
}
