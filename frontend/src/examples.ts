// Example goals offered as chips. Every one of these was built end to end by the team on the local 7B model
// (see PROGRESS.md, generality check); the bookmark manager with tags is deliberately not listed: it never passed.
export interface Example {
  label: string
  goal: string
}

export const EXAMPLES: Example[] = [
  { label: 'calculator with history', goal: 'Build a calculator with history' },
  { label: 'todo app with priorities', goal: 'Build a todo app with priorities' },
  { label: 'expense tracker', goal: 'Build an expense tracker with categories and totals' },
  { label: 'notes app with search', goal: 'Build a notes app with search' },
  { label: 'habit tracker', goal: 'Build a habit tracker' },
  { label: 'quiz app', goal: 'Build a quiz app' },
  { label: 'contact book', goal: 'Build a contact book' },
  { label: 'inventory list', goal: 'Build an inventory list' },
]
