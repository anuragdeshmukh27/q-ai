// The one hook the UI uses: backend connection, the current project's event stream, and the controls.
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { pickDefault } from './demos'
import { ApiError, api, openStream, type ConfigInfo, type Metrics, type RecordingMeta } from './api'
import type { EscalationAction } from './escalation'
import { OfficeModel, type ToastAction, type Tone } from './model'

export interface Toast {
  id: number
  key?: string
  level: Tone
  title: string
  text: string
  action?: ToastAction
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
  const [config, setConfig] = useState<ConfigInfo | null>(null)
  const [preset, setPreset] = useState('fastapi-vanilla')
  const [fast, setFast] = useState(true) // fast live mode: skip an unneeded polish pass, one LLM review round per task
  const [replay, setReplay] = useState(false) // the current project is a replay, not a live build
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [builds, setBuilds] = useState(0)
  const [busy, setBusy] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const toastId = useRef(0)

  const toast = useCallback((level: Tone, title: string, text = '', key?: string, action?: ToastAction) => {
    const id = ++toastId.current
    setToasts((t) => [...t.slice(-3), { id, key, level, title, text, action }])
    // A toast waiting on a decision stays long enough to be answered; the rest fade.
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), key ? 60000 : level === 'good' ? 6000 : 9000)
  }, [])

  /** Rewrite a toast in place (an approval that has now been decided), then let it fade. */
  const updateToast = useCallback((key: string, level: Tone, title: string, text: string) => {
    let id = 0
    setToasts((t) => t.map((x) => (x.key === key ? ((id = x.id), { ...x, level, title, text, action: undefined }) : x)))
    if (id) window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000)
  }, [])

  const fail = useCallback((e: unknown) => toast('bad', 'Could not do that', e instanceof ApiError ? e.message : 'Something went wrong. Please try again.'), [toast])

  // The model turns events into visuals; toasts are one kind of visual.
  useEffect(
    () =>
      model.onVisual((v) => {
        if (v.kind === 'toast') toast(v.level, v.title, v.text, v.key, v.action)
        else if (v.kind === 'toast_update') updateToast(v.key, v.level, v.title, v.text)
      }),
    [model, toast, updateToast],
  )

  // Team + recordings: retry until the backend answers.
  useEffect(() => {
    let stop = false
    let timer: number | undefined
    const load = async () => {
      try {
        const [agents, recs, cfg] = await Promise.all([api.agents(), api.recordings(), api.config()])
        if (stop) return
        model.setRoster(agents)
        setConfig(cfg)
        setRecordings(recs)
        setRecording((cur) => cur || pickDefault(recs))
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
        const s = await api.create({ goal, mode, demo, recording: demo ? recording || undefined : undefined, speed, preset: demo ? undefined : preset, fast_live: demo ? undefined : fast })
        model.reset()
        model.setGoal(goal)
        model.setMode(s.mode)
        setProjectId(s.id)
        setReplay(demo)
        setBuilds((await api.projects().catch(() => [])).length || builds + 1)
      } catch (e) {
        fail(e)
      } finally {
        setBusy(false)
      }
    },
    [mode, demo, recording, speed, preset, fast, model, fail, builds],
  )

  const startImport = useCallback(
    async (source: string, autoFix: boolean) => {
      setBusy(true)
      try {
        const s = await api.create({ goal: '', mode, demo: false, import_from: source, auto_fix: autoFix, fast_live: fast })
        model.reset()
        model.setGoal(s.goal)
        model.setMode(s.mode)
        setProjectId(s.id)
        setReplay(false)
        setBuilds((await api.projects().catch(() => [])).length || builds + 1)
      } catch (e) {
        fail(e)
      } finally {
        setBusy(false)
      }
    },
    [mode, fast, model, fail, builds],
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

  const decide = useCallback(
    async (aid: string, approve: boolean) => {
      if (projectId) await api.decide(projectId, aid, approve).catch(fail)
    },
    [projectId, fail],
  )

  const escalate = useCallback(
    async (action: EscalationAction, agent: string) => {
      if (!projectId) return
      await api.escalate(projectId, action, agent).catch(fail) // the server answers with an escalation_action event, which rewrites the toast
    },
    [projectId, fail],
  )

  return {
    config, preset, setPreset, fast, setFast, replay, decide, escalate, toast, fail,
    model, backend, projectId, connected, demo, setDemo, speed, setSpeed, mode, setMode, recordings, recording, setRecording,
    metrics, builds, busy, start, startImport, toasts, dismissToast: (id: number) => setToasts((t) => t.filter((x) => x.id !== id)),
  }
}
