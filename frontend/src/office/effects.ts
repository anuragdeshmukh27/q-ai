// Pooled particles in world space: code glyphs, steam, sparks, Zzz, confetti. One pixel of world = one pixel of art.
import { Container, Sprite, Texture } from 'pixi.js'
import { hexNum } from './pixel'

interface P {
  s: Sprite
  vx: number
  vy: number
  life: number
  max: number
  g: number
  sway: number
  phase: number
  fade: boolean
  baseX: number
  y: number
  hw: number
  hh: number
  spin: number
}

export interface Spawn {
  x: number
  y: number
  vx?: number
  vy?: number
  life?: number
  color?: string
  w?: number
  h?: number
  gravity?: number
  tex?: Texture
  fade?: boolean
  sway?: number
  spin?: number
  alpha?: number
}

export class Particles {
  readonly layer = new Container()
  private live: P[] = []
  private free: Sprite[] = []

  constructor() {
    this.layer.zIndex = 100000
    this.layer.sortableChildren = false
  }

  spawn(o: Spawn) {
    if (this.live.length > 700) return
    const s = this.free.pop() ?? new Sprite(Texture.WHITE)
    s.texture = o.tex ?? Texture.WHITE
    s.tint = o.tex ? 0xffffff : hexNum(o.color ?? '#ffffff')
    s.anchor.set(0)
    if (o.tex) s.scale.set(1)
    else s.setSize(o.w ?? 1, o.h ?? 1)
    const hw = Math.floor((o.tex ? o.tex.width : (o.w ?? 1)) / 2)
    const hh = Math.floor((o.tex ? o.tex.height : (o.h ?? 1)) / 2)
    s.alpha = o.alpha ?? 1
    s.rotation = 0
    s.position.set(o.x, o.y)
    this.layer.addChild(s)
    this.live.push({ s, vx: o.vx ?? 0, vy: o.vy ?? 0, life: o.life ?? 1, max: o.life ?? 1, g: o.gravity ?? 0, sway: o.sway ?? 0, phase: Math.random() * 6, fade: o.fade ?? true, baseX: o.x, y: o.y, hw, hh, spin: o.spin ?? 0 })
  }

  update(dt: number) {
    for (let i = this.live.length - 1; i >= 0; i--) {
      const p = this.live[i]
      p.life -= dt
      if (p.life <= 0) {
        this.layer.removeChild(p.s)
        this.free.push(p.s)
        this.live.splice(i, 1)
        continue
      }
      p.vy += p.g * dt
      p.baseX += p.vx * dt
      p.y += p.vy * dt
      p.s.x = Math.round(p.baseX + (p.sway ? Math.sin((p.max - p.life) * 3 + p.phase) * p.sway : 0)) - p.hw
      p.s.y = Math.round(p.y) - p.hh
      if (p.spin) p.s.rotation += p.spin * dt
      if (p.fade) p.s.alpha = Math.min(1, (p.life / p.max) * 2)
    }
  }

  clear() {
    for (const p of this.live) {
      this.layer.removeChild(p.s)
      this.free.push(p.s)
    }
    this.live = []
  }
}

export const CONFETTI = ['#ff5a5a', '#ffc233', '#3ddc6c', '#5aa7ff', '#c084fc', '#ff7ad9']
