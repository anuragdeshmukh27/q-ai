// The office floor plan (tile coordinates). 18 x 12 tiles of 16 px. Rows 0-1 are the back wall.
import type { Blocked, Tile } from './astar'

export const TILE = 16
export const COLS = 18
export const ROWS = 12
export const WORLD_W = COLS * TILE
export const WORLD_H = ROWS * TILE

export interface Box {
  x: number
  y: number
  w: number
  h: number
}

// Solid furniture (tiles). Desks are added from the roster: every desk is 2 tiles wide, one row below its chair.
export const RACKS: Box[] = [{ x: 16, y: 2, w: 1, h: 2 }, { x: 17, y: 2, w: 1, h: 2 }]
export const COFFEE: Box = { x: 16, y: 8, w: 1, h: 2 }
export const TABLE: Box = { x: 6, y: 9, w: 4, h: 2 }
export const RECEPTION: Box = { x: 1, y: 10, w: 2, h: 1 }
export const RECEPTION_SEAT: Tile = { x: 1, y: 9 }
export const PLANTS: Tile[] = [{ x: 0, y: 2 }, { x: 0, y: 6 }, { x: 17, y: 5 }, { x: 14, y: 10 }]
export const SOFA: Box = { x: 14, y: 5, w: 2, h: 1 }
export const RUG: Box = { x: 5, y: 8, w: 6, h: 4 }
export const CHAIRS: Tile[] = [{ x: 5, y: 9 }, { x: 5, y: 10 }, { x: 10, y: 9 }, { x: 10, y: 10 }, { x: 7, y: 11 }, { x: 8, y: 11 }]

// Where employees stand for a coffee break (spaced so name tags do not overlap).
export const COFFEE_SPOTS: Tile[] = [{ x: 15, y: 9 }, { x: 17, y: 9 }, { x: 15, y: 7 }, { x: 17, y: 7 }, { x: 15, y: 11 }, { x: 17, y: 11 }, { x: 14, y: 8 }, { x: 14, y: 11 }]

export interface Desk {
  id: string
  seat: Tile // the chair tile (where the employee sits)
}

export function deskTiles(seat: Tile): Box {
  return { x: seat.x, y: seat.y + 1, w: 2, h: 1 }
}

/** Places a visitor can stand to talk to the person seated at `seat`, best first: the aisle tiles beside the chair and the desk. */
export function visitSpots(seat: Tile): Tile[] {
  return [
    { x: seat.x - 1, y: seat.y },
    { x: seat.x + 2, y: seat.y },
    { x: seat.x - 1, y: seat.y + 1 },
    { x: seat.x + 2, y: seat.y + 1 },
  ]
}

/** The grid with every chair other than `own` blocked, so nobody walks through a seated colleague. */
export function blockedFor(base: Blocked, seats: Tile[], own: Tile): Blocked {
  const b = base.map((row) => row.slice())
  for (const s of seats) if (s.x !== own.x || s.y !== own.y) b[s.y][s.x] = true
  return b
}

export function buildBlocked(seats: Tile[]): Blocked {
  const b: Blocked = Array.from({ length: ROWS }, (_, y) => Array.from({ length: COLS }, () => y < 2))
  const block = (r: Box) => {
    for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) if (b[y]?.[x] !== undefined) b[y][x] = true
  }
  RACKS.forEach(block)
  block(COFFEE)
  block(TABLE)
  block(RECEPTION)
  block(SOFA)
  PLANTS.forEach((p) => block({ ...p, w: 1, h: 1 }))
  seats.forEach((s) => block(deskTiles(s)))
  return b
}
