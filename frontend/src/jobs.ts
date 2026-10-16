// Job descriptions (Simulation mode): the types the JD box, the task panel and the debrief share, and the small pure helpers around them. No React in here, so the tests can drive it.

export const MAX_JD_CHARS = 5000

export interface JobSample {
  id: string
  title: string
  text: string
}

/** How a posting was read: by the 7b ("model") or by the deterministic keyword reader ("keywords", with the reason the model was not used). */
export interface JobExtraction {
  role: string
  role_family: 'backend' | 'frontend' | 'database' | 'fullstack' | 'devops' | 'other'
  seniority: 'intern' | 'junior' | 'mid' | 'senior' | 'lead'
  domain: string
  skills: string[]
  soft_skills: string[]
  app_idea: string
  source: 'model' | 'keywords'
  reason: string
}

/** One scenario scored against the posting: role 50 + skills 35 + domain 15, and the sentence that says how. */
export interface JobMatch {
  scenario: string
  title: string
  kind: string
  score: number
  parts: { role: number; skills: number; domain: number }
  shared_skills: string[]
  reason: string
  rank: number
}

export interface JobAnalysis {
  job: { source: 'paste' | 'sample'; sample_id: string; chars: number; clipped: boolean }
  extraction: JobExtraction
  ranking: JobMatch[]
  recommended: string | null
}

/** What is sent with a start request: the posting (a sample id or the text) and the reading the person was shown. */
export interface JobRequest {
  sample_id?: string
  text?: string
  extraction?: JobExtraction
}

/** The job of the running session (the `scenario_started` event's `job`, and the briefing the `job_briefing` event may reword). */
export interface SessionJob {
  source: 'paste' | 'sample'
  sampleId: string
  role: string
  seniority: string
  domain: string
  reader: 'model' | 'keywords'
  keySkills: string[]
  match: { score: number; rank: number; of: number; reason: string }
  weights: Record<string, number>
  briefing: { text: string; source: 'template' | 'model'; reason: string }
}

/** The "Role fit" block of a report (`report.job`): extra to the standard score. */
export interface ReportJob {
  source: 'paste' | 'sample'
  sample_id: string
  clipped: boolean
  extraction: JobExtraction
  match: JobMatch
  weights: Record<string, number>
  weight_reasons: Record<string, string[]>
  key_skills: string[]
  briefing: { text: string; source: 'template' | 'model'; reason: string }
  role_fit: number
  standard_total: number
  criteria: { id: string; name: string; score: number; max: number; weight: number }[]
}

export function clipJd(text: string): string {
  return text.length > MAX_JD_CHARS ? text.slice(0, MAX_JD_CHARS) : text
}

export function counter(text: string): string {
  return `${text.length.toLocaleString('en-US')} / ${MAX_JD_CHARS.toLocaleString('en-US')}`
}

export function readerLabel(e: Pick<JobExtraction, 'source' | 'reason'>): string {
  return e.source === 'model' ? 'AI reader (qwen2.5-coder:7b)' : 'Keyword reader'
}

/** Why the keyword reader was used, in a sentence for the person; empty for the model. */
export function readerNote(e: Pick<JobExtraction, 'source' | 'reason'>): string {
  if (e.source === 'model') return 'Read by the local model; every skill it named is in your text.'
  return e.reason ? `The model was not used: ${e.reason}.` : 'Read by the deterministic keyword reader.'
}

/** The body of a start request for the analysis the person is looking at. */
export function jobRequest(a: JobAnalysis, text: string): JobRequest {
  return a.job.source === 'sample' ? { sample_id: a.job.sample_id, extraction: a.extraction } : { text, extraction: a.extraction }
}

export function seniorityLabel(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : ''
}

/** The criteria the weights stress, heaviest first (a weight of 1.1 or more), for the one-line summary next to the role-fit score. */
export function stressed(weights: Record<string, number>, names: Record<string, string>): string[] {
  return Object.entries(weights)
    .filter(([id, w]) => w >= 1.1 && names[id])
    .sort((a, b) => b[1] - a[1])
    .map(([id]) => names[id])
}

export function weightText(w: number): string {
  return `×${w.toFixed(2)}`
}
