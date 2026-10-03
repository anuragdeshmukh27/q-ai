// Colour palettes. Shirt colours come from `sprite.palette` in config/agents.yaml; everything else is derived in code.
import { darken, hash, lighten } from './pixel'

export const SHIRTS: Record<string, string> = {
  indigo: '#5b6cf0',
  teal: '#22b8a8',
  green: '#4fbf5f',
  pink: '#ee6fa8',
  orange: '#f09a3e',
  slate: '#7d8aa3',
  purple: '#a86bea',
  red: '#e5584f',
  default: '#8aa0c0',
}

const SKINS = ['#f2c9a0', '#e0a679', '#c58a5c', '#8d5a3a', '#f5d6b8', '#a56e47']
const HAIRS = ['#2a1d17', '#4a2f1e', '#1b1b24', '#6b4226', '#8a6a3b', '#3a3a46']
const PANTS = ['#2f3b5a', '#3a3f4f', '#47396b', '#34495e', '#2b4a45']

export type HairStyle = 'short' | 'long' | 'bun' | 'curly' | 'cropped'
export type Accessory = 'glasses' | 'clipboard' | 'headphones' | 'cap' | 'tie' | 'none'

export interface Look {
  skin: string
  skinShade: string
  hair: string
  hairLight: string
  hairStyle: HairStyle
  shirt: string
  shirtDark: string
  shirtLight: string
  pants: string
  pantsDark: string
  shoe: string
  accessory: Accessory
  accent: string
}

// Hair styles are fixed per role so each employee is recognisable at a glance.
const STYLE: Record<string, HairStyle> = {
  architect: 'short', planner: 'long', backend: 'curly', frontend: 'bun', database: 'cropped', integrator: 'short', qa: 'long', reviewer: 'cropped',
}

export function lookFor(id: string, palette: string, accessory: string): Look {
  const h = hash(id)
  const shirt = SHIRTS[palette] ?? SHIRTS.default
  const pants = PANTS[(h >>> 3) % PANTS.length]
  const skin = SKINS[h % SKINS.length]
  const hair = HAIRS[(h >>> 5) % HAIRS.length]
  return {
    skin, skinShade: darken(skin, 0.14),
    hair, hairLight: lighten(hair, 0.22),
    hairStyle: STYLE[id] ?? (['short', 'long', 'bun', 'curly', 'cropped'] as const)[h % 5],
    shirt, shirtDark: darken(shirt, 0.25), shirtLight: lighten(shirt, 0.2),
    pants, pantsDark: darken(pants, 0.25), shoe: '#1a1b22',
    accessory: (['glasses', 'clipboard', 'headphones', 'cap', 'tie'].includes(accessory) ? accessory : 'none') as Accessory,
    accent: lighten(shirt, 0.35),
  }
}

// UI + world colours
export const COLORS = {
  ink: '#0b0d12',
  floorA: '#33425e',
  floorB: '#2f3d58',
  wall: '#1c2438',
  wallLight: '#27324d',
  base: '#12172a',
  wood: '#8a5a3a',
  woodDark: '#6a4229',
  woodLight: '#a8734c',
  good: '#4ade80',
  bad: '#f87171',
  warn: '#fbbf24',
  info: '#60a5fa',
}

export const STATE_COLOR: Record<string, string> = {
  idle: '#7c8499',
  thinking: '#a78bfa',
  typing: '#60a5fa',
  reading: '#38bdf8',
  executing: '#4ade80',
  testing: '#fbbf24',
  walking: '#94a3b8',
  sleeping: '#64748b',
  loading_model: '#fb923c',
  error: '#f87171',
  celebrating: '#f472b6',
  waiting_human: '#fbbf24',
}

export const STATE_LABEL: Record<string, string> = {
  idle: 'idle',
  thinking: 'thinking',
  typing: 'typing',
  reading: 'reading',
  executing: 'running',
  testing: 'testing',
  walking: 'on the move',
  sleeping: 'sleeping',
  loading_model: 'coffee break',
  error: 'error',
  celebrating: 'celebrating',
  waiting_human: 'needs you',
}
