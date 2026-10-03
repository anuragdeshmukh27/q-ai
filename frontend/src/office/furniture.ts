// Every piece of furniture, painted from code. Colours are tuned for a dark, projector-friendly office.
import type { Texture } from 'pixi.js'
import { COLS, TILE } from './layout'
import { COLORS } from './palette'
import { darken, dot, grid, hash, lighten, mix, rect, surface, toTexture, type Surface } from './pixel'

const T = TILE

// ---- floor -------------------------------------------------------------------------------------
export function floorTile(kind: 'carpet' | 'tile' | 'wood', tx: number, ty: number): Texture {
  const s = surface(T, T)
  const g = s.g
  const h = hash(`${kind}${tx}${ty}`)
  if (kind === 'carpet') {
    const base = (tx + ty) % 2 ? COLORS.floorA : COLORS.floorB
    rect(g, 0, 0, T, T, base)
    rect(g, 0, 0, T, 1, lighten(base, 0.05))
    rect(g, 0, 0, 1, T, lighten(base, 0.05))
    for (let i = 0; i < 4; i++) dot(g, (h >>> (i * 2)) % T, (h >>> (i * 3 + 1)) % T, darken(base, 0.06 + (i % 3) * 0.03))
  } else if (kind === 'tile') {
    const base = (tx + ty) % 2 ? '#aab4c6' : '#9aa6bb'
    rect(g, 0, 0, T, T, base)
    rect(g, 0, T - 1, T, 1, darken(base, 0.18))
    rect(g, T - 1, 0, 1, T, darken(base, 0.18))
    dot(g, 3, 3, lighten(base, 0.2))
  } else {
    const base = '#7a5236'
    rect(g, 0, 0, T, T, base)
    for (let i = 0; i < 4; i++) {
      const y = i * 4
      rect(g, 0, y, T, 1, darken(base, 0.28))
      const off = ((tx + ty + i) % 2) * 8
      rect(g, (off + 8) % T, y + 1, 1, 3, darken(base, 0.2))
      dot(g, (h >>> (i * 4)) % T, y + 2, lighten(base, 0.15))
    }
  }
  return toTexture(s)
}

export function rugTexture(wTiles: number, hTiles: number): Texture {
  const w = wTiles * T
  const h = hTiles * T
  const s = surface(w, h)
  const g = s.g
  rect(g, 1, 1, w - 2, h - 2, '#5a2f4a')
  rect(g, 3, 3, w - 6, h - 6, '#7a3d62')
  rect(g, 6, 6, w - 12, h - 12, '#5a2f4a')
  for (let x = 8; x < w - 8; x += 4) for (let y = 8; y < h - 8; y += 4) if (((x + y) / 4) % 2 === 0) rect(g, x, y, 2, 2, '#9a5a80')
  rect(g, 0, 2, 1, h - 4, '#e0b0c8')
  rect(g, w - 1, 2, 1, h - 4, '#e0b0c8')
  return toTexture(s)
}

// ---- back wall (all decoration painted in one 288 x 32 strip) ---------------------------------
export function wallStrip(): Texture {
  const W = COLS * T
  const s = surface(W, 32)
  const g = s.g
  // plaster with soft panel lines
  for (let y = 0; y < 32; y++) rect(g, 0, y, W, 1, mix('#222b44', '#18203a', y / 31))
  for (let x = 0; x < W; x += 24) rect(g, x, 0, 1, 26, 'rgba(255,255,255,0.04)')
  rect(g, 0, 0, W, 2, '#10162a')
  // baseboard + floor shadow
  rect(g, 0, 26, W, 5, '#10162a')
  rect(g, 0, 26, W, 1, '#3a4766')
  rect(g, 0, 31, W, 1, '#0a0e1c')

  const windowAt = (x: number, w: number) => {
    rect(g, x - 2, 3, w + 4, 22, '#0c1020')
    rect(g, x - 1, 4, w + 2, 20, '#4a5878')
    rect(g, x, 5, w, 18, '#0d1830')
    // night sky: gradient, stars, skyline with lit windows
    for (let y = 5; y < 23; y++) rect(g, x, y, w, 1, mix('#101c3c', '#27345e', (y - 5) / 18))
    for (let i = 0; i < 6; i++) dot(g, x + 1 + ((i * 7 + x) % (w - 2)), 6 + ((i * 3) % 6), '#cfe0ff')
    let bx = x
    let n = 0
    while (bx < x + w) {
      const bw = 3 + ((n * 5 + x) % 4)
      const bh = 4 + ((n * 7 + x) % 8)
      rect(g, bx, 23 - bh, Math.min(bw, x + w - bx), bh, '#0a1024')
      for (let wy = 23 - bh + 1; wy < 22; wy += 2) for (let wx = bx + 1; wx < Math.min(bx + bw, x + w) - 1; wx += 2) if ((wx * 3 + wy * 5 + n) % 3 === 0) dot(g, wx, wy, '#f6d77a')
      bx += bw + 1
      n++
    }
    rect(g, x + Math.floor(w / 2), 5, 1, 18, '#4a5878')
    rect(g, x, 13, w, 1, '#4a5878')
    rect(g, x - 2, 24, w + 4, 2, '#5a6888')
  }
  windowAt(14, 26)
  windowAt(172, 26)

  // whiteboard frame (the live board is a separate overlay)
  rect(g, 69, 3, 54, 24, '#0c1020')
  rect(g, 70, 4, 52, 22, '#c9d0de')
  rect(g, 71, 5, 50, 20, '#eef1f7')
  rect(g, 70, 25, 52, 2, '#7d8aa3')
  for (let i = 0; i < 4; i++) rect(g, 74 + i * 7, 7, 5, 1, '#b8c0d4')

  // clock
  rect(g, 138, 6, 11, 11, '#0c1020')
  rect(g, 139, 7, 9, 9, '#eef1f7')
  rect(g, 143, 8, 1, 4, '#1a1f33')
  rect(g, 143, 11, 3, 1, '#1a1f33')
  dot(g, 143, 11, '#e5584f')

  // Q poster
  rect(g, 150, 4, 18, 21, '#0c1020')
  rect(g, 151, 5, 16, 19, '#2a3358')
  grid(g, [
    '..pppppp..',
    '.pp....pp.',
    'pp......pp',
    'pp......pp',
    'pp......pp',
    'pp......pp',
    'pp..pp..pp',
    '.pp..pp.p.',
    '..pppppppp',
    '.......pp.',
  ], { p: '#8ab4ff' }, 154, 8)
  rect(g, 153, 20, 12, 1, '#5b6cf0')
  rect(g, 155, 22, 8, 1, '#3a4780')

  // shelf with books + plant
  rect(g, 205, 16, 36, 3, '#6a4229')
  rect(g, 205, 16, 36, 1, '#8a5a3a')
  const books = ['#e5584f', '#4fbf5f', '#5b6cf0', '#f09a3e', '#a86bea', '#22b8a8', '#ee6fa8']
  let bx = 207
  books.forEach((c, i) => {
    const bh = 7 + (i % 3) * 2
    rect(g, bx, 16 - bh, 3, bh, c)
    rect(g, bx, 16 - bh, 1, bh, darken(c, 0.25))
    bx += 4
  })
  rect(g, 235, 10, 5, 6, '#7a5230')
  rect(g, 234, 5, 7, 6, '#2f8f4e')
  rect(g, 236, 3, 3, 3, '#3fae60')

  // door frame at far right under the racks is hidden; add a vent
  rect(g, 252, 6, 18, 6, '#10162a')
  for (let i = 0; i < 4; i++) rect(g, 254, 7 + i, 14, 1, '#242c48')
  return toTexture(s)
}

// ---- desk, chair, monitor --------------------------------------------------------------------
export function deskTexture(seed: string, accent: string): Texture {
  const s = surface(32, 20)
  const g = s.g
  const top = '#9a6a45'
  rect(g, 0, 0, 32, 11, top)
  rect(g, 0, 0, 32, 1, lighten(top, 0.25))
  rect(g, 0, 0, 1, 11, lighten(top, 0.12))
  rect(g, 31, 0, 1, 11, darken(top, 0.15))
  rect(g, 0, 11, 32, 1, darken(top, 0.4))
  rect(g, 0, 12, 32, 8, '#6a4229')
  rect(g, 0, 12, 32, 1, '#7d5034')
  // drawers
  rect(g, 2, 14, 12, 5, '#593622')
  rect(g, 18, 14, 12, 5, '#593622')
  rect(g, 7, 16, 2, 1, '#c3c6d0')
  rect(g, 23, 16, 2, 1, '#c3c6d0')
  rect(g, 0, 19, 32, 1, '#2a1a10')
  // keyboard + mouse in front of the chair
  rect(g, 3, 4, 11, 4, '#1a1d29')
  rect(g, 4, 5, 9, 2, '#3a4056')
  for (let x = 4; x < 13; x += 2) dot(g, x, 5, '#6a7390')
  rect(g, 16, 5, 2, 3, '#1a1d29')
  // personal items from the id hash: sticky note, mug, pen cup
  const h = hash(seed)
  rect(g, 19, 2, 3, 3, accent)
  rect(g, 19, 2, 3, 1, lighten(accent, 0.3))
  if (h % 2) {
    rect(g, 25, 3, 3, 4, '#e8eaf2')
    rect(g, 25, 3, 3, 1, '#5a3a22')
    dot(g, 28, 4, '#c3c6d0')
  } else {
    rect(g, 25, 2, 3, 5, '#3a4056')
    dot(g, 25, 1, '#e5584f')
    dot(g, 27, 0, '#5b6cf0')
  }
  return toTexture(s)
}

export function chairTexture(accent: string): Texture {
  const s = surface(14, 16)
  const g = s.g
  rect(g, 1, 3, 12, 12, '#242a40')
  rect(g, 2, 2, 10, 1, '#242a40')
  rect(g, 3, 1, 8, 1, '#242a40')
  rect(g, 2, 3, 10, 1, lighten('#242a40', 0.18))
  rect(g, 3, 4, 8, 9, '#2d3452')
  rect(g, 3, 4, 8, 1, mix('#2d3452', accent, 0.5))
  rect(g, 1, 13, 12, 2, '#161a2c')
  return toTexture(s)
}

export function monitorFrame(): Texture {
  const s = surface(16, 14)
  const g = s.g
  rect(g, 0, 0, 16, 11, '#0f121c')
  rect(g, 0, 0, 16, 1, '#2a3048')
  rect(g, 6, 11, 4, 2, '#252a3e')
  rect(g, 3, 13, 10, 1, '#1b1f30')
  dot(g, 14, 10, '#4ade80')
  return toTexture(s)
}

export interface Screen {
  surface: Surface
  texture: Texture
}

export function makeScreen(): Screen {
  const s = surface(14, 9)
  return { surface: s, texture: toTexture(s) }
}

// ---- tall furniture -------------------------------------------------------------------------
export function rackFrame(): Texture {
  const s = surface(16, 32)
  const g = s.g
  rect(g, 0, 0, 16, 32, '#141828')
  rect(g, 0, 0, 16, 1, '#3a4262')
  rect(g, 0, 0, 1, 32, '#2a3250')
  rect(g, 15, 0, 1, 32, '#0b0e1a')
  for (let i = 0; i < 6; i++) {
    const y = 2 + i * 5
    rect(g, 2, y, 12, 4, '#1f253c')
    rect(g, 2, y, 12, 1, '#2d3552')
    for (let x = 3; x < 9; x += 2) rect(g, x, y + 2, 1, 1, '#0b0e1a')
  }
  rect(g, 0, 31, 16, 1, '#05070f')
  return toTexture(s)
}

export function rackLights(): Surface {
  return surface(16, 32)
}

export function paintRackLights(s: Surface, t: number, busy: number, seed: number) {
  s.g.clearRect(0, 0, 16, 32)
  for (let i = 0; i < 6; i++) {
    const y = 2 + i * 5
    const phase = Math.sin(t * (2 + busy * 9) + i * 1.7 + seed)
    const on = phase > -0.3
    dot(s.g, 11, y + 1, on ? '#4ade80' : '#1d5c3a')
    dot(s.g, 13, y + 1, phase * Math.sin(t * 3.1 + i) > 0.1 + (1 - busy) * 0.5 ? '#fbbf24' : '#5a4614')
    if (busy > 0.5 && (Math.floor(t * 12) + i) % 4 === 0) dot(s.g, 12, y + 2, '#60a5fa')
  }
}

export function coffeeMachine(): Texture {
  const s = surface(16, 32)
  const g = s.g
  rect(g, 1, 6, 14, 22, '#2a2f45')
  rect(g, 1, 6, 14, 1, '#454e70')
  rect(g, 1, 6, 1, 22, '#394160')
  rect(g, 2, 8, 12, 6, '#12151f')
  rect(g, 3, 9, 6, 4, '#0b0e1a')
  dot(g, 4, 10, '#4ade80')
  dot(g, 6, 10, '#4ade80')
  rect(g, 10, 9, 3, 4, '#e5584f')
  rect(g, 6, 15, 4, 3, '#0b0e1a')
  rect(g, 7, 18, 2, 2, '#5a3a22')
  rect(g, 4, 21, 8, 5, '#1a1d29')
  rect(g, 5, 22, 6, 3, '#f1f2f6')
  rect(g, 5, 22, 6, 1, '#5a3a22')
  rect(g, 11, 23, 1, 2, '#d7d9e2')
  rect(g, 0, 28, 16, 3, '#1b1f30')
  rect(g, 0, 28, 16, 1, '#454e70')
  return toTexture(s)
}

export function plant(variant: number): Texture {
  const s = surface(16, 24)
  const g = s.g
  rect(g, 4, 17, 8, 7, '#7a5230')
  rect(g, 4, 17, 8, 1, '#a8734c')
  rect(g, 5, 23, 6, 1, '#4a2f1e')
  const leaf = variant % 2 ? '#2f8f4e' : '#3fae60'
  const dark = darken(leaf, 0.3)
  rect(g, 7, 6, 2, 12, dark)
  rect(g, 3, 7, 4, 3, leaf)
  rect(g, 9, 5, 4, 3, leaf)
  rect(g, 2, 11, 5, 3, dark)
  rect(g, 9, 10, 5, 3, leaf)
  rect(g, 5, 2, 6, 4, leaf)
  rect(g, 6, 1, 4, 2, lighten(leaf, 0.2))
  rect(g, 4, 14, 4, 3, leaf)
  dot(g, 3, 8, lighten(leaf, 0.3))
  dot(g, 10, 6, lighten(leaf, 0.3))
  return toTexture(s)
}

export function meetingTable(): Texture {
  const s = surface(64, 32)
  const g = s.g
  rect(g, 1, 2, 62, 22, '#8a5a3a')
  rect(g, 1, 2, 62, 1, '#b07a52')
  rect(g, 0, 3, 1, 20, '#6a4229')
  rect(g, 63, 3, 1, 20, '#6a4229')
  rect(g, 2, 21, 60, 3, '#6a4229')
  rect(g, 2, 24, 60, 2, '#2a1a10')
  rect(g, 4, 26, 4, 5, '#4a2f1e')
  rect(g, 56, 26, 4, 5, '#4a2f1e')
  // laptop
  rect(g, 10, 7, 12, 8, '#1a1d29')
  rect(g, 11, 8, 10, 6, '#3a6fd8')
  for (let i = 0; i < 3; i++) rect(g, 12, 9 + i * 2, 4 + (i % 2) * 3, 1, '#cfe0ff')
  rect(g, 9, 15, 14, 2, '#c3c6d0')
  // papers + mug + pen
  rect(g, 30, 8, 9, 7, '#f1f2f6')
  rect(g, 32, 10, 5, 1, '#9aa0b2')
  rect(g, 32, 12, 4, 1, '#9aa0b2')
  rect(g, 42, 9, 4, 4, '#e8eaf2')
  rect(g, 42, 9, 4, 1, '#5a3a22')
  rect(g, 50, 8, 8, 6, '#e8d9a0')
  rect(g, 51, 9, 6, 1, '#b8a460')
  return toTexture(s)
}

export function meetingChair(flip: boolean): Texture {
  const s = surface(12, 14)
  const g = s.g
  rect(g, 1, 2, 10, 9, '#3a4056')
  rect(g, 1, 2, 10, 1, '#5a6288')
  rect(g, 2, 11, 8, 2, '#1b1f30')
  if (flip) rect(g, 1, 0, 10, 2, '#3a4056')
  return toTexture(s)
}

export function receptionDesk(): Texture {
  const s = surface(32, 20)
  const g = s.g
  rect(g, 0, 0, 32, 11, '#c7a27a')
  rect(g, 0, 0, 32, 1, '#e6c9a4')
  rect(g, 0, 11, 32, 9, '#8a6a4a')
  rect(g, 0, 11, 32, 1, '#6a4f36')
  rect(g, 3, 14, 26, 4, '#6a4f36')
  grid(g, [
    '.ppppp.',
    'pwwwwwp',
    'pwQwQwp',
    'pwwwwwp',
    '.ppppp.',
  ], { p: '#3a4780', w: '#eef1f7', Q: '#5b6cf0' }, 12, 14)
  // bell
  rect(g, 4, 5, 5, 3, '#e8c34a')
  rect(g, 6, 4, 1, 1, '#e8c34a')
  rect(g, 22, 3, 6, 5, '#f1f2f6')
  rect(g, 23, 4, 4, 1, '#9aa0b2')
  return toTexture(s)
}

export function shadow(w: number, h: number): Texture {
  const s = surface(w, h)
  const g = s.g
  g.fillStyle = 'rgba(0,0,0,0.28)'
  g.fillRect(1, 0, w - 2, h)
  g.fillRect(0, 1, w, h - 2)
  return toTexture(s)
}

/** Soft radial light used additively under monitors. Generated, not drawn pixel by pixel on purpose: it is light, not a sprite. */
export function glow(radius: number): Texture {
  const size = radius * 2
  const s = surface(size, size)
  const g = s.g
  const grad = g.createRadialGradient(radius, radius, 0, radius, radius, radius)
  grad.addColorStop(0, 'rgba(255,255,255,0.9)')
  grad.addColorStop(0.4, 'rgba(255,255,255,0.25)')
  grad.addColorStop(1, 'rgba(255,255,255,0)')
  g.fillStyle = grad
  g.fillRect(0, 0, size, size)
  return toTexture(s)
}

export function whiteboardCanvas(): Surface {
  return surface(50, 20)
}

export function paintWhiteboard(s: Surface, tasks: { status: string }[]) {
  const g = s.g
  g.clearRect(0, 0, 50, 20)
  const cols: Record<string, string> = { done: '#34c759', running: '#3b82f6', in_progress: '#3b82f6', failed: '#ef4444', pending: '#b8c0d4' }
  const n = Math.min(tasks.length, 18)
  for (let i = 0; i < n; i++) {
    const x = 2 + (i % 6) * 8
    const y = 3 + Math.floor(i / 6) * 6
    const c = cols[tasks[i].status] ?? cols.pending
    rect(g, x, y, 6, 4, c)
    rect(g, x, y, 6, 1, lighten(c, 0.3))
  }
  if (!n) for (let i = 0; i < 3; i++) rect(g, 3, 4 + i * 5, 24 - i * 5, 1, '#b8c0d4')
  const done = tasks.filter((t) => t.status === 'done').length
  rect(g, 2, 17, 46, 2, '#c9d0de')
  if (n) rect(g, 2, 17, Math.round((46 * done) / tasks.length), 2, '#34c759')
}

export function sofa(): Texture {
  const s = surface(32, 20)
  const g = s.g
  rect(g, 1, 0, 30, 10, '#3b4a8a')
  rect(g, 1, 0, 30, 1, '#5565a8')
  rect(g, 3, 3, 12, 7, '#4a5cad')
  rect(g, 17, 3, 12, 7, '#4a5cad')
  rect(g, 3, 3, 12, 1, '#6577c4')
  rect(g, 17, 3, 12, 1, '#6577c4')
  rect(g, 1, 10, 30, 7, '#34427a')
  rect(g, 1, 10, 30, 1, '#4a5cad')
  rect(g, 0, 3, 3, 14, '#2d3a6e')
  rect(g, 29, 3, 3, 14, '#2d3a6e')
  rect(g, 0, 3, 3, 1, '#4a5cad')
  rect(g, 29, 3, 3, 1, '#4a5cad')
  rect(g, 2, 17, 3, 2, '#14182c')
  rect(g, 27, 17, 3, 2, '#14182c')
  rect(g, 9, 5, 5, 4, '#f0a24a') // cushion
  rect(g, 9, 5, 5, 1, '#f6bf7a')
  return toTexture(s)
}
