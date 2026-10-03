// A* over the office tile grid (4-neighbour). Used for every walk between desks.
export interface Tile {
  x: number
  y: number
}

export type Blocked = boolean[][] // blocked[y][x]

export function inside(b: Blocked, x: number, y: number): boolean {
  return y >= 0 && y < b.length && x >= 0 && x < b[0].length
}

/** Shortest path from `from` to `to`, both included, or null. The start tile may be blocked (a chair under a desk edge). */
export function findPath(b: Blocked, from: Tile, to: Tile): Tile[] | null {
  if (!inside(b, to.x, to.y) || !inside(b, from.x, from.y)) return null
  if (b[to.y][to.x]) return null
  const key = (x: number, y: number) => y * b[0].length + x
  const g = new Map<number, number>([[key(from.x, from.y), 0]])
  const came = new Map<number, number>()
  const open: { x: number; y: number; f: number }[] = [{ ...from, f: 0 }]
  const h = (x: number, y: number) => Math.abs(x - to.x) + Math.abs(y - to.y)
  const closed = new Set<number>()
  while (open.length) {
    let best = 0
    for (let i = 1; i < open.length; i++) if (open[i].f < open[best].f) best = i
    const cur = open.splice(best, 1)[0]
    const ck = key(cur.x, cur.y)
    if (closed.has(ck)) continue
    closed.add(ck)
    if (cur.x === to.x && cur.y === to.y) {
      const path: Tile[] = [{ x: cur.x, y: cur.y }]
      let k = ck
      while (came.has(k)) {
        k = came.get(k)!
        path.push({ x: k % b[0].length, y: Math.floor(k / b[0].length) })
      }
      return path.reverse()
    }
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const nx = cur.x + dx
      const ny = cur.y + dy
      if (!inside(b, nx, ny) || b[ny][nx]) continue
      const nk = key(nx, ny)
      const ng = (g.get(ck) ?? 0) + 1
      if (ng < (g.get(nk) ?? Infinity)) {
        g.set(nk, ng)
        came.set(nk, ck)
        open.push({ x: nx, y: ny, f: ng + h(nx, ny) })
      }
    }
  }
  return null
}
