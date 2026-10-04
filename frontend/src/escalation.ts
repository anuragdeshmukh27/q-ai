// Plain-words text for "an employee needs you": what happened, and what the human can do about it.

export interface Escalation {
  agent: string // employee id, or 'team'
  reason: string
  detail: string
  task: string
}

export type EscalationAction = 'retry' | 'replan' | 'stop'

export const ESCALATION_BUTTONS: { action: EscalationAction; label: string; hint: string }[] = [
  { action: 'retry', label: 'Retry this step', hint: 'The same employee tries the step again with fresh attempts.' },
  { action: 'replan', label: 'Re-plan', hint: 'The Planner splits the step differently, then the team continues.' },
  { action: 'stop', label: 'Stop build', hint: 'Stop here. Nothing already merged is lost.' },
]

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

/** One or two sentences a non-technical judge can read: what went wrong, in the employee's name. */
export function explainEscalation(e: Escalation, name: string): string {
  const detail = clip(e.detail.trim(), 160)
  switch (e.reason) {
    case 'max_iterations':
      return `${name} used all their attempts on this step and it is still not finished.`
    case 'no_improvement':
      return `${name} ran the tests again and again, and the same ones kept failing, so they stopped instead of going in circles.`
    case 'repeated_action':
      return `${name} got stuck repeating the same move, so they stopped.`
    case 'invalid_output':
      return `The AI model behind ${name} kept answering in a form Q cannot read.`
    case 'no_valid_output':
      return `${name} could not produce a plan or design that passes Q's checks after three tries${detail ? `: ${detail}` : ''}.`
    case 'model_unavailable':
      return `The AI model for ${name} could not be reached${detail ? ` (${detail})` : ''}. Check that Ollama is running.`
    case 'review_unresolved':
      return `The reviewer still asks for changes after several rounds, so ${name}'s work was not accepted yet.`
    case 'merge_conflict':
      return `Two employees changed the same lines and the merge needs a decision${detail ? `: ${detail}` : ''}.`
    case 'waiting_human':
      return `${name} has a question for you${detail ? `: ${detail}` : '.'}`
    default:
      return `${name} could not finish this step${detail ? `: ${detail}` : ''}.`
  }
}

export const ESCALATION_CHOICES = 'You can retry this step, re-plan it, or stop the build.'
