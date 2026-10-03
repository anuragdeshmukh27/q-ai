// Small pixel icons (status marks, glyphs) painted from grids. All original.
import type { Texture } from 'pixi.js'
import { dot, grid, surface, toTexture } from './pixel'

const OUT = '#0b0d12'

function icon(rows: string[], pal: Record<string, string>): Texture {
  const w = rows[0].length
  const h = rows.length
  const s = surface(w + 2, h + 2)
  // 1 px dark outline around every opaque pixel, so marks read on any floor colour
  const mask = surface(w, h)
  grid(mask.g, rows, pal)
  const data = mask.g.getImageData(0, 0, w, h).data
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++)
      if (data[(y * w + x) * 4 + 3] > 0) for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [0, 1], [-1, -1], [1, 1], [-1, 1], [1, -1]]) dot(s.g, x + 1 + dx, y + 1 + dy, OUT)
  grid(s.g, rows, pal, 1, 1)
  return toTexture(s)
}

export interface Icons {
  bang: Texture
  question: Texture
  check: Texture
  cross: Texture
  mail: Texture
  zA: Texture
  zB: Texture
  dots: Texture[]
  book: Texture
  heart: Texture
}

let cached: Icons | null = null

export function icons(): Icons {
  if (cached) return cached
  cached = {
    bang: icon(['rr', 'rr', 'rr', 'rr', '..', 'rr'], { r: '#ff4d4d' }),
    question: icon(['.aaa.', 'a...a', '....a', '..aa.', '..a..', '.....', '..a..'], { a: '#ffc233' }),
    check: icon(['......g', '.....gg', 'g...gg.', 'gg.gg..', '.ggg...', '..g....'], { g: '#3ddc6c' }),
    cross: icon(['r...r', '.r.r.', '..r..', '.r.r.', 'r...r'], { r: '#ff5a5a' }),
    mail: icon(['wwwwwww', 'wb...bw', 'w.b.b.w', 'w..b..w', 'wwwwwww'], { w: '#f3f5fb', b: '#6c7ae0' }),
    zA: icon(['zzzz', '..z.', '.z..', 'zzzz'], { z: '#bcd0ff' }),
    zB: icon(['zzzzz', '...z.', '..z..', '.z...', 'zzzzz'], { z: '#e2ebff' }),
    dots: [
      icon(['...........', '.ww........', '.ww........'], { w: '#e6e8ff' }),
      icon(['...........', '.ww..ww....', '.ww..ww....'], { w: '#e6e8ff' }),
      icon(['...........', '.ww..ww..ww', '.ww..ww..ww'], { w: '#e6e8ff' }),
    ],
    book: icon(['bbbbb', 'bwbwb', 'bwbwb', 'bbbbb'], { b: '#5aa7ff', w: '#e8f1ff' }),
    heart: icon(['.r.r.', 'rrrrr', 'rrrrr', '.rrr.', '..r..'], { r: '#ff6fa8' }),
  }
  return cached
}
