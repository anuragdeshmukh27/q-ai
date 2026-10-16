import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { IdeSearch, IdeTree } from '../api'
import { autoplayReduce, bannerLine, isUnsaved, type AutoplayState } from '../autoplay'
import { AutoplayBanner } from '../components/AutoplayBanner'
import { Dock } from '../components/Dock'
import { ScenarioPicker } from '../components/ScenarioPicker'
import { DebriefTab } from '../dock/DebriefTab'
import { SearchPanel, Tabs } from '../dock/IdeTab'
import { card, orderDemos } from '../demos'
import { IdeController, type IdeClient } from '../ide'
import { OfficeModel, type AgentInfo, type QEvent } from '../model'
import { deltaLabel, previousAttempt, sessionSeconds, type DebriefReport, type ScenarioInfo } from '../scenario'

const ROSTER: AgentInfo[] = [['architect', 'Aarav'], ['planner', 'Priya'], ['backend', 'Rohan'], ['database', 'Karan'], ['qa', 'Ananya'], ['reviewer', 'Vikram']].map(([id, name], i) => ({
  id, name, role: id, desk: [3 + i, 2], sprite: { palette: 'teal', accessory: 'none' },
}))

let seq = 0
const ev = (type: string, rest: Record<string, unknown> = {}, ts = 1000): QEvent => ({ seq: seq++, ts, type, ...rest })

const TREE: IdeTree = {
  role: 'backend', ready: true, task: 'h1', running: false, editable: ['backend/**', 'tests/regression/**'], names: { backend: 'Rohan', database: 'Karan' },
  files: [
    { path: 'backend/api/appointments.py', size: 10, owner: 'backend', writable: true },
    { path: 'backend/api/doctors.py', size: 10, owner: 'backend', writable: true },
    { path: 'database/migrations/0007_rename_slot_time_to_slot_at.sql', size: 10, owner: 'database', writable: false },
  ],
}
const FOUND: IdeSearch = {
  query: 'slot_time', matches: 3, files: 2, truncated: false,
  results: [
    { path: 'backend/api/doctors.py', count: 1, lines: [{ line: 95, text: 'return [row["slot_time"] for row in rows]' }] },
    { path: 'database/migrations/0007_rename_slot_time_to_slot_at.sql', count: 2, lines: [{ line: 1, text: 'ALTER TABLE appointments RENAME COLUMN slot_time TO slot_at' }] },
  ],
}
const CARD: ScenarioInfo = { id: 'opd-bookings-down', title: 'Production incident: Bookings are down', summary: 'The front desk cannot book.', role: 'backend', minutes: 25, level: 'Intermediate', channel: '#incident-opd', tests: 3, teammates: ['qa', 'architect', 'database', 'planner'] }

const started = (over: Record<string, unknown> = {}) => ev('autoplay_started', { variant: 'strong', speed: 1, rate: 1, t: 4, total: 10, labels: ['a', 'b'], task: 'h1', doc: '# Bookings fail\n\nFix the routes.', tree: TREE, ...over })
const step = (n: number, label: string, focus = 'ide') => ev('autoplay_step', { n, total: 10, label, focus })
const opened = (path: string, content: string, writable: boolean, line?: number) => ev('autoplay_open_file', { path, content, writable, ...(line ? { line } : {}) })
const FIXED = 'def booked_times():\n    return [row["slot_at"] for row in rows]\n'

/** The events of a script that opens, searches, edits and saves, as the server announces them. */
const SCRIPT: QEvent[] = [
  started(), step(1, 'Say you are on it, run the tests'), step(2, 'Search for slot_time'),
  ev('autoplay_search', { q: 'slot_time', result: FOUND }),
  step(3, 'Open the routes and migration 0007'),
  opened('backend/api/doctors.py', 'def booked_times():\n    return [row["slot_time"] for row in rows]\n', true),
  opened('database/migrations/0007_rename_slot_time_to_slot_at.sql', 'ALTER TABLE appointments RENAME COLUMN slot_time TO slot_at\n', false, 1),
  step(6, 'Fix both routes'),
  ev('autoplay_edit', { path: 'backend/api/doctors.py', content: FIXED, writable: true }),
]

function replayed(events: QEvent[]) {
  const m = new OfficeModel()
  m.setRoster(ROSTER)
  m.apply(ev('scenario_started', { scenario: CARD.id, title: CARD.title, role: 'backend', minutes: 25, channel: { id: 'incident-opd', name: '#incident-opd' }, teammates: CARD.teammates, started_at: 1000, kind: 'demo', variant: 'strong' }))
  events.forEach((e) => m.apply(e, false))
  return m
}

describe('the autoplay state follows the script', () => {
  it('starts with the task document and the tree, and counts the steps', () => {
    const a = autoplayReduce(null, started())!
    expect(a.active).toBe(true); expect(a.variant).toBe('strong'); expect(a.doc).toContain('Fix the routes.'); expect(a.ide.tree?.files).toHaveLength(3); expect(a.total).toBe(10)
    const b = autoplayReduce(a, step(4, 'Tell the team', 'chat'))!
    expect(bannerLine(b)).toBe('Strong run · step 4 of 10 · Tell the team'); expect(b.focus).toBe('chat')
    expect(autoplayReduce(null, step(1, 'x'))).toBeNull() // nothing before autoplay_started
  })

  it('opens a file as a tab (a read-only one stays read-only) and shows the line a search result points at', () => {
    let a = autoplayReduce(null, started())
    for (const e of SCRIPT.slice(1, 7)) a = autoplayReduce(a, e)
    expect(a!.ide.tabs).toEqual(['backend/api/doctors.py', 'database/migrations/0007_rename_slot_time_to_slot_at.sql'])
    expect(a!.ide.open).toBe('database/migrations/0007_rename_slot_time_to_slot_at.sql'); expect(a!.ide.files['database/migrations/0007_rename_slot_time_to_slot_at.sql'].writable).toBe(false)
    expect(a!.ide.reveal).toEqual({ path: 'database/migrations/0007_rename_slot_time_to_slot_at.sql', line: 1, seq: 1 })
    expect(a!.ide.panel).toBe('search'); expect(a!.ide.query).toBe('slot_time'); expect(a!.ide.found?.matches).toBe(3)
  })

  it('shows the edited text unsaved until the server logs the save, and lists a new file in the tree', () => {
    let a = autoplayReduce(null, started())
    for (const e of SCRIPT.slice(1)) a = autoplayReduce(a, e)
    const f = a!.ide.files['backend/api/doctors.py']
    expect(f.text).toBe(FIXED); expect(isUnsaved(f)).toBe(true); expect(a!.ide.panel).toBe('files')
    a = autoplayReduce(a, ev('session_event', { id: 'E009', t: 70, kind: 'file_saved', path: 'backend/api/doctors.py', added: 1, removed: 1 }))
    expect(isUnsaved(a!.ide.files['backend/api/doctors.py'])).toBe(false); expect(a!.ide.files['backend/api/doctors.py'].saved).toBe(FIXED)
    a = autoplayReduce(a, ev('autoplay_edit', { path: 'tests/regression/test_regression_slot_at.py', content: 'def test_x(): pass\n', writable: true }))
    expect(a!.ide.tree?.files.map((x) => x.path)).toContain('tests/regression/test_regression_slot_at.py'); expect(a!.ide.files['tests/regression/test_regression_slot_at.py'].saved).toBe('')
  })

  it('ends as done, stopped or error, and keeps the mirror after the end', () => {
    let a = autoplayReduce(null, started())
    a = autoplayReduce(a, opened('backend/api/doctors.py', 'x', true))
    const done = autoplayReduce(a, ev('autoplay_ended', { reason: 'done' }))!
    expect(done.active).toBe(false); expect(done.ended).toBe('done'); expect(done.ide.tabs).toHaveLength(1)
    expect(autoplayReduce(a, ev('autoplay_ended', { reason: 'error', error: 'boom' }))).toMatchObject({ ended: 'error', error: 'boom' })
    expect(autoplayReduce(a, ev('autoplay_speed', { speed: 2, rate: 2, t: 90 }))).toMatchObject({ speed: 2, rate: 2 })
  })

  it('ends in the same state when the events arrive again (a reconnect, a catch-up burst, a replay)', () => {
    const once = replayed(SCRIPT).autoplay
    const twice = replayed([...SCRIPT, ...SCRIPT.slice(1)]).autoplay
    expect(twice!.ide.files).toEqual(once!.ide.files); expect(twice!.ide.tabs).toEqual(once!.ide.tabs); expect(twice!.ide.open).toBe(once!.ide.open)
    const catchUp = new OfficeModel()
    catchUp.setRoster(ROSTER)
    SCRIPT.forEach((e) => catchUp.apply(e, false))
    expect(catchUp.autoplay!.ide.files).toEqual(once!.ide.files)
  })
})

describe('the IDE controller shows the mirror without asking the server', () => {
  const quiet = () => {
    const calls: string[] = []
    const client: IdeClient = {
      tree: async () => (calls.push('tree'), TREE), read: async (_r, p) => (calls.push(`read ${p}`), { path: p, content: '' }), write: async (_r, p) => (calls.push(`write ${p}`), { path: p }),
      runTests: async () => (calls.push('tests'), { started: true }), search: async () => (calls.push('search'), FOUND),
    }
    const ctl = new IdeController(client, () => {})
    ctl.setRole('backend')
    return { ctl, calls }
  }

  it('opens the tabs, the unsaved dot and the lock exactly as the script has them, with no call to the server', () => {
    const { ctl, calls } = quiet()
    ctl.follow(replayed(SCRIPT).autoplay!.ide)
    expect(ctl.tabs).toEqual(['backend/api/doctors.py', 'database/migrations/0007_rename_slot_time_to_slot_at.sql'])
    expect(ctl.open).toBe('backend/api/doctors.py'); expect(ctl.text).toBe(FIXED); expect(ctl.isDirty('backend/api/doctors.py')).toBe(true)
    expect(ctl.writable('database/migrations/0007_rename_slot_time_to_slot_at.sql')).toBe(false); expect(ctl.query).toBe('slot_time'); expect(ctl.found?.matches).toBe(3)
    expect(calls).toEqual([])
    expect(renderToStaticMarkup(<Tabs ctl={ctl} tree={TREE} onPick={() => {}} onClose={() => {}} />)).toContain('Unsaved changes')
  })

  it('clears the dot when the save is logged and follows the next state (idempotent)', () => {
    const { ctl } = quiet()
    const m = replayed(SCRIPT)
    ctl.follow(m.autoplay!.ide)
    m.apply(ev('session_event', { id: 'E010', t: 71, kind: 'file_saved', path: 'backend/api/doctors.py', added: 1, removed: 1 }), false)
    ctl.follow(m.autoplay!.ide)
    ctl.follow(m.autoplay!.ide)
    expect(ctl.isDirty('backend/api/doctors.py')).toBe(false); expect(ctl.dirty).toEqual([])
  })

  it('puts the script\'s search in the box and its result in the panel', () => {
    const { ctl } = quiet()
    ctl.follow(replayed(SCRIPT).autoplay!.ide)
    const html = renderToStaticMarkup(<SearchPanel ctl={ctl} tree={TREE} box={{ current: null }} onPick={() => {}} follow />)
    expect(html).toContain('value="slot_time"'); expect(html).toContain('readOnly=""'); expect(html).toContain('3 matches in 2 files'); expect(html).toContain('🔒')
  })
})

describe('the banner', () => {
  const live = () => replayed(SCRIPT.slice(0, 3)).autoplay!

  it('says Autoplay demo with the step, the speed switch and a Stop button the whole time it runs', () => {
    const html = renderToStaticMarkup(<AutoplayBanner auto={live()} onStop={() => {}} onSpeed={() => {}} />)
    expect(html).toContain('Autoplay demo'); expect(html).toContain('Strong run · step 2 of 10 · Search for slot_time'); expect(html).toContain('Stop')
    expect(html).toContain('aria-label="Autoplay speed"'); expect(html).toMatch(/aria-pressed="true"[^>]*>1×/); expect(html).toMatch(/aria-pressed="false"[^>]*>2×/)
  })

  it('has no Stop once the run ended, and says why an error ended it', () => {
    const done = autoplayReduce(live(), ev('autoplay_ended', { reason: 'done' }))!
    const html = renderToStaticMarkup(<AutoplayBanner auto={done} onStop={() => {}} onSpeed={() => {}} />)
    expect(html).not.toContain('Stop'); expect(html).toContain('finished'); expect(html).not.toContain('Autoplay speed')
    const bad = autoplayReduce(live(), ev('autoplay_ended', { reason: 'error', error: 'RuntimeError: the submit was not accepted' }))!
    expect(renderToStaticMarkup(<AutoplayBanner auto={bad} />)).toContain('the submit was not accepted')
  })

  it('shows a Stop as stopped at its step, in the calm colour, and only an error as failed', () => {
    const stopped = autoplayReduce(live(), ev('autoplay_ended', { reason: 'stopped' }))!
    const html = renderToStaticMarkup(<AutoplayBanner auto={stopped} onStop={() => {}} onSpeed={() => {}} />)
    expect(html).toContain('Strong run · stopped at step 2 of 10'); expect(html).not.toContain('finished'); expect(html).not.toContain('failed')
    expect(html).not.toContain('Stop</button>'); expect(html).not.toContain('var(--bad)'); expect(html).toContain('width:20%')
    const bad = autoplayReduce(live(), ev('autoplay_ended', { reason: 'error', error: 'RuntimeError: boom' }))!
    const failed = renderToStaticMarkup(<AutoplayBanner auto={bad} />)
    expect(failed).toContain('The scripted run failed: RuntimeError: boom'); expect(failed).toContain('var(--bad)')
  })

  it('is labelled as a recording in a replay and cannot be stopped there', () => {
    const html = renderToStaticMarkup(<AutoplayBanner auto={live()} replay onStop={() => {}} onSpeed={() => {}} />)
    expect(html).toContain('Recorded autoplay demo'); expect(html).not.toContain('Stop'); expect(html).not.toContain('Autoplay speed')
  })
})

describe('Watch a run on the scenario card', () => {
  it('offers a strong and a weak run, enabled, next to Start the incident', () => {
    const html = renderToStaticMarkup(<ScenarioPicker scenarios={[CARD]} busy={false} onStart={() => {}} onWatch={() => {}} />)
    expect(html).toContain('Start the incident'); expect(html).toContain('WATCH A RUN'); expect(html).toContain('Strong run'); expect(html).toContain('Weak run'); expect(html).toContain('does not count in your attempts')
    expect(html).not.toContain('disabled=""')
  })

  it('is not there without a handler and is disabled while a run is starting', () => {
    expect(renderToStaticMarkup(<ScenarioPicker scenarios={[CARD]} busy={false} onStart={() => {}} />)).not.toContain('Watch a run')
    expect(renderToStaticMarkup(<ScenarioPicker scenarios={[CARD]} busy onStart={() => {}} onWatch={() => {}} />)).toMatch(/<button[^>]*disabled[^>]*>Strong run/)
  })
})

describe('the dock in a replay of an autoplay recording', () => {
  const dock = (m: OfficeModel, replay: boolean) => renderToStaticMarkup(<Dock model={m} projectId="p1" replay={replay} onDecide={() => {}} ticker="" onSubmit={async () => {}} onError={() => {}} onPost={async () => {}} onTryAgain={async () => {}} busy={false} />)

  it('shows the IDE and the Debrief tab of a recorded autoplay run, which a plain replay never has', () => {
    const m = replayed([...SCRIPT, ev('debrief_started', { attempt: 1, judges: [] })])
    const html = dock(m, true)
    expect(html).toContain('>IDE<'); expect(html).toContain('>Debrief'); expect(html).toContain('data-testid="ide-host"')
    expect(html).not.toContain('The IDE is for a live Simulation build')
    const plain = new OfficeModel()
    plain.setRoster(ROSTER)
    plain.setHumanRoles(['backend'])
    plain.apply(ev('debrief_started', { attempt: 1, judges: [] }))
    const old = dock(plain, true)
    expect(old).not.toContain('>IDE<'); expect(old).not.toContain('>Debrief'); expect(old).not.toContain('ide-host') // Hackathon v2 and the other recordings are unchanged
  })

  it('shows the IDE for a live autoplay run before any person plays a role', () => {
    const m = replayed(SCRIPT)
    expect(dock(m, false)).toContain('>IDE<')
  })
})

describe('the session timer of an autoplay run', () => {
  it('follows the run\'s own clock, not the wall clock, and stops at the end', () => {
    const s = { startedAt: 1000, endedAt: null, clock: { t: 60, atMs: 5_000_000, rate: 2 }, finishedT: null }
    expect(sessionSeconds(s, 5_000_000)).toBe(60); expect(sessionSeconds(s, 5_010_000)).toBe(80)
    expect(sessionSeconds({ ...s, endedAt: 9e9, finishedT: 192.4 }, 6_000_000)).toBe(192.4)
    expect(sessionSeconds({ startedAt: 1000, endedAt: null }, 1_100_000)).toBe(100) // a person's session still runs on the wall clock
  })

  it('anchors on the autoplay start, a change of speed and every logged event, and freezes at session_finished', () => {
    const m = replayed([started({ t: 4, rate: 2 })])
    expect(m.scenario?.clock).toMatchObject({ t: 4, rate: 2 })
    m.apply(ev('autoplay_speed', { speed: 2, rate: 4, t: 50 }), false)
    expect(m.scenario?.clock).toMatchObject({ t: 50, rate: 4 })
    m.apply(ev('session_event', { id: 'E020', t: 91.5, kind: 'test_run' }), false)
    expect(m.scenario?.clock?.t).toBe(91.5)
    m.apply(ev('session_event', { id: 'E021', t: 200.2, kind: 'session_finished', ok: true }), false)
    expect(m.scenario?.finishedT).toBe(200.2); expect(sessionSeconds(m.scenario, Date.now() + 99_000)).toBe(200.2)
  })
})

describe('a demo is marked and is no attempt of yours', () => {
  const REPORT = (over: Partial<DebriefReport>): DebriefReport => ({
    version: 1, scenario: CARD.id, title: CARD.title, project: 'p', attempt: 2, kind: 'demo', variant: 'strong', total: 100, max: 100, elapsed: 190, minutes: 25, rubric: { id: 'r', version: 1 },
    criteria: [], rows: [], events: {}, fairness: { points: 0, quoted: 0, matched: 0, dropped: [], ai_rejected: [], tests_rerun: null, rubric: 'v1', voices: { judges: 'template', coach: 'template', reason: '' } },
    focus: ['Full marks already.'], coach: { text: 'x', source: 'template' }, judge_lines: {},
    attempts: [{ attempt: 1, total: 30, kind: 'demo', variant: 'weak', scores: {}, project: 'p0', finished_at: '', elapsed: 400 }, { attempt: 2, total: 100, kind: 'demo', variant: 'strong', scores: {}, project: 'p', finished_at: '', elapsed: 190 }],
    files: { md: '', json: '' }, ...over,
  })
  const render = (r: DebriefReport) => {
    const m = new OfficeModel()
    m.setRoster(ROSTER)
    m.apply(ev('debrief_started', { attempt: r.attempt, judges: [] }))
    m.apply(ev('debrief_report', { report: r }))
    return renderToStaticMarkup(<DebriefTab model={m} projectId="p1" onTryAgain={() => {}} />)
  }

  it('shows a demo chip, labels the bars and hides Try again for a demo', () => {
    const html = render(REPORT({}))
    expect(html).toContain('demo · strong run'); expect(html).toContain('Demo 2: 100'); expect(html).not.toContain('Try again'); expect(html).not.toContain('attempt 2 ·')
  })

  it('keeps Try again and the attempt label for the learner\'s own report', () => {
    const own = REPORT({ kind: 'learner', variant: '', attempts: [{ attempt: 1, total: 60, scores: {}, project: 'p0', finished_at: '', elapsed: 400 }, { attempt: 2, total: 80, scores: {}, project: 'p', finished_at: '', elapsed: 300 }], total: 80 })
    const html = render(own)
    expect(html).toContain('Try again'); expect(html).toContain('attempt 2 ·'); expect(html).not.toContain('demo ·')
  })

  it('compares a demo with nothing, and a learner attempt only with the learner\'s own attempts', () => {
    expect(previousAttempt(REPORT({}))).toBeNull(); expect(deltaLabel(REPORT({}))).toBe('')
    const mixed = REPORT({ kind: 'learner', attempt: 2, total: 80, attempts: [{ attempt: 1, total: 99, kind: 'demo', scores: {}, project: '', finished_at: '', elapsed: 1 }, { attempt: 2, total: 80, scores: {}, project: '', finished_at: '', elapsed: 1 }] })
    expect(previousAttempt(mixed)).toBeNull()
  })

  it('puts a demo chip in the model from scenario_started', () => {
    const m = replayed([])
    expect(m.scenario).toMatchObject({ kind: 'demo', variant: 'strong' })
  })
})

describe('the Demo picker card of a recorded simulation', () => {
  it('lists the recording after the shipped ones with its own title', () => {
    const rec = (name: string, extra: Record<string, unknown> = {}) => ({ name, goal: 'Production incident: Bookings are down', ok: true, seconds: 215, events: 3000, ...extra })
    const ordered = orderDemos([rec('simulation-bookings-down-strong', { title: 'Simulation: Bookings are down (strong)', app: 'Hospital OPD', feature: 'Strong run: 100/100', kind: 'scenario' }), rec('flagship'), rec('calculator-fault')])
    expect(ordered.map((r) => r.name)).toEqual(['calculator-fault', 'flagship', 'simulation-bookings-down-strong'])
    expect(card(ordered[2])).toMatchObject({ title: 'Simulation: Bookings are down (strong)', duration: '3 min 35 s', stats: '' })
  })
})

describe('unrelated events leave the autoplay state alone', () => {
  it('is a no-op for a session without a script', () => {
    const m = new OfficeModel()
    m.setRoster(ROSTER)
    m.apply(ev('session_event', { id: 'E001', t: 1, kind: 'file_saved', path: 'x' }), false)
    expect(m.autoplay).toBeNull()
    const a: AutoplayState | null = autoplayReduce(null, ev('channel_message', { id: 'C1' }))
    expect(a).toBeNull()
  })
})
