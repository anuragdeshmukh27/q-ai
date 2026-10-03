// Example goals offered as chips. They are detailed on purpose: a goal that names its fields and option labels is followed as written.
// Every goal here was built end to end by the team on the local 7B model (see PROGRESS.md); the same list lives in scripts/goals.py.
// The habit tracker and quiz goals are deliberately not listed: their one run failed. The last four are related resources (parent and child, votes, sort).
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
  { label: 'reddit replica', goal: 'Build a reddit-style forum: posts with title, content and author, comments on each post, upvote and downvote posts, sort by top or newest, edit and delete' },
  { label: 'blog with comments', goal: 'Build a blog: posts with title, content and author, readers add comments to a post, edit and delete posts and comments' },
  { label: 'Q&A forum', goal: 'Build a Q&A forum: questions with title, details and author, answers to each question, upvote questions and answers, sort by top or newest' },
  { label: 'project tasks', goal: 'Build a project tracker: projects with name and description, tasks for each project with title and status To do/In progress/Done, edit and delete' },
]
