import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { IdeSearch, IdeTree } from '../api'
import { SearchPanel, Tabs, Unsaved } from '../dock/IdeTab'
import { IdeController, type IdeClient } from '../ide'

const TREE: IdeTree = {
  role: 'backend', ready: true, task: 'h1', running: false, editable: ['backend/**', 'tests/regression/**'], names: { backend: 'Rohan', database: 'Karan' },
  files: [
    { path: 'backend/api/appointments.py', size: 10, owner: 'backend', writable: true },
    { path: 'backend/api/doctors.py', size: 10, owner: 'backend', writable: true },
    { path: 'database/migrations/0007_rename_slot_time_to_slot_at.sql', size: 10, owner: 'database', writable: false },
    { path: 'tests/regression/test_regression_x.py', size: 10, owner: 'backend', writable: true },
  ],
}
const FILES: Record<string, string> = {
  'backend/api/appointments.py': 'a1\na2\n', 'backend/api/doctors.py': 'd1\n', 'database/migrations/0007_rename_slot_time_to_slot_at.sql': 'ALTER ... slot_at\n', 'tests/regression/test_regression_x.py': 't\n',
}
const FOUND: IdeSearch = {
  query: 'slot_time', matches: 3, files: 2, truncated: false,
  results: [
    { path: 'backend/api/doctors.py', count: 1, lines: [{ line: 95, text: 'return [row["slot_time"] for row in rows]' }] },
    { path: 'database/migrations/0007_rename_slot_time_to_slot_at.sql', count: 2, lines: [{ line: 1, text: 'ALTER TABLE appointments RENAME COLUMN slot_time TO slot_at' }] },
  ],
}

function setup() {
  const calls: string[] = []
  const reads: [string, boolean][] = [] // every read the server saw: the path, and whether the IDE did it by itself
  const errors: unknown[] = []
  const client: IdeClient = {
    tree: async () => TREE,
    read: async (_r, p, auto) => (calls.push(`read ${p}`), reads.push([p, !!auto]), { path: p, content: FILES[p] }),
    write: async (_r, p, c) => (calls.push(`write ${p}`), (FILES[p] = c), { path: p }),
    runTests: async () => ({ started: true }),
    search: async (_r, q) => (calls.push(`search ${q}`), q === 'zzzz' ? { query: q, matches: 0, files: 0, truncated: false, results: [] } : FOUND),
  }
  const ctl = new IdeController(client, (e) => errors.push(e))
  ctl.setRole('backend')
  ctl.tree = TREE // the folder is loaded
  return { ctl, calls, errors, reads }
}

describe('the IDE: several files open as tabs', () => {
  it('keeps every opened file as a tab and shows the one you picked', async () => {
    const { ctl } = setup()
    await ctl.refresh()
    await ctl.openFile('backend/api/appointments.py')
    await ctl.openFile('backend/api/doctors.py')
    expect(ctl.tabs).toEqual(['backend/api/appointments.py', 'backend/api/doctors.py']); expect(ctl.open).toBe('backend/api/doctors.py')
    ctl.activate('backend/api/appointments.py')
    expect(ctl.open).toBe('backend/api/appointments.py'); expect(ctl.text).toBe('a1\na2\n')
    await ctl.openFile('backend/api/doctors.py') // already a tab: no second tab, no second read
    expect(ctl.tabs).toHaveLength(2)
  })

  it('does not read a file twice when you come back to its tab, and keeps its unsaved edit', async () => {
    const { ctl, calls } = setup()
    await ctl.openFile('backend/api/appointments.py')
    ctl.edit('changed\n')
    await ctl.openFile('backend/api/doctors.py')
    ctl.activate('backend/api/appointments.py')
    expect(ctl.text).toBe('changed\n'); expect(ctl.isDirty('backend/api/appointments.py')).toBe(true); expect(ctl.isDirty('backend/api/doctors.py')).toBe(false)
    expect(calls.filter((c) => c.startsWith('read'))).toEqual(['read backend/api/appointments.py', 'read backend/api/doctors.py'])
  })

  it('asks before you leave a file with unsaved edits for another one, and not otherwise', async () => {
    const { ctl } = setup()
    await ctl.openFile('backend/api/appointments.py')
    expect(ctl.unsavedBeforeSwitch('backend/api/doctors.py')).toBeNull()
    ctl.edit('changed\n')
    expect(ctl.unsavedBeforeSwitch('backend/api/doctors.py')).toBe('backend/api/appointments.py')
    expect(ctl.unsavedBeforeSwitch('backend/api/appointments.py')).toBeNull() // the same file: nothing is left
    await ctl.save()
    expect(ctl.unsavedBeforeSwitch('backend/api/doctors.py')).toBeNull()
  })

  it('refuses to close a tab with unsaved edits, closes it once saved, and discards on request', async () => {
    const { ctl } = setup()
    await ctl.openFile('backend/api/appointments.py')
    await ctl.openFile('backend/api/doctors.py')
    ctl.edit('x\n')
    expect(ctl.closeTab('backend/api/doctors.py')).toBe(false); expect(ctl.tabs).toHaveLength(2)
    await ctl.save('backend/api/doctors.py')
    expect(ctl.closeTab('backend/api/doctors.py')).toBe(true); expect(ctl.tabs).toEqual(['backend/api/appointments.py']); expect(ctl.open).toBe('backend/api/appointments.py')
    ctl.edit('y\n')
    ctl.discardTab('backend/api/appointments.py')
    expect(ctl.tabs).toEqual([]); expect(ctl.open).toBe(''); expect(ctl.dirty).toEqual([])
  })

  it('shows the neighbour when the active tab is closed', async () => {
    const { ctl } = setup()
    for (const p of ['backend/api/appointments.py', 'backend/api/doctors.py', 'tests/regression/test_regression_x.py']) await ctl.openFile(p)
    ctl.activate('backend/api/doctors.py')
    ctl.closeTab('backend/api/doctors.py')
    expect(ctl.open).toBe('tests/regression/test_regression_x.py')
    ctl.closeTab('tests/regression/test_regression_x.py')
    expect(ctl.open).toBe('backend/api/appointments.py')
  })

  it('saves every tab with edits before the tests run', async () => {
    const { ctl, calls } = setup()
    await ctl.openFile('backend/api/appointments.py')
    ctl.edit('one\n')
    await ctl.openFile('backend/api/doctors.py')
    ctl.edit('two\n')
    await ctl.run()
    expect(calls.filter((c) => c.startsWith('write'))).toEqual(['write backend/api/appointments.py', 'write backend/api/doctors.py'])
  })

  it('forgets the tabs when the role changes', async () => {
    const { ctl } = setup()
    await ctl.openFile('backend/api/appointments.py')
    ctl.setRole('database')
    expect(ctl.tabs).toEqual([]); expect(ctl.open).toBe('')
  })

  it('drops a tab for a file that could not be read', async () => {
    const { ctl, errors } = setup()
    await ctl.openFile('backend/api/appointments.py')
    const read = (ctl as unknown as { client: IdeClient }).client.read
    ;(ctl as unknown as { client: IdeClient }).client.read = async (r, p) => (p === 'gone.py' ? Promise.reject(new Error('file not found')) : read(r, p))
    await ctl.openFile('gone.py')
    expect(ctl.tabs).toEqual(['backend/api/appointments.py']); expect(ctl.open).toBe('backend/api/appointments.py'); expect(errors).toHaveLength(1)
  })
})

describe('picking a file is logged as the learner’s own open', () => {
  it('tells the server once when you pick the file the IDE had shown by itself', async () => {
    const { ctl, reads } = setup()
    await ctl.openFile('backend/api/appointments.py', true) // the IDE's first file
    expect(reads).toEqual([['backend/api/appointments.py', true]])
    await ctl.pick('backend/api/appointments.py') // the learner clicks the tab or the tree entry of the file that is open
    await ctl.pick('backend/api/appointments.py')
    expect(reads).toEqual([['backend/api/appointments.py', true], ['backend/api/appointments.py', false]]) // logged as theirs, once
  })

  it('opens a file that is not a tab yet with a read the server logs as the learner’s, and does not read it again for its tab', async () => {
    const { ctl, reads } = setup()
    await ctl.pick('backend/api/doctors.py')
    await ctl.openFile('backend/api/appointments.py')
    ctl.activate('backend/api/doctors.py')
    await ctl.pick('backend/api/doctors.py')
    expect(reads).toEqual([['backend/api/doctors.py', false], ['backend/api/appointments.py', false]])
  })

  it('shows the line of a search result in a tab that is open already, and logs that pick too', async () => {
    const { ctl, reads } = setup()
    await ctl.openFile('backend/api/doctors.py', true)
    await ctl.openFile('backend/api/appointments.py', true)
    await ctl.openAt('backend/api/doctors.py', 95)
    expect(ctl.open).toBe('backend/api/doctors.py'); expect(ctl.reveal).toMatchObject({ path: 'backend/api/doctors.py', line: 95 })
    expect(reads.filter(([, auto]) => !auto)).toEqual([['backend/api/doctors.py', false]])
  })

  it('forgets what was picked when the role changes', async () => {
    const { ctl, reads } = setup()
    await ctl.pick('backend/api/doctors.py')
    ctl.setRole('database')
    ctl.setRole('backend')
    await ctl.openFile('backend/api/doctors.py', true)
    await ctl.pick('backend/api/doctors.py')
    expect(reads.map(([, auto]) => auto)).toEqual([false, true, false])
  })
})

describe('the tab bar and the question about unsaved edits', () => {
  it('shows a tab per file with a dot for unsaved edits, a lock for read-only files and a close button', async () => {
    const { ctl } = setup()
    await ctl.refresh()
    await ctl.openFile('backend/api/appointments.py')
    await ctl.openFile('database/migrations/0007_rename_slot_time_to_slot_at.sql')
    ctl.activate('backend/api/appointments.py')
    ctl.edit('x\n')
    const html = renderToStaticMarkup(<Tabs ctl={ctl} tree={TREE} onPick={() => {}} onClose={() => {}} />)
    expect(html).toContain('aria-label="Open files"'); expect(html).toContain('>appointments.py<'); expect(html).toContain('0007_rename_slot_time_to_slot_at.sql<')
    expect(html.match(/aria-label="Unsaved changes"/g)?.length).toBe(1); expect(html.match(/aria-label="read-only"/g)?.length).toBe(1)
    expect(html).toContain('aria-label="Close appointments.py"'); expect(html).toMatch(/aria-selected="true"[^>]*title="backend\/api\/appointments.py"|title="backend\/api\/appointments.py"[^>]*aria-selected="true"/)
    expect(renderToStaticMarkup(<Tabs ctl={setup().ctl} tree={TREE} onPick={() => {}} onClose={() => {}} />)).toBe('')
  })

  it('offers save, keep unsaved or cancel when switching, and save, discard or cancel when closing', () => {
    const sw = renderToStaticMarkup(<Unsaved pending={{ kind: 'switch', from: 'backend/api/appointments.py', target: 'backend/api/doctors.py' }} onAnswer={() => {}} />)
    expect(sw).toContain('role="alertdialog"'); expect(sw).toContain('appointments.py'); expect(sw).toContain('has changes that are not saved'); expect(sw).toContain('Save and switch')
    expect(sw).toContain('Switch, keep unsaved'); expect(sw).toContain('Cancel'); expect(sw).not.toContain('Discard')
    const close = renderToStaticMarkup(<Unsaved pending={{ kind: 'close', path: 'backend/api/doctors.py' }} onAnswer={() => {}} />)
    expect(close).toContain('Save and close'); expect(close).toContain('Discard changes'); expect(close).toContain('Cancel'); expect(close).not.toContain('keep unsaved')
  })
})

describe('project-wide search', () => {
  it('searches the server, keeps the answer, and a short query searches nothing', async () => {
    const { ctl, calls } = setup()
    ctl.setRole('backend')
    await ctl.search('slot_time')
    expect(ctl.found?.matches).toBe(3); expect(calls).toContain('search slot_time'); expect(ctl.searching).toBe(false)
    await ctl.search(' s ')
    expect(ctl.found).toBeNull(); expect(calls.filter((c) => c.startsWith('search'))).toHaveLength(1)
    await ctl.search('zzzz')
    expect(ctl.found?.matches).toBe(0)
  })

  it('opens a result at its line, in a tab, and asks the editor to show the line', async () => {
    const { ctl } = setup()
    await ctl.openAt('database/migrations/0007_rename_slot_time_to_slot_at.sql', 1)
    expect(ctl.open).toBe('database/migrations/0007_rename_slot_time_to_slot_at.sql'); expect(ctl.tabs).toHaveLength(1); expect(ctl.reveal).toMatchObject({ path: ctl.open, line: 1, seq: 1 })
    await ctl.openAt('backend/api/doctors.py', 95)
    expect(ctl.reveal).toMatchObject({ path: 'backend/api/doctors.py', line: 95, seq: 2 })
  })

  it('lists the results by file and line, with a lock on read-only files', async () => {
    const { ctl } = setup()
    await ctl.search('slot_time')
    const html = renderToStaticMarkup(<SearchPanel ctl={ctl} tree={TREE} box={{ current: null }} onPick={() => {}} />)
    expect(html).toContain('aria-label="Search all files"'); expect(html).toContain('3 matches in 2 files')
    expect(html).toContain('backend/api/doctors.py'); expect(html).toContain('>95<'); expect(html).toContain('row[&quot;slot_time&quot;]'); expect(html).toContain('title="backend/api/doctors.py:95"')
    expect(html).toContain('0007_rename_slot_time_to_slot_at.sql'); expect(html).toContain('… 1 more in this file')
    expect(html.match(/aria-label="read-only"/g)?.length).toBe(1) // the migration is the only read-only file in the results
  })

  it('says so when nothing matched, and explains the box before the first search', async () => {
    const { ctl } = setup()
    expect(renderToStaticMarkup(<SearchPanel ctl={ctl} tree={TREE} box={{ current: null }} onPick={() => {}} />)).toContain('the read-only ones too')
    await ctl.search('zzzz')
    expect(renderToStaticMarkup(<SearchPanel ctl={ctl} tree={TREE} box={{ current: null }} onPick={() => {}} />)).toContain('No match for “zzzz”.')
  })
})
