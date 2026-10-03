// Example goals offered as chips. They are detailed on purpose: a goal that names its fields and option labels is followed as written.
// Every goal here was built end to end by the team on the local 7B model (see PROGRESS.md); the same list lives in scripts/goals.py.
// The habit tracker and quiz goals are deliberately not listed: their one run failed.
export interface Example {
  label: string
  goal: string
}

export const EXAMPLES: Example[] = [
  { label: 'calculator with history', goal: 'Build a calculator with history: add, subtract, multiply and divide two numbers, show the result, keep a history list, clear the history' },
  { label: 'todo app', goal: 'Build a todo app: title, description, priority Low/Medium/High, due date, mark as done, filter by status, edit and delete' },
  { label: 'expense tracker', goal: 'Build an expense tracker: description, amount, category Food/Transport/Housing/Fun/Other, date, total spent, filter by category, edit and delete' },
  { label: 'notes app', goal: 'Build a notes app: title, content, tag Work/Personal/Ideas, search by text, edit and delete' },
  { label: 'contact book', goal: 'Build a contact book: name, phone, email, group Family/Friends/Work, search by name, edit and delete' },
  { label: 'inventory list', goal: 'Build an inventory list: item name, quantity, location Warehouse/Shop/Home, status In stock/Low/Out of stock, edit and delete' },
]
