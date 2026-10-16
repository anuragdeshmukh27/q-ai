// The one hook the UI uses: backend connection, the current project's event stream, and the controls.
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { demosFor, pickDefault } from './demos'
import { ApiError, api, openStream, type ConfigInfo, type Metrics, type RecordingMeta } from './api'
import type { EscalationAction } from './escalation'
import { OfficeModel, type ToastAction, type Tone } from './model'
import type { JobRequest } from './jobs'
import type { ScenarioInfo } from './scenario'

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
  const [humanRoles, setHumanRolesState] = useState<string[]>(['backend']) // simulation: the engineers the person plays
  const [recordings, setRecordings] = useState<RecordingMeta[]>([])
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]) // the cards of the scenario picker (Simulation mode)
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
        const [agents, recs, cfg, cards] = await Promise.all([api.agents(), api.recordings(), api.config(), api.scenarios().catch(() => [] as ScenarioInfo[])])
        if (stop) return
        model.setRoster(agents)
        setConfig(cfg)
        setRecordings(recs)
        setScenarios(cards)
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

  // Demo mode lists the recordings of the chosen mode (simulations, or builds): a pick that is not in that list moves to the mode's default.
  useEffect(() => {
    if (!demo || !recordings.length) return
    setRecording((cur) => (demosFor(recordings, mode).some((r) => r.name === cur) ? cur : pickDefault(recordings, mode)))
  }, [demo, mode, recordings])

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
        const sim = !demo && mode === 'simulation' // a replay is a recording: it plays as it was made
        const s = await api.create({ goal, mode: demo && mode === 'simulation' ? 'supervised' : mode, demo, recording: demo ? recording || undefined : undefined, speed, preset: demo ? undefined : preset, fast_live: demo ? undefined : fast, human_roles: sim ? humanRoles : undefined })
        model.reset()
        model.setGoal(goal)
        model.setMode(s.mode)
        if (sim) model.setHumanRoles(humanRoles)
        setProjectId(s.id)
        setReplay(demo)
        setBuilds((await api.projects().catch(() => [])).length || builds + 1)
      } catch (e) {
        fail(e)
      } finally {
        setBusy(false)
      }
    },
    [mode, humanRoles, demo, recording, speed, preset, fast, model, fail, builds],
  )

  /** A scenario: a finished app with a planted problem, one task for the role it names, the AI team on call. */
  const startScenario = useCallback(
    async (id: string, job?: JobRequest) => {
      setBusy(true)
      try {
        const card = scenarios.find((c) => c.id === id)
        const s = await api.startScenario(id, job)
        model.reset()
        model.setGoal(card?.title ?? s.goal)
        model.setMode(s.mode)
        model.setHumanRoles(card ? [card.role] : ['backend'])
        setProjectId(s.id)
        setReplay(false)
        setBuilds((await api.projects().catch(() => [])).length || builds + 1)
      } catch (e) {
        fail(e)
      } finally {
        setBusy(false)
      }
    },
    [scenarios, model, fail, builds],
  )

  /** "Watch a run": a script plays the scenario on the server (variant strong or weak); the screen follows it through its events. */
  const startAutoplay = useCallback(
    async (id: string, variant: string) => {
      setBusy(true)
      try {
        const card = scenarios.find((c) => c.id === id)
        const s = await api.startAutoplay(id, variant, 1)
        model.reset()
        model.setGoal(`${card?.title ?? s.goal} · ${variant === 'weak' ? 'weak' : 'strong'} run`)
        model.setMode(s.mode)
        model.setHumanRoles(card ? [card.role] : ['backend'])
        setProjectId(s.id)
        setReplay(false)
        setBuilds((await api.projects().catch(() => [])).length || builds + 1)
      } catch (e) {
        fail(e)
      } finally {
        setBusy(false)
      }
    },
    [scenarios, model, fail, builds],
  )

  const setAutoplaySpeed = useCallback(
    async (s: number) => {
      if (projectId) await api.autoplaySpeed(projectId, s).catch(fail)
    },
    [projectId, fail],
  )

  /** Stop the scripted run: the server ends the script, the team and the debrief and removes the demo's project; the screen goes back to the start. */
  const stopAutoplay = useCallback(async () => {
    if (!projectId) return
    try {
      await api.autoplayStop(projectId)
    } catch (e) {
      fail(e)
      return
    }
    model.reset()
    setProjectId(null)
    setReplay(false)
    toast('info', 'Autoplay stopped', 'The scripted run was stopped and nothing of it was kept.')
  }, [projectId, model, fail, toast])

  /** A post in the incident channel; the answer of a teammate arrives as a `channel_message` event. */
  const postChannel = useCallback(
    async (text: string, to?: string) => {
      if (projectId) await api.postChannel(projectId, text, to).catch(fail)
    },
    [projectId, fail],
  )

  const startImport = useCallback(
    async (source: string, autoFix: boolean) => {
      setBusy(true)
      try {
        const s = await api.create({ goal: '', mode: mode === 'simulation' ? 'supervised' : mode, demo: false, import_from: source, auto_fix: autoFix, fast_live: fast })
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
      const crossing = (m === 'simulation') !== (mode === 'simulation') // who plays which role is fixed when a build starts
      if (crossing && projectId && !replay && !model.finished) {
        toast('warn', 'Simulation is chosen before the build starts', 'Start a new build to switch into or out of it.')
        return
      }
      setModeState(m)
      model.setMode(m)
      if (crossing) model.setHumanRoles(m === 'simulation' ? humanRoles : [])
      if (projectId && !crossing) await api.setMode(projectId, m).catch(fail)
    },
    [mode, humanRoles, projectId, replay, model, fail, toast],
  )

  /** The role picker: which engineers the person plays in the next simulation build. */
  const setHumanRoles = useCallback(
    (roles: string[]) => {
      setHumanRolesState(roles)
      if (mode === 'simulation' && (!projectId || replay || model.finished)) model.setHumanRoles(roles)
    },
    [mode, projectId, replay, model],
  )

  /** Submit: the answer also arrives as events (a toast for a red test run, for the Reviewer's items, for an accepted task). */
  const submitTask = useCallback(
    async (task: string) => {
      if (projectId) await api.submitTask(projectId, task).catch(fail)
    },
    [projectId, fail],
  )

  const copyPath = useCallback(
    async (path: string) => {
      try {
        await navigator.clipboard.writeText(path)
        toast('good', 'Folder path copied', path)
      } catch {
        toast('info', 'Your folder', path) // the clipboard is not available here: the path is in the message
      }
    },
    [toast],
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
    config, preset, setPreset, fast, setFast, replay, decide, escalate, toast, fail, humanRoles, setHumanRoles, submitTask, copyPath, scenarios, startScenario, startAutoplay, setAutoplaySpeed, stopAutoplay, postChannel,
    model, backend, projectId, connected, demo, setDemo, speed, setSpeed, mode, setMode, recordings, recording, setRecording,
    metrics, builds, busy, start, startImport, toasts, dismissToast: (id: number) => setToasts((t) => t.filter((x) => x.id !== id)),
  }
}
