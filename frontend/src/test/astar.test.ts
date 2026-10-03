import { describe, expect, it } from 'vitest'
import { findPath } from '../office/astar'
import { COLS, ROWS, blockedFor, buildBlocked, visitSpots } from '../office/layout'

const SEATS = [{ x: 3, y: 2 }, { x: 6, y: 2 }, { x: 9, y: 2 }, { x: 12, y: 2 }, { x: 3, y: 6 }, { x: 6, y: 6 }, { x: 9, y: 6 }, { x: 12, y: 6 }]

describe('A* walking', () => {
  const base = buildBlocked(SEATS)

  it('finds a shortest 4-neighbour path around a wall', () => {
    const b = Array.from({ length: 5 }, () => Array.from({ length: 5 }, () => false))
    for (let y = 0; y < 4; y++) b[y][2] = true // wall with a gap at the bottom
    const p = findPath(b, { x: 0, y: 0 }, { x: 4, y: 0 })!
    expect(p[0]).toEqual({ x: 0, y: 0 })
    expect(p.at(-1)).toEqual({ x: 4, y: 0 })
    expect(p.length).toBe(13) // down 4, across 4, up 4, plus the start
    expect(p.every((t) => !b[t.y][t.x])).toBe(true)
  })

  it('returns null when the goal is blocked or unreachable', () => {
    const b = Array.from({ length: 3 }, () => Array.from({ length: 3 }, () => false))
    b[1][1] = true
    expect(findPath(b, { x: 0, y: 0 }, { x: 1, y: 1 })).toBeNull()
    for (let y = 0; y < 3; y++) b[y][1] = true
    expect(findPath(b, { x: 0, y: 0 }, { x: 2, y: 2 })).toBeNull()
  })

  it('allows the start tile to be blocked (a chair at a desk edge)', () => {
    const b = Array.from({ length: 3 }, () => Array.from({ length: 3 }, () => false))
    b[0][0] = true
    expect(findPath(b, { x: 0, y: 0 }, { x: 2, y: 0 })).not.toBeNull()
  })

  it('every desk reaches every visit spot of every other desk without walking through a seated colleague', () => {
    for (const from of SEATS) {
      const grid = blockedFor(base, SEATS, from)
      for (const to of SEATS) {
        if (to === from) continue
        const spot = visitSpots(to).find((t) => !grid[t.y][t.x])!
        const p = findPath(grid, from, spot)
        expect(p, `${from.x},${from.y} -> ${spot.x},${spot.y}`).not.toBeNull()
        const others = SEATS.filter((s) => s !== from)
        expect(p!.some((t) => others.some((s) => s.x === t.x && s.y === t.y))).toBe(false)
      }
    }
  })

  it('keeps the coffee area and the lounge reachable from every desk', () => {
    for (const s of SEATS) {
      const grid = blockedFor(base, SEATS, s)
      for (const goal of [{ x: 15, y: 9 }, { x: 17, y: 9 }, { x: 15, y: 7 }, { x: 4, y: 8 }]) {
        expect(findPath(grid, s, goal), `${s.x},${s.y} -> ${goal.x},${goal.y}`).not.toBeNull()
      }
    }
    expect(base.length).toBe(ROWS)
    expect(base[0].length).toBe(COLS)
  })
})
