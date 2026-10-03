// The pixel office: builds the world once, then every frame reads the model and animates it.
import { Application, CanvasSource, Container, Graphics, Sprite, Text, Texture } from 'pixi.js'
import { Actor, type ActorEnv } from './actor'
import type { Tile } from './astar'
import { characterSheet } from './characters'
import { CONFETTI, Particles } from './effects'
import * as F from './furniture'
import { icons } from './icons'
import { CHAIRS, COFFEE, COFFEE_SPOTS, COLS, PLANTS, RACKS, RECEPTION, RECEPTION_SEAT, ROWS, RUG, SOFA, TABLE, TILE, WORLD_H, WORLD_W, blockedFor, buildBlocked, visitSpots } from './layout'
import { COLORS, STATE_COLOR, STATE_LABEL, lookFor } from './palette'
import { hash, hexNum, toTexture, type Surface } from './pixel'
import { GLOW, paintScreen } from './screens'
import type { AgentView, OfficeModel, Tone, Visual } from '../model'

const FONT = 'Segoe UI, system-ui, -apple-system, Roboto, sans-serif'
const TONE: Record<Tone, { border: string; fill: string }> = {
  info: { border: '#6ea8ff', fill: '#16213f' },
  good: { border: '#4ade80', fill: '#12301f' },
  bad: { border: '#f87171', fill: '#3a1717' },
  warn: { border: '#fbbf24', fill: '#3a2c0d' },
}

interface Tag {
  box: Container
  bg: Graphics
  name: Text
  status: Text
  key: string
}

interface Bubble {
  box: Container
  until: number
  born: number
  agent: string
}

interface Desk {
  id: string
  seat: Tile
  screen: { surface: Surface; texture: Texture }
  glow: Sprite
  lastPaint: number
}

export interface SceneHooks {
  onSelect(id: string | null): void
}

export class OfficeScene {
  private app = new Application()
  private ready = false
  private destroyed = false
  private observer: ResizeObserver | null = null
  private world = new Container()
  private floor = new Container()
  private stage3d = new Container()
  private iconLayer = new Container()
  private glowLayer = new Container()
  private overlay = new Container()
  private particles = new Particles()
  private actors = new Map<string, Actor>()
  private desks = new Map<string, Desk>()
  private tags = new Map<string, Tag>()
  private bubbles: Bubble[] = []
  private scale = 4
  private ui = 1
  private sizeKey = ''
  private now = 0
  private selected: string | null = null
  private ring!: Sprite
  private vignette = new Sprite()
  private frame = new Graphics()
  private whiteboard = F.whiteboardCanvas()
  private whiteboardTex!: Texture
  private wbKey = ''
  private racks: { surface: Surface; tex: Texture; seed: number }[] = []
  private confettiUntil = 0
  private unsub: (() => void)[] = []
  private forced = new Map<string, string>()
  private coffee = new Map<string, Tile>()
  private tempo = 1
  private decorative: Actor | null = null
  private env!: ActorEnv
  private blocked = buildBlocked([])

  private host: HTMLElement
  private model: OfficeModel
  private hooks: SceneHooks

  constructor(host: HTMLElement, model: OfficeModel, hooks: SceneHooks) {
    this.host = host
    this.model = model
    this.hooks = hooks
  }

  async start() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    await this.app.init({ width: this.host.clientWidth || 800, height: this.host.clientHeight || 600, background: COLORS.ink, antialias: false, resolution: dpr, autoDensity: true, roundPixels: true })
    if (this.destroyed) {
      this.app.destroy(true)
      return
    }
    this.host.appendChild(this.app.canvas)
    this.app.canvas.style.display = 'block'
    this.app.stage.eventMode = 'static'
    this.app.stage.hitArea = this.app.screen
    this.app.stage.on('pointertap', (e) => {
      if (e.target === this.app.stage) this.hooks.onSelect(null)
    })

    this.stage3d.sortableChildren = true
    this.world.addChild(this.floor, this.stage3d, this.glowLayer, this.particles.layer, this.iconLayer)
    this.iconLayer.sortableChildren = true
    this.app.stage.addChild(this.world, this.vignette, this.frame, this.overlay)

    this.buildWorld()
    this.syncRoster()
    this.unsub.push(this.model.onVisual((v) => this.act(v)))
    this.unsub.push(this.model.subscribe(() => this.syncRoster()))
    // Pixi only follows window resizes; the panels opening and closing resize this element instead.
    this.observer = new ResizeObserver(() => {
      const w = Math.max(1, this.host.clientWidth)
      const h = Math.max(1, this.host.clientHeight)
      if (w !== this.app.screen.width || h !== this.app.screen.height) this.app.renderer.resize(w, h)
    })
    this.observer.observe(this.host)
    this.app.ticker.add((t) => this.tick(t.deltaMS / 1000))
    this.ready = true
    this.fit()
  }

  destroy() {
    this.destroyed = true
    this.unsub.forEach((u) => u())
    this.observer?.disconnect()
    if (this.ready) this.app.destroy(true, { children: true })
  }

  // -- debugging / presentation hooks ---------------------------------------------------------
  forceState(id: string, state: string | null) {
    if (state) this.forced.set(id, state)
    else this.forced.delete(id)
  }

  setTempo(n: number) {
    this.tempo = Math.max(1, Math.min(n, 8))
  }

  select(id: string | null) {
    this.selected = id
  }

  // -- world construction -----------------------------------------------------------------------
  private buildWorld() {
    const floorCache = new Map<string, Texture>()
    const floorTex = (kind: 'carpet' | 'tile' | 'wood', tx: number, ty: number) => {
      const k = `${kind}${tx % 6}${ty % 6}`
      if (!floorCache.has(k)) floorCache.set(k, F.floorTile(kind, tx % 6, ty % 6))
      return floorCache.get(k)!
    }
    for (let ty = 2; ty < ROWS; ty++) {
      for (let tx = 0; tx < COLS; tx++) {
        const kind = tx >= 14 && ty >= 7 ? 'tile' : tx <= 3 && ty >= 8 ? 'wood' : 'carpet'
        const s = new Sprite(floorTex(kind, tx, ty))
        s.position.set(tx * TILE, ty * TILE)
        this.floor.addChild(s)
      }
    }
    const rug = new Sprite(F.rugTexture(RUG.w, RUG.h))
    rug.position.set(RUG.x * TILE, RUG.y * TILE)
    this.floor.addChild(rug)
    const wall = new Sprite(F.wallStrip())
    this.floor.addChild(wall)
    this.whiteboardTex = toTexture(this.whiteboard)
    const wb = new Sprite(this.whiteboardTex)
    wb.position.set(71, 5)
    this.floor.addChild(wb)

    const add = (tex: Texture, x: number, y: number, z: number) => {
      const s = new Sprite(tex)
      s.position.set(x, y)
      s.zIndex = z
      this.stage3d.addChild(s)
      return s
    }
    // racks (with live LEDs)
    const rackFrame = F.rackFrame()
    RACKS.forEach((r, i) => {
      add(rackFrame, r.x * TILE, r.y * TILE, (r.y + r.h) * TILE)
      const surf = F.rackLights()
      const tex = toTexture(surf)
      add(tex, r.x * TILE, r.y * TILE, (r.y + r.h) * TILE + 0.1)
      this.racks.push({ surface: surf, tex, seed: i * 1.7 })
    })
    add(F.sofa(), SOFA.x * TILE, SOFA.y * TILE - 4, (SOFA.y + 1) * TILE)
    add(F.coffeeMachine(), COFFEE.x * TILE, COFFEE.y * TILE, (COFFEE.y + COFFEE.h) * TILE)
    PLANTS.forEach((p, i) => add(F.plant(i), p.x * TILE, (p.y + 1) * TILE - 24, (p.y + 1) * TILE))
    add(F.meetingTable(), TABLE.x * TILE, TABLE.y * TILE, (TABLE.y + TABLE.h) * TILE - 3)
    CHAIRS.forEach((c) => add(F.meetingChair(c.y === 11), c.x * TILE + 2, c.y * TILE + 1, c.y === 11 ? (c.y + 1) * TILE : c.y * TILE + 4))
    add(F.receptionDesk(), RECEPTION.x * TILE, (RECEPTION_SEAT.y + 1) * TILE - 2, (RECEPTION_SEAT.y + 2) * TILE)

    this.ring = new Sprite(F.shadow(18, 7))
    this.ring.anchor.set(0.5)
    this.ring.tint = 0x7cc4ff
    this.ring.visible = false
    this.floor.addChild(this.ring)
  }

  private syncRoster() {
    const have = new Set(this.actors.keys())
    const roster = [...this.model.agents.values()]
    if (roster.length === have.size && roster.every((a) => have.has(a.id))) {
      this.updateWhiteboard()
      return
    }
    // (re)build employees
    this.actors.forEach((a) => {
      a.sprite.destroy()
      a.shadow.destroy()
      a.mark.destroy()
    })
    this.actors.clear()
    this.desks.forEach((d) => d.glow.destroy())
    this.desks.clear()
    this.tags.forEach((t) => t.box.destroy({ children: true }))
    this.tags.clear()
    this.stage3d.children.filter((c) => (c as Sprite & { __desk?: boolean }).__desk).forEach((c) => c.destroy())

    const seats = roster.map((a) => ({ x: a.desk[0], y: a.desk[1] }))
    this.blocked = buildBlocked(seats)
    const shadow = F.shadow(10, 4)
    const glow = F.glow(16)
    const frame = F.monitorFrame()
    const add = (tex: Texture, x: number, y: number, z: number) => {
      const s = new Sprite(tex) as Sprite & { __desk?: boolean }
      s.position.set(x, y)
      s.zIndex = z
      s.__desk = true
      this.stage3d.addChild(s)
      return s
    }
    this.env = {
      blockedFor: (id) => blockedFor(this.blocked, [...this.actors.values()].map((a) => a.seat), this.actors.get(id)?.seat ?? RECEPTION_SEAT),
      particles: this.particles,
      icons: icons(),
      iconLayer: this.iconLayer,
      coffeeSpot: (id) => this.coffeeSpot(id),
      tempo: () => this.tempo,
      monitorTop: (id) => {
        const s = this.desks.get(id)!.seat
        return { x: s.x * TILE + 24, y: (s.y + 1) * TILE - 9 }
      },
      say: (id, text, tone, secs) => this.bubble(id, text, tone, secs),
      receive: (id, tone) => this.actors.get(id)?.flash(tone === 'bad' ? icons().bang : icons().mail, 1.6, this.now),
    }
    for (const a of roster) {
      const seat = { x: a.desk[0], y: a.desk[1] }
      const look = lookFor(a.id, a.sprite.palette, a.sprite.accessory)
      add(F.chairTexture(look.shirt), seat.x * TILE + 1, seat.y * TILE + 1, (seat.y + 1) * TILE - 0.3)
      add(F.deskTexture(a.id, look.shirt), seat.x * TILE, (seat.y + 1) * TILE - 2, (seat.y + 2) * TILE)
      const mon = add(frame, seat.x * TILE + 16, (seat.y + 1) * TILE - 6, (seat.y + 2) * TILE + 0.1)
      const screen = F.makeScreen()
      add(screen.texture, mon.x + 1, mon.y + 1, (seat.y + 2) * TILE + 0.2)
      const g = new Sprite(glow)
      g.anchor.set(0.5)
      g.blendMode = 'add'
      g.position.set(mon.x + 8, mon.y + 6)
      g.alpha = 0
      this.glowLayer.addChild(g)
      this.desks.set(a.id, { id: a.id, seat, screen, glow: g, lastPaint: -1 })
      const actor = new Actor(a.id, seat, characterSheet(a.id, look), this.env, shadow, this.stage3d, false)
      actor.sprite.on('pointertap', () => this.hooks.onSelect(a.id))
      this.actors.set(a.id, actor)
      this.makeTag(a)
    }
    // Decorative (not an agent): the receptionist. Never clickable, never in the roster.
    const rl = lookFor('receptionist', 'orange', 'headphones')
    this.decorative?.sprite.destroy()
    this.decorative = new Actor('receptionist', RECEPTION_SEAT, characterSheet('receptionist', rl), this.env, shadow, this.stage3d, true)
  }

  // -- labels and bubbles -----------------------------------------------------------------------
  private makeTag(a: AgentView) {
    const box = new Container()
    const bg = new Graphics()
    const name = new Text({ text: a.name, style: { fontFamily: FONT, fontSize: 14, fontWeight: '700', fill: '#f2f4fa' }, resolution: this.app.renderer.resolution })
    const status = new Text({ text: '', style: { fontFamily: FONT, fontSize: 11, fontWeight: '600', fill: '#9aa3b8' }, resolution: this.app.renderer.resolution })
    box.addChild(bg, name, status)
    box.eventMode = 'static'
    box.cursor = 'pointer'
    box.on('pointertap', () => this.hooks.onSelect(a.id))
    this.overlay.addChild(box)
    this.tags.set(a.id, { box, bg, name, status, key: '' })
  }

  private bubble(id: string, text: string, tone: Tone, seconds: number) {
    this.bubbles = this.bubbles.filter((b) => {
      if (b.agent !== id) return true
      b.box.destroy({ children: true })
      return false
    })
    const u = this.ui
    const c = TONE[tone]
    const box = new Container()
    const label = new Text({ text, style: { fontFamily: FONT, fontSize: 14 * u, fontWeight: '600', fill: '#f4f6fc', wordWrap: true, wordWrapWidth: 210 * u, align: 'center' }, resolution: this.app.renderer.resolution })
    label.anchor.set(0.5, 0)
    const padX = 10 * u
    const padY = 6 * u
    const w = Math.max(40 * u, label.width) + padX * 2
    const h = label.height + padY * 2
    const g = new Graphics()
    const cut = 3 * u
    // chamfered "pixel" bubble with a tail
    g.poly([cut, 0, w - cut, 0, w, cut, w, h - cut, w - cut, h, w / 2 + 6 * u, h, w / 2, h + 7 * u, w / 2 - 6 * u, h, cut, h, 0, h - cut, 0, cut]).fill(c.fill).stroke({ width: Math.max(2, 2 * u), color: hexNum(c.border) })
    g.position.set(-w / 2, -h - 7 * u)
    label.position.set(0, -h - 7 * u + padY)
    box.addChild(g, label)
    this.overlay.addChild(box)
    this.bubbles.push({ box, until: this.now + seconds / Math.min(this.tempo, 2), born: this.now, agent: id })
  }

  // -- reacting to events -----------------------------------------------------------------------
  private act(v: Visual) {
    switch (v.kind) {
      case 'message': {
        const from = this.actors.get(v.from)
        const to = this.actors.get(v.to)
        if (from && to) from.visit(v.to, to.seat, this.pickSpot(to.seat, v.from), v.text, v.tone)
        else if (from) this.bubble(v.from, v.text, v.tone, 3)
        break
      }
      case 'say':
        this.bubble(v.agent, v.text, v.tone, 3.2)
        break
      case 'test':
        this.actors.get(v.agent)?.flash(v.ok ? icons().check : icons().cross, 2, this.now)
        break
      case 'alert':
        this.actors.get(v.agent)?.flash(icons().bang, 3, this.now)
        break
      case 'reset':
        this.actors.forEach((a) => a.dropErrands())
        this.bubbles.forEach((b) => b.box.destroy({ children: true }))
        this.bubbles = []
        this.particles.clear()
        this.confettiUntil = 0
        break
      case 'celebrate':
        if (v.agents) {
          // An Ask-employee request: confetti around the people who did the work, not over the whole office.
          for (const id of v.agents) {
            const a = this.actors.get(id)
            if (a) this.burstAround(a.pos.x, a.pos.y - 8)
          }
          break
        }
        this.actors.forEach((a) => a.dropErrands())
        this.confettiUntil = this.now + 7
        this.burst()
        break
    }
  }

  /** Each employee on a coffee break keeps one spot; spots are handed out first-free. */
  private coffeeSpot(id: string): Tile {
    const have = this.coffee.get(id)
    if (have) return have
    const used = new Set([...this.coffee.values()].map((t) => `${t.x},${t.y}`))
    const spot = COFFEE_SPOTS.find((t) => !used.has(`${t.x},${t.y}`)) ?? COFFEE_SPOTS[0]
    this.coffee.set(id, spot)
    return spot
  }

  private pickSpot(seat: Tile, visitor: string): Tile {
    const taken = new Set<string>()
    for (const [id, a] of this.actors) if (id !== visitor) a.claimed.forEach((t) => taken.add(`${t.x},${t.y}`))
    const spots = visitSpots(seat).filter((t) => !this.blocked[t.y]?.[t.x])
    return spots.find((t) => !taken.has(`${t.x},${t.y}`)) ?? spots[0]
  }

  /** A small confetti burst centred on one employee. */
  private burstAround(cx: number, cy: number) {
    for (let i = 0; i < 28; i++) {
      const ang = Math.random() * Math.PI * 2
      const speed = 8 + Math.random() * 16
      this.particles.spawn({
        x: cx + Math.cos(ang) * 4, y: cy + Math.sin(ang) * 3, vx: Math.cos(ang) * speed, vy: Math.sin(ang) * speed - 14,
        life: 1.1 + Math.random() * 0.7, color: CONFETTI[i % CONFETTI.length], w: 1, h: 2, gravity: 40, fade: true,
      })
    }
  }

  private burst() {
    for (let i = 0; i < 90; i++) {
      this.particles.spawn({
        x: Math.random() * WORLD_W, y: 8 + Math.random() * 30, vx: Math.random() * 24 - 12, vy: 10 + Math.random() * 20,
        life: 2.4 + Math.random() * 1.4, color: CONFETTI[i % CONFETTI.length], w: 2, h: 3, gravity: 16, sway: 3, fade: true,
      })
    }
  }

  // -- layout -----------------------------------------------------------------------------------
  private fit() {
    const W = this.app.screen.width
    const H = this.app.screen.height
    const dpr = this.app.renderer.resolution
    const margin = 14
    const fitX = ((W - margin * 2) * dpr) / WORLD_W
    const fitY = ((H - margin * 2) * dpr) / WORLD_H
    let fit = Math.min(fitX, fitY)
    // Whole device pixels per art pixel keep the art razor sharp. Only fall back to half steps when whole steps would waste over 20% of the room.
    if (fit >= 1) {
      const whole = Math.floor(fit)
      fit = fit / whole < 1.2 ? whole : Math.floor(fit * 2) / 2
    }
    this.scale = Math.max(0.4, fit / dpr)
    this.ui = Math.max(0.75, Math.min(1.5, this.scale / 4))
    const ox = Math.round((W - WORLD_W * this.scale) / 2)
    const oy = Math.round((H - WORLD_H * this.scale) / 2)
    this.world.scale.set(this.scale)
    this.world.position.set(ox, oy)

    // vignette
    const c = document.createElement('canvas')
    c.width = 256
    c.height = 160
    const g = c.getContext('2d')!
    const grad = g.createRadialGradient(128, 80, 40, 128, 80, 160)
    grad.addColorStop(0, 'rgba(8,10,20,0)')
    grad.addColorStop(1, 'rgba(8,10,20,0.62)')
    g.fillStyle = grad
    g.fillRect(0, 0, 256, 160)
    const old = this.vignette.texture
    this.vignette.texture = new Texture({ source: new CanvasSource({ resource: c }) })
    if (old !== Texture.EMPTY) old.destroy(true)
    this.vignette.position.set(0, 0)
    this.vignette.setSize(W, H)
    this.vignette.eventMode = 'none'

    // frame around the office
    this.frame.clear()
    this.frame.rect(ox - 3, oy - 3, WORLD_W * this.scale + 6, WORLD_H * this.scale + 6).stroke({ width: 3, color: 0x232a42 })
    this.frame.rect(ox - 6, oy - 6, WORLD_W * this.scale + 12, WORLD_H * this.scale + 12).stroke({ width: 1, color: 0x151a2c })
    this.frame.eventMode = 'none'
    this.tags.forEach((t) => (t.key = ''))
    this.bubbles.forEach((b) => b.box.destroy({ children: true }))
    this.bubbles = []
  }

  private toScreen(x: number, y: number) {
    return { x: this.world.x + x * this.scale, y: this.world.y + y * this.scale }
  }

  private updateWhiteboard() {
    const key = this.model.tasks.map((t) => t.status).join(',') + this.model.tasks.length
    if (key === this.wbKey) return
    this.wbKey = key
    F.paintWhiteboard(this.whiteboard, this.model.tasks)
    this.whiteboardTex.source.update()
  }

  // -- per frame --------------------------------------------------------------------------------
  private tick(dt: number) {
    dt = Math.min(dt, 0.1)
    this.now += dt
    const key = `${this.app.screen.width}x${this.app.screen.height}`
    if (key !== this.sizeKey) {
      this.sizeKey = key
      this.fit()
    }
    const busy = Math.min(1, this.model.activeCount / 3)

    for (const [id, actor] of this.actors) {
      const view = this.model.agents.get(id)
      if (!view) continue
      const state = this.forced.get(id) ?? view.state
      if (state !== 'loading_model') this.coffee.delete(id)
      actor.update(dt, this.now, state)
      const desk = this.desks.get(id)!
      if (this.now - desk.lastPaint > 0.1) {
        desk.lastPaint = this.now
        paintScreen(desk.screen.surface.g, state, this.now, hash(id) % 97)
        desk.screen.texture.source.update()
      }
      const [col, a] = GLOW[state] ?? GLOW.idle
      desk.glow.tint = hexNum(col)
      desk.glow.alpha = a * (0.85 + 0.15 * Math.sin(this.now * 7 + hash(id)))
      desk.glow.scale.set(state === 'executing' || state === 'error' ? 1.15 : 0.95)
    }
    if (this.decorative) {
      const ph = this.now % 11
      this.decorative.forced = null
      const wave = ph > 7 && ph < 8.4
      this.decorative.update(dt, this.now, wave ? 'waiting_human' : 'idle')
    }
    this.racks.forEach((r, i) => {
      F.paintRackLights(r.surface, this.now, busy, r.seed + i)
      r.tex.source.update()
    })
    if (this.now < this.confettiUntil && Math.random() < 0.9) {
      this.particles.spawn({ x: Math.random() * WORLD_W, y: 4, vx: Math.random() * 16 - 8, vy: 12, life: 3, color: CONFETTI[Math.floor(Math.random() * 6)], w: 2, h: 3, gravity: 14, sway: 3 })
    }
    this.particles.update(dt)
    this.updateRing()
    this.updateOverlay()
  }

  private updateRing() {
    const a = this.selected ? this.actors.get(this.selected) : null
    this.ring.visible = !!a
    if (a) {
      this.ring.position.set(Math.round(a.pos.x), Math.round(a.pos.y) - 1)
      this.ring.alpha = 0.5 + 0.3 * Math.sin(this.now * 5)
      this.ring.scale.set(1.15)
    }
  }

  private updateOverlay() {
    const u = this.ui
    for (const [id, actor] of this.actors) {
      const tag = this.tags.get(id)
      const view = this.model.agents.get(id)
      if (!tag || !view) continue
      const state = this.forced.get(id) ?? view.state
      const away = !actor.seated
      const shown = away && state === 'idle' ? 'walking' : state
      const key = `${shown}|${this.selected === id}|${view.task?.id ?? ''}|${u.toFixed(2)}`
      if (key !== tag.key) {
        tag.key = key
        const col = STATE_COLOR[shown] ?? '#7c8499'
        tag.name.style.fontSize = 14 * u
        tag.status.style.fontSize = 11 * u
        tag.status.text = `● ${STATE_LABEL[shown] ?? shown}${view.task && shown !== 'idle' && shown !== 'walking' ? ' · ' + view.task.id : ''}`
        tag.status.style.fill = col
        const w = Math.max(tag.name.width, tag.status.width) + 14 * u
        const h = tag.name.height + tag.status.height + 6 * u
        tag.bg.clear()
        tag.bg.roundRect(0, 0, w, h, 4 * u).fill({ color: 0x0b0e1a, alpha: 0.86 }).stroke({ width: this.selected === id ? 2 : 1, color: this.selected === id ? 0x7cc4ff : 0x2a3350 })
        tag.name.position.set((w - tag.name.width) / 2, 3 * u)
        tag.status.position.set((w - tag.status.width) / 2, 3 * u + tag.name.height)
        tag.box.pivot.set(w / 2, 0)
      }
      const anchorX = away ? actor.pos.x : actor.seat.x * TILE + TILE
      const anchorY = away ? actor.pos.y + 2 : (actor.seat.y + 2) * TILE + 1
      const p = this.toScreen(anchorX, anchorY)
      tag.box.position.set(Math.round(p.x), Math.round(p.y))
    }
    // bubbles
    this.bubbles = this.bubbles.filter((b) => {
      const age = this.now - b.born
      const left = b.until - this.now
      if (left <= 0) {
        b.box.destroy({ children: true })
        return false
      }
      const actor = this.actors.get(b.agent)
      if (!actor) return true
      const p = this.toScreen(actor.pos.x, actor.headY - (actor.mark.visible ? 7 : 1))
      const pop = Math.min(1, age / 0.18)
      b.box.alpha = Math.min(pop, left / 0.3)
      b.box.scale.set(0.85 + 0.15 * pop)
      b.box.position.set(Math.round(p.x), Math.round(p.y))
      return true
    })
  }
}
