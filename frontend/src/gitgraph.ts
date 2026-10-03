// Lane layout for the branch graph. Input is `Repo.graph()` (newest first, topological); output is where to draw each dot and line.
import type { Commit } from './api'

export interface GraphEdge {
  to: number // row of the parent commit
  via: number // lane the line runs in between the two dots
}

export interface GraphRow {
  commit: Commit
  lane: number
  edges: GraphEdge[]
}

export function layoutGraph(commits: Commit[]): { rows: GraphRow[]; lanes: number } {
  const row = new Map(commits.map((c, i) => [c.hash, i]))
  const lanes: (string | null)[] = [] // lane -> hash of the commit that lane is waiting for
  const rows: GraphRow[] = []
  let width = 1

  const free = () => {
    const i = lanes.indexOf(null)
    return i === -1 ? lanes.push(null) - 1 : i
  }

  for (const c of commits) {
    let lane = lanes.indexOf(c.hash)
    if (lane === -1) lane = free()
    for (let i = 0; i < lanes.length; i++) if (lanes[i] === c.hash) lanes[i] = null // lines that converge on this commit end here
    const edges: GraphEdge[] = []
    c.parents.forEach((p, k) => {
      if (!row.has(p)) return
      let via = k === 0 ? lane : lanes.indexOf(p) // the first parent continues in this lane (even if another lane already waits for it: they converge there)
      if (via === -1) via = free()
      lanes[via] = p
      edges.push({ to: row.get(p)!, via })
    })
    rows.push({ commit: c, lane, edges })
    width = Math.max(width, lanes.length, lane + 1)
  }
  return { rows, lanes: width }
}
