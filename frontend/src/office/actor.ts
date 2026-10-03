// One employee in the office: position, A* walking, errands (messages to colleagues) and the pose for every state.
import { Container, Rectangle, Sprite, type Texture } from 'pixi.js'
import { findPath, type Blocked, type Tile } from './astar'
import type { Particles } from './effects'
import { CONFETTI } from './effects'
import { TILE } from './layout'
import type { Icons } from './icons'
import { hash } from './pixel'
import type { Tone } from '../model'

const SPEED = 44 // world px per second (2.75 tiles/s)
const CODE_COLORS = ['#7aa2f7', '#9ece6a', '#e0af68', '#bb9af7', '#7dcfff']

export interface ActorEnv {
  blockedFor(id: string): Blocked
  particles: Particles
  icons: Icons
  iconLayer: Container
  coffeeSpot(id: string): Tile
  tempo(): number // replay speed: walking and talking keep up with a fast replay
  monitorTop(id: string): { x: number; y: number }
  say(id: string, text: string, tone: Tone, seconds: number): void
  receive(id: string, tone: Tone): void
}

interface Errand {
  to: string
  toSeat: Tile
  spot: Tile
  text: string
  tone: Tone
  stage: 'go' | 'dwell'
  dwell: number
}

type Mark = { tex: Texture; until: number } | null

const center = (t: Tile) => ({ x: t.x * TILE + TILE / 2, y: (t.y + 1) * TILE })
const same = (a: Tile, b: Tile) => a.x === b.x && a.y === b.y

export class Actor {
  readonly sprite: Sprite
  readonly shadow: Sprite
  readonly mark: Sprite
  pos: { x: number; y: number }
  tile: Tile
  path: Tile[] = []
  errands: Errand[] = []
  forced: string | null = null // debug: show a state without events
  private facing: 'down' | 'up' | 'side' = 'down'
  private flip = 1
  private walked = 0
  private seed: number
  private temp: Mark = null
  private lastSpawn = 0
  private lastState = 'idle'

  readonly id: string
  readonly seat: Tile
  readonly decorative: boolean
  private sheet: Record<string, Texture>
  private env: ActorEnv

  constructor(id: string, seat: Tile, sheet: Record<string, Texture>, env: ActorEnv, shadowTex: Texture, layer: Container, decorative = false) {
    this.id = id
    this.seat = seat
    this.sheet = sheet
    this.env = env
    this.decorative = decorative
    this.seed = (hash(id) % 1000) / 100
    this.tile = { ...seat }
    this.pos = center(seat)
    this.shadow = new Sprite(shadowTex)
    this.shadow.anchor.set(0.5, 0.5)
    this.sprite = new Sprite(sheet.sit_idle)
    this.sprite.anchor.set(0.5, 1)
    this.mark = new Sprite()
    this.mark.anchor.set(0.5, 1)
    this.mark.visible = false
    layer.addChild(this.shadow, this.sprite)
    env.iconLayer.addChild(this.mark)
    if (!decorative) {
      this.sprite.eventMode = 'static'
      this.sprite.cursor = 'pointer'
      this.sprite.hitArea = new Rectangle(-8, -16, 16, 16)
    }
  }

  /** The tile this employee is heading for or standing on (so two visitors never pick the same spot). */
  get claimed(): Tile[] {
    return [this.tile, ...(this.errands[0] ? [this.errands[0].spot] : [])]
  }

  get seated(): boolean {
    return !this.path.length && same(this.tile, this.seat)
  }

  /** Queue a walk to a colleague's desk. Old queued visits are dropped so a fast replay never lags behind. */
  visit(to: string, toSeat: Tile, spot: Tile, text: string, tone: Tone) {
    this.errands.push({ to, toSeat, spot, text, tone, stage: 'go', dwell: 2.6 + Math.min(2, text.length / 30) })
    if (this.errands.length > 3) this.errands.splice(1, this.errands.length - 3)
  }

  /** Forget queued visits (the build is over: everyone goes back to their desk). */
  dropErrands() {
    this.errands = []
  }

  flash(tex: Texture, seconds: number, now: number) {
    this.temp = { tex, until: now + seconds }
  }

  private desired(state: string): Tile {
    if (this.errands.length) return this.errands[0].spot
    if (state === 'loading_model') return this.env.coffeeSpot(this.id)
    return this.seat
  }

  update(dt: number, now: number, state: string) {
    if (state !== this.lastState) {
      if (state === 'error') this.flash(this.env.icons.bang, 2.5, now)
      this.lastState = state
    }
    if (!this.path.length) this.settle(dt, state)
    if (this.path.length) this.move(dt)
    this.render(now, state)
  }

  private settle(dt: number, state: string) {
    const err = this.errands[0]
    if (err && err.stage === 'dwell') {
      err.dwell -= dt * this.env.tempo()
      if (err.dwell <= 0) this.errands.shift()
      return
    }
    const want = this.desired(state)
    if (same(this.tile, want)) {
      if (err && err.stage === 'go') {
        err.stage = 'dwell'
        this.env.say(this.id, err.text, err.tone, err.dwell)
        this.env.receive(err.to, err.tone)
      }
      return
    }
    const p = findPath(this.env.blockedFor(this.id), this.tile, want)
    if (!p) {
      this.tile = { ...want } // never get stuck: snap
      this.pos = center(want)
      return
    }
    this.path = p.slice(1)
  }

  private move(dt: number) {
    let budget = SPEED * Math.min(this.env.tempo(), 3) * dt
    while (budget > 0 && this.path.length) {
      const next = center(this.path[0])
      const dx = next.x - this.pos.x
      const dy = next.y - this.pos.y
      const dist = Math.hypot(dx, dy)
      if (dist > 0.01) {
        if (Math.abs(dx) > Math.abs(dy)) {
          this.facing = 'side'
          this.flip = dx > 0 ? 1 : -1
        } else this.facing = dy > 0 ? 'down' : 'up'
      }
      if (dist <= budget) {
        this.pos = next
        this.tile = this.path.shift()!
        this.walked += dist
        budget -= dist
      } else {
        this.pos = { x: this.pos.x + (dx / dist) * budget, y: this.pos.y + (dy / dist) * budget }
        this.walked += budget
        budget = 0
      }
    }
    if (!this.path.length) this.facing = 'down'
  }

  private render(now: number, state: string) {
    const s = this.sheet
    const sp = this.sprite
    let name = 'sit_idle'
    let dx = 0
    let dy = 0
    sp.scale.x = 1
    const t = now + this.seed
    const moving = this.path.length > 0
    const seated = this.seated
    const err = this.errands[0]

    if (moving) {
      name = `walk_${this.facing}_${Math.floor(this.walked / 3.2) % 4}`
      if (this.facing === 'side') sp.scale.x = this.flip
    } else if (!seated) {
      if (err && err.stage === 'dwell') {
        const target = center(err.toSeat)
        name = 'stand_side'
        sp.scale.x = target.x >= this.pos.x ? 1 : -1
      } else if (state === 'loading_model') name = 'stand_mug'
      else if (state === 'celebrating') name = Math.floor(t * 4) % 2 ? 'stand_cheer_a' : 'stand_cheer_b'
      else name = 'stand_down'
    } else {
      switch (state) {
        case 'typing':
          name = Math.floor(t * 7) % 2 ? 'sit_type_a' : 'sit_type_b'
          break
        case 'executing':
          name = Math.floor(t * 2.5) % 2 ? 'sit_type_a' : 'sit_look_r'
          break
        case 'reading':
          name = Math.floor(t * 2.2) % 2 ? 'sit_look_l' : 'sit_look_r'
          break
        case 'thinking':
          name = t % 3.2 > 3 ? 'sit_think_b' : 'sit_think'
          break
        case 'testing':
          name = Math.floor(t * 1.4) % 2 ? 'sit_clip_ok' : 'sit_clip'
          break
        case 'sleeping':
          name = 'sit_sleep'
          dy = Math.floor(t * 0.9) % 2
          break
        case 'error':
          name = 'sit_error'
          dx = Math.floor(t * 22) % 2 ? 1 : -1
          break
        case 'waiting_human':
          name = Math.floor(t * 3.5) % 2 ? 'sit_wave_a' : 'sit_wave_b'
          break
        case 'celebrating':
          name = Math.floor(t * 4) % 2 ? 'sit_cheer_a' : 'sit_cheer_b'
          dy = Math.floor(t * 4) % 2 ? 0 : -1
          break
        default: {
          const ph = t % 6.5
          name = ph < 0.13 ? 'sit_blink' : ph > 3.1 && ph < 3.8 ? 'sit_look_l' : ph > 4.3 && ph < 5 ? 'sit_look_r' : 'sit_idle'
        }
      }
    }
    sp.texture = s[name] ?? s.sit_idle
    sp.x = Math.round(this.pos.x) + dx
    sp.y = Math.round(this.pos.y) + dy
    sp.zIndex = this.pos.y
    this.shadow.visible = !seated
    this.shadow.position.set(Math.round(this.pos.x), Math.round(this.pos.y) - 1)
    this.shadow.zIndex = this.pos.y - 0.5

    this.effects(now, state, seated, moving)
    this.renderMark(now, state, seated)
  }

  private effects(now: number, state: string, seated: boolean, moving: boolean) {
    const P = this.env.particles
    const head = { x: this.pos.x, y: this.pos.y - 14 }
    const gap = (every: number) => {
      if (now - this.lastSpawn < every) return false
      this.lastSpawn = now
      return true
    }
    if (seated && !this.decorative) {
      const m = this.env.monitorTop(this.id)
      if (state === 'typing' && gap(0.09)) {
        P.spawn({ x: m.x + (Math.random() * 10 - 5), y: m.y, vx: Math.random() * 6 - 3, vy: -18 - Math.random() * 10, life: 0.9, color: CODE_COLORS[Math.floor(Math.random() * 5)], w: 2, h: 1 })
      } else if (state === 'executing' && gap(0.12)) {
        P.spawn({ x: m.x + (Math.random() * 10 - 5), y: m.y, vy: -14, life: 0.8, color: '#56d364', w: 1, h: 1 })
      } else if (state === 'testing' && gap(0.7)) {
        P.spawn({ x: this.pos.x - 8, y: this.pos.y - 8, vy: -10, life: 0.9, color: '#34c759', w: 2, h: 2 })
      } else if (state === 'sleeping' && gap(1.3)) {
        P.spawn({ x: head.x + 6, y: head.y + 1, vx: 4, vy: -7, life: 2.4, tex: Math.random() > 0.5 ? this.env.icons.zA : this.env.icons.zB, sway: 2 })
      } else if (state === 'error' && gap(0.25)) {
        P.spawn({ x: m.x + (Math.random() * 8 - 4), y: m.y + 2, vx: Math.random() * 30 - 15, vy: -22, life: 0.45, color: '#ff5a5a', w: 1, h: 1, gravity: 90 })
      } else if (state === 'waiting_human' && gap(0.7)) {
        P.spawn({ x: head.x + 7, y: head.y - 6, vy: -4, life: 0.8, color: '#ffc233', w: 1, h: 1 })
      } else if (state === 'celebrating' && gap(0.18)) {
        P.spawn({ x: head.x + (Math.random() * 14 - 7), y: head.y - 10, vx: Math.random() * 20 - 10, vy: -6, life: 1.6, color: CONFETTI[Math.floor(Math.random() * CONFETTI.length)], w: 1, h: 2, gravity: 28 })
      }
    } else if (!moving && !seated && state === 'loading_model' && gap(0.35)) {
      P.spawn({ x: this.pos.x + 6, y: this.pos.y - 9, vx: 0, vy: -9, life: 1.1, color: '#e6ebf5', w: 1, h: 2, sway: 1.2, alpha: 0.8 })
    }
  }

  private renderMark(now: number, state: string, seated: boolean) {
    const ic = this.env.icons
    let tex: Texture | null = null
    let bob = 0
    if (this.temp && now < this.temp.until) {
      tex = this.temp.tex
      bob = Math.sin(now * 8) > 0 ? 1 : 0
    } else if (!this.decorative && seated) {
      if (state === 'error') tex = ic.bang
      else if (state === 'waiting_human') tex = ic.question
      else if (state === 'thinking') tex = ic.dots[Math.floor(now * 2.4) % 3]
      else if (state === 'reading') tex = ic.book
      else if (state === 'celebrating') tex = ic.heart
      if (tex) bob = Math.floor(now * 3) % 2
    }
    this.mark.visible = tex !== null
    if (tex) {
      this.mark.texture = tex
      this.mark.position.set(Math.round(this.pos.x), Math.round(this.pos.y) - 17 - bob)
      this.mark.zIndex = 99999
    }
  }

  get headY(): number {
    return this.pos.y - 16
  }
}
