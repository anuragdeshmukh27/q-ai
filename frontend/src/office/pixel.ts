// Procedural pixel-art helpers. Every sprite in the office is painted from code (rects and palette grids); no image files.
import { CanvasSource, Texture } from 'pixi.js'

export interface Surface {
  c: HTMLCanvasElement
  g: CanvasRenderingContext2D
}

export function surface(w: number, h: number): Surface {
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  const g = c.getContext('2d')!
  g.imageSmoothingEnabled = false
  return { c, g }
}

export function rect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, color: string) {
  g.fillStyle = color
  g.fillRect(x, y, w, h)
}

export function dot(g: CanvasRenderingContext2D, x: number, y: number, color: string) {
  g.fillStyle = color
  g.fillRect(x, y, 1, 1)
}

/** Paint a palette-char grid ('.' and ' ' are transparent). */
export function grid(g: CanvasRenderingContext2D, rows: string[], pal: Record<string, string>, ox = 0, oy = 0) {
  rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      const color = pal[row[x]]
      if (color) dot(g, ox + x, oy + y, color)
    }
  })
}

export function gridSurface(rows: string[], pal: Record<string, string>): Surface {
  const s = surface(Math.max(...rows.map((r) => r.length)), rows.length)
  grid(s.g, rows, pal)
  return s
}

export function toTexture(s: Surface | HTMLCanvasElement): Texture {
  const c = 'c' in s ? s.c : s
  return new Texture({ source: new CanvasSource({ resource: c, scaleMode: 'nearest', resolution: 1 }) })
}

/** Re-upload a canvas that was painted again (animated monitor screens). */
export function refresh(t: Texture) {
  t.source.update()
}

// -- colour maths ---------------------------------------------------------------------------------
export function rgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export function toHex(r: number, g: number, b: number): string {
  const c = (v: number) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')
  return `#${c(r)}${c(g)}${c(b)}`
}

export function mix(a: string, b: string, t: number): string {
  const [ar, ag, ab] = rgb(a)
  const [br, bg, bb] = rgb(b)
  return toHex(ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t)
}

export const darken = (c: string, t: number) => mix(c, '#000000', t)
export const lighten = (c: string, t: number) => mix(c, '#ffffff', t)
export const hexNum = (c: string) => parseInt(c.slice(1), 16)

/** Small deterministic hash for per-agent variation. */
export function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619)
  return h >>> 0
}
