import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { RecordingMeta } from '../api'
import { LeftPanel } from '../components/LeftPanel'
import { TopBar } from '../components/TopBar'
import { card, demoModeTip, demosFor, modeIdleReason, orderDemos, pickDefault } from '../demos'
import { OfficeModel } from '../model'

const rec = (name: string, extra: Partial<RecordingMeta> = {}): RecordingMeta => ({ name, goal: 'Build a todo app: title', ok: true, seconds: 185, events: 10, ...extra })
const SIM = rec('simulation-bookings-down-strong', { goal: 'Production incident: Bookings are down', title: 'Simulation: Bookings are down (strong)', app: 'Hospital OPD', feature: 'Strong run', kind: 'scenario', variant: 'strong', seconds: 193 })
const BUILDS = [rec('hackathon-platform-v2', { title: 'Hackathon platform v2' }), rec('calculator-fault', { title: 'Calculator with a fault' }), rec('uber', { title: 'Uber' })]
const ALL = [...BUILDS, SIM]

const bar = (over: Record<string, unknown> = {}) =>
  renderToStaticMarkup(
    <TopBar title="" build={0} percent={0} hasProject={false} active={0} total={0} mode="supervised" onMode={() => {}} demo onDemo={() => {}} speed={1} onSpeed={() => {}} metrics={null} appUrl="" cost={null} connected done={null} recordings={ALL} {...over} />,
  )
const button = (html: string, label: string) => html.match(new RegExp(`<button[^>]*>${label}</button>`))?.[0] ?? ''

const panel = (mode: string, recording: string, recordings = ALL, demo = true) =>
  renderToStaticMarkup(
    <LeftPanel model={new OfficeModel()} busy={false} demo={demo} hasProject={false} recordings={recordings} recording={recording} onRecording={() => {}} config={null} preset="fastapi-vanilla" onPreset={() => {}} fast onFast={() => {}} onStart={() => {}} onImport={() => {}} mode={mode} replay={false} projectId={null} humanRoles={['backend']} onHumanRoles={() => {}} onSubmit={async () => {}} onCopyPath={() => {}} scenarios={[]} onScenario={() => {}} />,
  )

describe('the autonomy switch filters the recordings in Demo mode', () => {
  it('Simulation shows the simulation recordings, the other modes the recorded builds', () => {
    expect(demosFor(ALL, 'simulation').map((r) => r.name)).toEqual(['simulation-bookings-down-strong'])
    for (const m of ['assisted', 'supervised', 'autonomous']) expect(demosFor(ALL, m).map((r) => r.name)).toEqual(['calculator-fault', 'hackathon-platform-v2', 'uber'])
  })
  it('leaves the build recordings as they were: the same cards in the same order, none tagged', () => {
    expect(demosFor(ALL, 'supervised').map((r) => r.name)).toEqual(orderDemos(BUILDS).map((r) => r.name))
    expect(demosFor(BUILDS, 'supervised')).toEqual(orderDemos(BUILDS))
    expect(pickDefault(BUILDS)).toBe('calculator-fault')
    expect(pickDefault(ALL, 'supervised')).toBe('calculator-fault')
    expect(demosFor(BUILDS, 'supervised').map((r) => card(r).simulation)).toEqual([false, false, false])
  })
  it('each mode starts on its own recording', () => {
    expect(pickDefault(ALL, 'simulation')).toBe('simulation-bookings-down-strong')
    expect(pickDefault(BUILDS, 'simulation')).toBe('')
  })
  it('lists a failed simulation recording nowhere', () => {
    expect(demosFor([...BUILDS, { ...SIM, ok: false }], 'simulation')).toEqual([])
  })
})

describe('the recorded builds list in Demo mode', () => {
  it('shows only the build recordings in Supervised, without a Simulation tag', () => {
    const html = panel('supervised', 'calculator-fault')
    expect(html).toContain('CHOOSE A RECORDED BUILD'); expect(html).toContain('Hackathon platform v2'); expect(html).toContain('Uber')
    expect(html).not.toContain('Bookings are down'); expect(html).not.toContain('SIMULATION')
  })
  it('shows "Simulation: Bookings are down (strong)" with a Simulation tag in Simulation, and no build', () => {
    const html = panel('simulation', 'simulation-bookings-down-strong')
    expect(html).toContain('CHOOSE A RECORDED BUILD'); expect(html).toContain('Simulation: Bookings are down (strong)'); expect(html).toContain('SIMULATION')
    expect(html).toContain('3 min 13 s'); expect(html).not.toContain('Hackathon platform v2'); expect(html).not.toContain('Uber')
    expect(html).toContain('Production incident: Bookings are down') // the goal box of the chosen recording
    expect(html).toMatch(/<button[^>]*>▶ Play demo<\/button>/)
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>▶ Play demo/)
  })
  it('says so when there is no recorded simulation, and keeps Play off', () => {
    const html = panel('simulation', '', BUILDS)
    expect(html).toContain('No recorded simulations yet'); expect(html).toMatch(/<button[^>]*disabled=""[^>]*>▶ Play demo/)
  })
  it('outside Demo mode the live panel is as before', () => {
    const html = panel('supervised', '', ALL, false)
    expect(html).not.toContain('CHOOSE A RECORDED BUILD'); expect(html).toContain('Build it')
  })
})

describe('the autonomy buttons in Demo mode', () => {
  it('stay enabled while there is something to show, and say what they show', () => {
    const html = bar()
    for (const m of ['Assisted', 'Supervised', 'Autonomous', 'Simulation']) expect(button(html, m)).not.toContain('disabled')
    expect(button(html, 'Simulation')).toContain('title="Demo mode: show the recorded simulations"')
    expect(button(html, 'Assisted')).toContain('title="Demo mode: show the recorded builds"')
  })
  it('a mode with no recording is disabled, with the reason as its tooltip', () => {
    const noSim = bar({ recordings: BUILDS })
    expect(button(noSim, 'Simulation')).toMatch(/disabled=""/); expect(button(noSim, 'Simulation')).toContain('title="Demo mode: there are no recorded simulations to show"')
    expect(button(noSim, 'Supervised')).not.toContain('disabled')
    const noBuild = bar({ recordings: [SIM] })
    for (const m of ['Assisted', 'Supervised', 'Autonomous']) { expect(button(noBuild, m)).toMatch(/disabled=""/); expect(button(noBuild, m)).toContain('there are no recorded builds to show') }
    expect(button(noBuild, 'Simulation')).not.toContain('disabled')
  })
  it('are untouched outside Demo mode: always enabled, no Demo tooltip', () => {
    const html = bar({ demo: false, recordings: BUILDS })
    for (const m of ['Assisted', 'Supervised', 'Autonomous', 'Simulation']) { expect(button(html, m)).not.toContain('disabled'); expect(button(html, m)).not.toContain('title=') }
    expect(modeIdleReason(BUILDS, 'simulation')).not.toBe(''); expect(demoModeTip(ALL, 'simulation')).toContain('recorded simulations')
  })
})

describe('the replay speed switch', () => {
  it('keeps 1×, 2× and 4× in Demo mode whichever mode is on, including for the simulation recording', () => {
    for (const mode of ['supervised', 'simulation']) {
      const html = bar({ mode, speed: 2 })
      const group = html.match(/aria-label="Replay speed">(.*?)<\/div>/)?.[1] ?? ''
      expect(group).toContain('>1×<'); expect(group).toContain('>2×<'); expect(group).toContain('>4×<')
      expect(group).toMatch(/aria-pressed="true"[^>]*>2×/)
    }
  })
  it('is hidden when Demo mode is off', () => {
    expect(bar({ demo: false })).not.toContain('Replay speed')
  })
})
