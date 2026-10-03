// What each employee's 14 x 9 monitor shows for every state. Painted per frame from the state and the clock.
import { dot, hash, rect } from './pixel'

const TOKENS = ['#7aa2f7', '#9ece6a', '#e0af68', '#bb9af7', '#c0caf5', '#f7768e', '#7dcfff']

function codeLine(g: CanvasRenderingContext2D, y: number, n: number, seed: number, dim = 1) {
  const h = hash(`${seed}:${n}`)
  const indent = (h % 3) * 2
  let x = 1 + indent
  let k = h >>> 3
  while (x < 13) {
    const len = 1 + (k % 4)
    const c = TOKENS[k % TOKENS.length]
    g.globalAlpha = dim
    rect(g, x, y, Math.min(len, 13 - x), 1, c)
    g.globalAlpha = 1
    x += len + 1
    k = (k >>> 2) + n + 3
    if ((k & 7) === 0) break
  }
}

export function paintScreen(g: CanvasRenderingContext2D, state: string, t: number, seed: number) {
  const W = 14
  const H = 9
  g.clearRect(0, 0, W, H)
  switch (state) {
    case 'typing': {
      rect(g, 0, 0, W, H, '#10162a')
      const top = Math.floor(t * 4)
      for (let i = 0; i < 4; i++) codeLine(g, 1 + i * 2, top + i, seed, 0.95)
      if (Math.floor(t * 3) % 2 === 0) rect(g, 1 + ((top * 3) % 9), 7, 2, 1, '#e6e8ff')
      if (Math.random() < 0.18) {
        g.globalAlpha = 0.12
        rect(g, 0, 0, W, H, '#ffffff')
        g.globalAlpha = 1
      }
      break
    }
    case 'reading': {
      rect(g, 0, 0, W, H, '#142034')
      const off = Math.floor(t * 5) % 2
      for (let i = 0; i < 5; i++) {
        const y = 1 + i * 2 - off
        if (y < 0 || y > 8) continue
        const w = 5 + ((hash(`${seed}${Math.floor(t * 2.5) + i}`) >>> 2) % 7)
        rect(g, 1, y, Math.min(w, 12), 1, i % 2 ? '#6e86ad' : '#9db4d8')
      }
      rect(g, 12, 0, 2, H, 'rgba(255,255,255,0.08)')
      rect(g, 13, 1 + (Math.floor(t * 3) % 6), 1, 2, '#9db4d8')
      break
    }
    case 'executing': {
      rect(g, 0, 0, W, H, '#04100a')
      const top = Math.floor(t * 5)
      for (let i = 0; i < 4; i++) {
        const n = top + i
        const h = hash(`${seed}x${n}`)
        dot(g, 1, 1 + i * 2, '#2ea043')
        rect(g, 3, 1 + i * 2, 2 + (h % 8), 1, h % 5 === 0 ? '#e3b341' : '#56d364')
      }
      if (Math.floor(t * 2.5) % 2 === 0) rect(g, 1, 8, 2, 1, '#56d364')
      g.globalAlpha = 0.07 + 0.05 * Math.sin(t * 9)
      rect(g, 0, 0, W, H, '#56d364')
      g.globalAlpha = 1
      break
    }
    case 'testing': {
      rect(g, 0, 0, W, H, '#161a2c')
      const n = Math.floor(t * 1.8) % 6
      for (let i = 0; i < 4; i++) {
        const y = 1 + i * 2
        if (i < n) {
          dot(g, 1, y, '#34c759')
          rect(g, 3, y, 4 + ((i * 3) % 6), 1, '#56d364')
        } else if (i === n) {
          rect(g, 3, y, 2 + (Math.floor(t * 6) % 6), 1, '#fbbf24')
        }
      }
      rect(g, 1, 8, 12, 1, '#2a3048')
      rect(g, 1, 8, Math.min(12, Math.round((12 * (t * 1.8 - Math.floor(t * 1.8 / 6) * 6)) / 6)), 1, '#fbbf24')
      break
    }
    case 'thinking': {
      rect(g, 0, 0, W, H, '#1a1430')
      for (let i = 0; i < 3; i++) {
        const h = Math.round(Math.sin(t * 5 - i * 0.9) * 1.5)
        rect(g, 4 + i * 3, 4 + h, 2, 2, '#c4b5fd')
      }
      break
    }
    case 'sleeping':
      rect(g, 0, 0, W, H, '#05060b')
      break
    case 'loading_model': {
      rect(g, 0, 0, W, H, '#0b1830')
      rect(g, 2, 5, 10, 2, '#1e3358')
      rect(g, 2, 5, 1 + Math.floor((t * 4) % 10), 2, '#fb923c')
      dot(g, 3 + (Math.floor(t * 8) % 8), 2, '#93c5fd')
      break
    }
    case 'error': {
      const flash = Math.floor(t * 4) % 2 === 0
      rect(g, 0, 0, W, H, flash ? '#8a1c1c' : '#c22d2d')
      rect(g, 6, 1, 2, 5, '#ffffff')
      rect(g, 6, 7, 2, 1, '#ffffff')
      break
    }
    case 'waiting_human': {
      rect(g, 0, 0, W, H, Math.floor(t * 2) % 2 ? '#8a6410' : '#a97a14')
      rect(g, 5, 1, 4, 1, '#fff')
      rect(g, 8, 2, 1, 2, '#fff')
      rect(g, 6, 4, 2, 1, '#fff')
      rect(g, 6, 6, 2, 1, '#fff')
      break
    }
    case 'celebrating': {
      for (let y = 0; y < H; y++) {
        const hue = (t * 160 + y * 36) % 360
        g.fillStyle = `hsl(${hue} 80% 55%)`
        g.fillRect(0, y, W, 1)
      }
      break
    }
    default: {
      // idle / walking: a quiet screensaver with a drifting block
      rect(g, 0, 0, W, H, '#0d1424')
      rect(g, 1, 1, 6, 1, '#1d2740')
      rect(g, 1, 3, 4, 1, '#1d2740')
      const x = 1 + Math.floor(Math.abs(((t * 2 + seed) % 20) - 10) * 1.1)
      rect(g, Math.min(x, 11), 6, 2, 2, '#34476e')
    }
  }
}

/** Colour of the light a monitor throws, by state. */
export const GLOW: Record<string, [string, number]> = {
  typing: ['#5b8cff', 0.38],
  reading: ['#5ab4ff', 0.3],
  executing: ['#3ddc6c', 0.45],
  testing: ['#ffc233', 0.38],
  thinking: ['#9b8cff', 0.3],
  loading_model: ['#fb923c', 0.35],
  error: ['#ff4d4d', 0.5],
  waiting_human: ['#ffc233', 0.45],
  celebrating: ['#ff7ad9', 0.45],
  idle: ['#3a5080', 0.14],
  walking: ['#3a5080', 0.14],
  sleeping: ['#000000', 0],
}
