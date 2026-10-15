// What the pages show when the server answers a write request. One case per run:
//   node tests/ui/refusals.mjs '{"case": "create", "status": 409, "body": {"detail": "Slot already booked"}}'
// The case is the way a request is made: create (the New appointment form), edit (the pencil), action (the Complete / Cancel buttons), delete (the bin) or board (a card moved on the board).
// The answer is what the server sent: `status` and either `body` (JSON) or `text` (not JSON). Prints one line of JSON for the test to check:
//   { formOpen, formError, saveEnabled, toasts: [{kind, text}], writes: [{method, url, body}], reloaded }
import { createBrowser } from './fakedom.mjs'

const given = JSON.parse(process.argv[2] ?? '{}')
const doctor = (id, name) => ({ id, name, department: 'Pediatrics', phone: '8408975520', email: `user${id}@example.com`, consultation_fee: 250, room: 'OPD 305', availability: 'Available', created_at: '2026-10-10 08:00:00' })
const visit = (id, doctor_id, who, time, status) => ({ id, doctor_id, patient_name: who, patient_phone: '9812345678', date: '2026-10-15', time, slot_at: time, reason: 'Follow-up', status, created_at: '2026-10-10 08:30:00', cancel_reason: null })
const DOCTORS = [doctor(1, 'Dr. Farhan Ali'), doctor(2, 'Dr. Vikram Shah')]
const VISITS = { 1: [visit(1, 1, 'Sana Sheikh', '11:00', 'Booked'), visit(2, 1, 'Arjun Nair', '12:00', 'Completed')], 2: [visit(3, 2, 'Kavita Patil', '09:30', 'Booked')] }

// reads are always answered; the first write of the run gets the server's answer under test
const route = (method, url) => {
  if (method !== 'GET') return { status: given.status, body: given.body, text: given.text }
  const kids = url.match(/^\/api\/doctors\/(\d+)\/(appointments|prescriptions|lab_tests)$/)
  if (url === '/api/doctors') return { status: 200, body: { items: DOCTORS } }
  if (kids) return { status: 200, body: { items: kids[2] === 'appointments' ? VISITS[kids[1]] : [] } }
  return { status: 404, body: { detail: 'Not found' } }
}
const b = await createBrowser(route)
const { html, view, go, flush } = b
const press = async (node) => { await node.click(); await flush(); await flush() }
const button = (pred) => html.querySelectorAll('button').find(pred)
const fill = (name, value) => { html.querySelector('#f-' + name).value = value }

await go('#/appointments')
const before = b.calls.length
if (given.case === 'create') {
  await press(button((x) => x.textContent.startsWith('+ New')))
  fill('patient_name', 'Meera Joshi'); fill('patient_phone', given.phone ?? '9812345678'); fill('date', '2026-10-15'); fill('time', '11:00'); fill('reason', 'Check-up'); fill('status', 'Booked')
  await html.querySelector('form').fire('submit'); await flush(); await flush()
} else if (given.case === 'edit') {
  await press(view().querySelectorAll('button').find((x) => x.attrs['aria-label'] === 'Edit'))
  fill('time', '12:00')
  await html.querySelector('form').fire('submit'); await flush(); await flush()
} else if (given.case === 'action') {
  await press(view().querySelectorAll('button[data-action="cancel"]').find((x) => !x.disabled))
} else if (given.case === 'delete') {
  await press(view().querySelectorAll('button').find((x) => x.attrs['aria-label'] === 'Delete'))
  await press(button((x) => x.className === 'btn-danger'))
} else if (given.case === 'board') {
  await press(view().querySelector('#view-board'))
  const card = view().querySelectorAll('.q-kcard').find((c) => c.querySelector('select'))
  const sel = card.querySelector('select')
  sel.value = 'Cancelled'
  await sel.fire('change'); await flush(); await flush()
} else {
  throw new Error('unknown case ' + given.case)
}
const form = html.querySelector('form')
const error = html.querySelector('#form-error')
const save = form && form.querySelectorAll('button').find((x) => x.type === 'submit')
console.log(JSON.stringify({
  formOpen: !!form,
  formError: error ? error.textContent : '',
  saveEnabled: save ? !save.disabled : null,
  toasts: b.toasts(),
  writes: b.calls.filter((c) => c.method !== 'GET'),
  reloaded: b.calls.slice(before).filter((c) => c.method === 'GET').length,
}))
