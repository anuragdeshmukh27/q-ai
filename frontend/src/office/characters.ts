// Procedural 16x16 employees. Painted from rectangles per pose, so every state has its own frame set.
import type { Texture } from 'pixi.js'
import { dot, rect, surface, toTexture } from './pixel'
import type { Look } from './palette'

export type Dir = 'down' | 'up' | 'side'
export type Arm = 'down' | 'desk' | 'type_a' | 'type_b' | 'chin' | 'cheer_a' | 'cheer_b' | 'wave_a' | 'wave_b' | 'mug' | 'clip' | 'clip_ok'

export interface Pose {
  dir: Dir
  sit?: boolean
  leg?: number // walk phase 0..3
  arms?: [Arm, Arm] // [left, right] as seen on screen
  eyes?: 'open' | 'blink' | 'sleep' | 'left' | 'right' | 'wide'
  mouth?: 'none' | 'smile' | 'o' | 'frown'
  head?: number // extra downward head offset (asleep)
  bob?: number
  flush?: boolean // red cheeks
}

const EYE = '#16161e'
const MOUTH = '#a8514a'
const FRAME = '#2c3a6b'
const LENS = '#9fc4ff'

type RectFn = (x: number, y: number, w: number, h: number, c: string) => void
type DotFn = (x: number, y: number, c: string) => void

export function drawCharacter(g: CanvasRenderingContext2D, look: Look, pose: Pose) {
  const oy = pose.bob ?? 0
  const hy = pose.head ?? 0
  const R: RectFn = (x, y, w, h, c) => rect(g, x, y + oy, w, h, c)
  const D: DotFn = (x, y, c) => dot(g, x, y + oy, c)
  const H: RectFn = (x, y, w, h, c) => rect(g, x, y + oy + hy, w, h, c)
  const HD: DotFn = (x, y, c) => dot(g, x, y + oy + hy, c)
  const arms = pose.arms ?? ['down', 'down']
  const side = pose.dir === 'side'
  const back = pose.dir === 'up'

  // ---- legs (never when seated) ----
  if (!pose.sit) {
    const p = pose.leg ?? 0
    if (side) {
      const f = [0, 2, 0, -2][p]
      R(7 - f, 12, 2, 3, look.pantsDark) // back leg
      R(7 - f, 15, 3, 1, look.shoe)
      R(7 + f, 12, 2, 3, look.pants) // front leg
      R(7 + f, 15, 3, 1, look.shoe)
    } else {
      const lift = [0, 1, 0, 2][p] // 1 = left leg raised, 2 = right
      R(6, 12, 2, lift === 1 ? 2 : 3, look.pants)
      R(8, 12, 2, lift === 2 ? 2 : 3, look.pants)
      R(7, 12, 1, 3, look.pantsDark)
      R(5, lift === 1 ? 14 : 15, 3, 1, look.shoe)
      R(8, lift === 2 ? 14 : 15, 3, 1, look.shoe)
    }
  }

  // ---- torso ----
  const th = pose.sit ? 7 : 5
  if (side) {
    R(6, 7, 4, th, look.shirt)
    R(6, 7, 1, th, look.shirtDark)
    R(6, 7 + th - 1, 4, 1, look.shirtDark)
  } else {
    R(5, 7, 6, th, look.shirt)
    R(5, 7, 1, th, look.shirtDark)
    R(5, 7 + th - 1, 6, 1, look.shirtDark)
    if (!back) {
      D(7, 7, look.skin)
      D(8, 7, look.skin)
      if (look.accessory === 'tie') {
        D(7, 7, look.accent)
        D(8, 7, look.accent)
        R(7, 8, 2, 3, look.accent)
        D(8, 10, look.shirtDark)
      }
    }
  }

  // ---- arms ----
  const arm = (kind: Arm, left: boolean) => {
    const x0 = left ? 4 : 11
    const hx = left ? 5 : 9 // hand x when in front of the body
    switch (kind) {
      case 'down':
        R(x0, 8, 1, 2, look.shirt)
        D(x0, 10, look.skin)
        break
      case 'desk':
        R(x0, 8, 1, 4, look.shirt)
        R(hx, 12, 2, 1, look.skin)
        break
      case 'type_a':
        R(x0, 8, 1, 4, look.shirt)
        R(hx, left ? 12 : 11, 2, 1, look.skin)
        break
      case 'type_b':
        R(x0, 8, 1, 4, look.shirt)
        R(hx, left ? 11 : 12, 2, 1, look.skin)
        break
      case 'chin':
        R(x0, 7, 1, 3, look.shirt)
        R(left ? 4 : 10, 6, 2, 1, look.skin)
        break
      case 'cheer_a':
        R(x0, 4, 1, 4, look.shirt)
        R(x0, 2, 1, 2, look.skin)
        break
      case 'cheer_b': {
        const x = x0 + (left ? -1 : 1)
        R(x, 3, 1, 4, look.shirt)
        R(x, 1, 1, 2, look.skin)
        break
      }
      case 'wave_a':
        R(x0, 5, 1, 5, look.shirt)
        R(x0, 3, 1, 2, look.skin)
        break
      case 'wave_b':
        R(x0 + 1, 5, 1, 5, look.shirt)
        R(x0 + 1, 3, 1, 2, look.skin)
        break
      case 'mug':
        R(x0, 8, 1, 2, look.shirt)
        D(x0, 10, look.skin)
        R(x0 + 1, 9, 3, 3, '#f1f2f6')
        R(x0 + 1, 9, 3, 1, '#5a3a22')
        D(x0 + 4, 10, '#d7d9e2')
        break
      case 'clip':
      case 'clip_ok':
        R(x0, 8, 1, 2, look.shirt)
        D(x0, 10, look.skin)
        R(0, 8, 4, 6, '#7a5230')
        R(1, 9, 2, 4, '#f4f4ef')
        R(1, 8, 2, 1, '#c3c6d0')
        if (kind === 'clip_ok') {
          D(1, 11, '#34c759')
          D(2, 12, '#34c759')
        } else {
          D(1, 10, '#9aa0b2')
          D(2, 11, '#9aa0b2')
        }
        break
    }
  }
  if (side) {
    const swing = pose.leg === undefined ? 0 : [0, 1, 0, -1][pose.leg]
    R(7 + swing, 8, 2, 3, look.shirtLight)
    D(8 + swing, 11, look.skin)
  } else {
    arm(arms[0], true)
    arm(arms[1], false)
    if (!pose.sit && look.accessory === 'clipboard' && arms[0] === 'down') {
      R(0, 8, 4, 6, '#7a5230')
      R(1, 9, 2, 4, '#f4f4ef')
      R(1, 8, 2, 1, '#c3c6d0')
      D(1, 11, '#9aa0b2')
    }
  }

  // ---- head ----
  if (side) {
    H(7, 3, 4, 4, look.skin)
    HD(11, 5, look.skin) // nose
    HD(7, 4, look.skinShade) // ear
    HD(10, 4, EYE)
    if (look.accessory === 'glasses') {
      HD(8, 4, FRAME)
      HD(9, 4, FRAME)
      HD(11, 4, FRAME)
    }
    hairSide(H, HD, look)
  } else if (back) {
    H(5, 3, 6, 4, look.hair)
    HD(7, 6, look.skin)
    HD(8, 6, look.skin)
    hairFront(H, HD, look, true)
  } else {
    H(5, 3, 6, 4, look.skin)
    hairFront(H, HD, look, false)
    const e = pose.eyes ?? 'open'
    const ex = e === 'left' ? [5, 8] : e === 'right' ? [7, 10] : [6, 9]
    if (e === 'blink') {
      HD(6, 4, look.skinShade)
      HD(9, 4, look.skinShade)
    } else if (e === 'sleep') {
      HD(6, 5, EYE)
      HD(9, 5, EYE)
    } else {
      HD(ex[0], 4, EYE)
      HD(ex[1], 4, EYE)
      if (e === 'wide') {
        HD(ex[0], 5, EYE)
        HD(ex[1], 5, EYE)
      }
    }
    if (look.accessory === 'glasses') {
      for (const x of [5, 7, 8, 10]) HD(x, 4, FRAME)
      for (const x of [6, 9]) if (e !== 'wide') HD(x, 5, LENS)
    }
    const m = pose.mouth ?? 'none'
    if (m === 'smile') {
      HD(7, 6, MOUTH)
      HD(8, 6, MOUTH)
    } else if (m === 'o') {
      H(7, 6, 2, 1, '#5a2a2a')
    } else if (m === 'frown') {
      HD(7, 6, MOUTH)
      HD(8, 6, MOUTH)
    }
    if (pose.flush) {
      HD(5, 5, '#e66a5a')
      HD(10, 5, '#e66a5a')
    }
  }
}

function hairFront(H: RectFn, HD: DotFn, look: Look, back: boolean) {
  const { hair, hairLight } = look
  switch (look.hairStyle) {
    case 'short':
      H(5, 1, 6, 2, hair)
      HD(5, 3, hair)
      HD(10, 3, hair)
      HD(7, 1, hairLight)
      break
    case 'cropped':
      H(5, 2, 6, 1, hair)
      H(6, 1, 4, 1, hair)
      HD(7, 1, hairLight)
      break
    case 'long':
      H(5, 1, 6, 2, hair)
      H(4, 2, 1, 6, hair)
      H(11, 2, 1, 6, hair)
      HD(5, 3, hair)
      HD(10, 3, hair)
      HD(7, 1, hairLight)
      if (back) H(5, 6, 6, 3, hair)
      break
    case 'bun':
      H(5, 1, 6, 2, hair)
      H(7, 0, 2, 1, hair)
      HD(5, 3, hair)
      HD(10, 3, hair)
      HD(8, 0, hairLight)
      break
    case 'curly':
      H(5, 0, 6, 1, hair)
      H(4, 1, 8, 2, hair)
      HD(4, 3, hair)
      HD(11, 3, hair)
      HD(6, 1, hairLight)
      HD(9, 0, hairLight)
      break
  }
  if (back) {
    H(5, 3, 6, 3, hair)
    HD(6, 3, hairLight)
  }
  if (look.accessory === 'headphones') {
    H(5, 1, 6, 1, '#252a3a')
    H(4, 3, 1, 3, look.accent)
    H(11, 3, 1, 3, look.accent)
    HD(4, 2, '#252a3a')
    HD(11, 2, '#252a3a')
  } else if (look.accessory === 'cap') {
    H(5, 1, 6, 2, look.accent)
    HD(7, 1, '#ffffff')
    if (!back) H(5, 3, 6, 1, look.shirtDark)
  }
}

function hairSide(H: RectFn, HD: DotFn, look: Look) {
  const { hair, hairLight } = look
  H(5, 1, 6, 2, hair)
  H(5, 3, 2, 3, hair)
  HD(8, 1, hairLight)
  switch (look.hairStyle) {
    case 'long':
      H(5, 3, 2, 6, hair)
      break
    case 'bun':
      H(5, 0, 2, 2, hair)
      break
    case 'curly':
      H(5, 0, 5, 1, hair)
      H(4, 1, 1, 4, hair)
      break
    case 'cropped':
      H(5, 3, 1, 2, hair)
      break
    default:
      break
  }
  if (look.accessory === 'headphones') {
    H(6, 1, 4, 1, '#252a3a')
    H(7, 3, 2, 3, look.accent)
  } else if (look.accessory === 'cap') {
    H(5, 1, 6, 2, look.accent)
    H(10, 2, 3, 1, look.shirtDark)
  }
}

// -- the poses an employee can be in -------------------------------------------------------------
export const POSES: Record<string, Pose> = {
  stand_down: { dir: 'down' },
  stand_up: { dir: 'up' },
  stand_side: { dir: 'side' },
  stand_mug: { dir: 'down', arms: ['down', 'mug'], mouth: 'smile' },
  stand_cheer_a: { dir: 'down', arms: ['cheer_a', 'cheer_a'], mouth: 'smile' },
  stand_cheer_b: { dir: 'down', arms: ['cheer_b', 'cheer_b'], mouth: 'smile', bob: -1 },
  sit_idle: { dir: 'down', sit: true, arms: ['desk', 'desk'] },
  sit_blink: { dir: 'down', sit: true, arms: ['desk', 'desk'], eyes: 'blink' },
  sit_look_l: { dir: 'down', sit: true, arms: ['desk', 'desk'], eyes: 'left' },
  sit_look_r: { dir: 'down', sit: true, arms: ['desk', 'desk'], eyes: 'right' },
  sit_type_a: { dir: 'down', sit: true, arms: ['type_a', 'type_a'], eyes: 'left' },
  sit_type_b: { dir: 'down', sit: true, arms: ['type_b', 'type_b'], eyes: 'right' },
  sit_think: { dir: 'down', sit: true, arms: ['desk', 'chin'], eyes: 'right' },
  sit_think_b: { dir: 'down', sit: true, arms: ['desk', 'chin'], eyes: 'blink' },
  sit_clip: { dir: 'down', sit: true, arms: ['clip', 'desk'] },
  sit_clip_ok: { dir: 'down', sit: true, arms: ['clip_ok', 'desk'], mouth: 'smile' },
  sit_sleep: { dir: 'down', sit: true, arms: ['desk', 'desk'], eyes: 'sleep', head: 3 },
  sit_wave_a: { dir: 'down', sit: true, arms: ['desk', 'wave_a'], mouth: 'o', eyes: 'wide' },
  sit_wave_b: { dir: 'down', sit: true, arms: ['desk', 'wave_b'], mouth: 'o', eyes: 'wide' },
  sit_error: { dir: 'down', sit: true, arms: ['desk', 'desk'], eyes: 'wide', mouth: 'frown', flush: true },
  sit_cheer_a: { dir: 'down', sit: true, arms: ['cheer_a', 'cheer_a'], mouth: 'smile' },
  sit_cheer_b: { dir: 'down', sit: true, arms: ['cheer_b', 'cheer_b'], mouth: 'smile', bob: -1 },
  ...Object.fromEntries(
    [0, 1, 2, 3].flatMap((p) => [
      [`walk_down_${p}`, { dir: 'down', leg: p, bob: p % 2 ? -1 : 0 }],
      [`walk_up_${p}`, { dir: 'up', leg: p, bob: p % 2 ? -1 : 0 }],
      [`walk_side_${p}`, { dir: 'side', leg: p, bob: p % 2 ? -1 : 0 }],
    ]),
  ),
}

const cache = new Map<string, Record<string, Texture>>()

/** All frames for one employee as textures (built once per look). */
export function characterSheet(key: string, look: Look): Record<string, Texture> {
  const hit = cache.get(key)
  if (hit) return hit
  const sheet: Record<string, Texture> = {}
  for (const [name, pose] of Object.entries(POSES)) {
    const s = surface(16, 16)
    drawCharacter(s.g, look, pose)
    sheet[name] = toTexture(s)
  }
  cache.set(key, sheet)
  return sheet
}
