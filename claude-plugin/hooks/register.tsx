// ThinSpec inside Claude Code: the design graph in a pane beside the
// transcript, the current task's budget in a line above the prompt, and the
// one command a person has, /thinspec, which opens the pane.
//
// This module only draws. Every fact comes from `thinspec state --json`, so
// the pane, the terminal and the agent's tools can never disagree.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, RenderElement } from 'claude-code'

import type { AbsNode, AbsSession, AbsSnapshot, AbsTask } from '../types'

const PANE = 'thinspec'
const TITLE = 'ThinSpec'

// Change the tag when the snapshot's fields change: it declines what an
// earlier version stored, which outlives a reload.
const snapshot = atom({ plugin: 'thinspec', key: 'snapshot' } as const, null, {
  shape: 'snapshot-2',
})
const selected = atom({ plugin: 'thinspec', key: 'selected' } as const, null)
// Why the last read of the state failed; null when it went well.
const problem = atom({ plugin: 'thinspec', key: 'problem' } as const, null)
// The parts the person opened, each "<node>/<part>": a part is told in one sentence until then.
const opened = atom({ plugin: 'thinspec', key: 'opened' } as const, [])
// The quote a press last put in the prompt box, as written: the next press replaces it.
const quoted = atom({ plugin: 'thinspec', key: 'quoted' } as const, null)

// A budget is in runs of the check and lines changed. Edits and minutes were
// budgeted by earlier versions, and such a budget is still shown.
const METRICS = ['trials', 'lines', 'patches', 'minutes'] as const
const UNIT = { trials: 'trials', lines: 'lines', patches: 'patches', minutes: 'min' } as const

const MARK: Record<string, string> = {
  planned: '○',
  active: '●',
  blocked: '⏸',
  done: '✓',
  banned: '✗',
  stepped_back: '↩',
  abandoned: '–',
}

type Tone = 'success' | 'warning' | 'error'
const HEALTH: Record<string, { glyph: string; word: string; tone?: Tone }> = {
  ok: { glyph: '✓', word: 'on budget', tone: 'success' },
  watch: { glyph: '!', word: 'watch', tone: 'warning' },
  step_back: { glyph: '↩', word: 'step back', tone: 'error' },
  idle: { glyph: '·', word: 'no work yet' },
}
const IDLE = { glyph: '·', word: 'no work yet' } as { glyph: string; word: string; tone?: Tone }

// The order open work is shown in: what waits for the person, what is being
// worked on, what is planned.
const SHOWN_FIRST: Record<string, number> = { blocked: 0, active: 1, planned: 2 }
const NAMED = 5 // open tasks named in the box of a node; the rest are counted

const num = (v: number): string =>
  Number.isInteger(v) ? String(v) : String(Math.round(v * 10) / 10)

const isOpen = (t: AbsTask): boolean =>
  t.status === 'active' || t.status === 'blocked'

const healthOf = (n: AbsNode) => HEALTH[n.health.level] ?? IDLE

/** After a component's name where the tree is text: it carries designs out, it is not one. */
const partMark = (n: AbsNode): string => (n.kind === 'component' ? ' (component)' : '')

/** "4/4 trials · 16/20 patches · 57/60 min", for the metrics that have a budget. */
function usage(t: AbsTask): string {
  const parts = METRICS.filter(m => (t.budget[m] ?? 0) > 0).map(
    m => `${num(t.actual[m] ?? 0)}/${num(t.budget[m] ?? 0)} ${UNIT[m]}`,
  )

  return parts.join(' · ') || 'no budget'
}

/** How a session is named to the person looking: "you" for the one they are in. */
const sessionName = (s: AbsSession): string =>
  s.me ? 'you' : s.here ? s.name : `${s.name} on ${s.host ?? 'another machine'}`

/** The sessions whose latest work is on this task, by name; '' when none is. */
const who = (data: AbsSnapshot, t: AbsTask): string =>
  (data.sessions ?? [])
    .filter(s => s.task === t.id)
    .map(sessionName)
    .join(', ')

// What a session is doing, as a mark. One that waits for its person is the
// one state here that needs somebody, so it alone takes a tone.
const DOING: Record<string, { glyph: string; tone?: Tone }> = {
  working: { glyph: '●' },
  waiting: { glyph: '◌', tone: 'warning' },
  quiet: { glyph: '·' },
}

/** One session in a line: what it is doing, who it is, and the task it is on. */
function sessionLine(data: AbsSnapshot, s: AbsSession): string {
  const t = data.tasks.find(x => x.id === s.task)
  const task = t === undefined ? 'no task declared' : t.title

  return `${DOING[s.state]?.glyph ?? '·'} ${sessionName(s)} · ${task}`
}

/** Under that line: the design above the task, how far into the budget, and since when. */
function sessionDetail(data: AbsSnapshot, s: AbsSession): string {
  const t = data.tasks.find(x => x.id === s.task)
  const design = data.nodes.find(n => n.id === t?.parent)
  const state =
    s.state === 'waiting'
      ? `waiting for ${s.me ? 'you' : 'its person'} since ${s.since}`
      : s.state === 'quiet'
        ? `quiet since ${s.since}`
        : 'working'

  return [...(t === undefined ? [] : [design?.title ?? t.parent, usage(t)]), state].join(' · ')
}

/** Who is on a task, short enough to sit in its mark: "you", or the end of a session's name. */
function tagOf(data: AbsSnapshot, t: AbsTask): string {
  const on = (data.sessions ?? []).filter(s => s.task === t.id)
  const first = on[0]

  if (first === undefined || !isOpen(t)) return ''

  const short = first.me ? 'you' : (first.name.split(' ').pop() ?? first.name)

  return on.length > 1 ? `${short} +${on.length - 1}` : short
}

/**
 * A node's story, in the order it is written: one part for each step it
 * names (**Motivation.** **Challenge.** **Approach.**, or **Insight.** for the
 * core). A summary that names no step is one part with no label.
 */
function storyOf(node: AbsNode): { label: string; text: string }[] {
  const cut = node.summary.split(/\*\*(Motivation|Challenge|Insight|Approach)\.\*\*/)
  const out: { label: string; text: string }[] = []
  const lead = (cut[0] ?? '').trim()

  if (lead !== '') out.push({ label: '', text: lead })

  for (let i = 1; i + 1 < cut.length; i += 2) {
    out.push({ label: cut[i] ?? '', text: (cut[i + 1] ?? '').trim() })
  }

  return out
}

/** How wide the names of a level's parts are set, so what they say starts in one column. The app's letters are narrower than a terminal's cells. */
const LABEL_COLUMNS = { picture: 11, terminal: 14 }

/** The first sentence of a part of a story: what is told before the person asks for all of it. */
const lead = (text: string): string => /^.*?[.!?](?=\s|$)/.exec(text)?.[0] ?? text

/**
 * A node's digest as it is read: what it has now, where that departs from its story, what was turned back, and
 * what runs came to, for and against. Only the parts that hold something.
 */
function digestOf(node: AbsNode): [string, Point[]][] {
  const kept = node.digest
  const marked = (mark: string, point: string, lines: string[] | undefined): Point[] =>
    (lines ?? []).map(text => ({ mark, point, text }))
  const parts: [string, Point[]][] = [
    ['Has now', marked('∙', 'has now', kept?.features)],
    // Where what is built departs from the story above it, and why: said, not left as a contradiction.
    ['As built', marked('≠', 'as built', kept?.as_built)],
    ['Turned back', marked('↩', 'turned back', kept?.reverts)],
    ['Results', [...marked('+', 'result for', kept?.positive), ...marked('−', 'result against', kept?.negative)]],
  ]

  return parts.filter(([, lines]) => lines.length > 0)
}

/** One point of the spec as the person reads it: its mark, which point it is, and its text. */
type Point = { mark: string; point: string; text: string }

/** Words laid out in lines of at most `width` characters, broken between words. */
function lineUp(text: string, width: number): string[] {
  const out: string[] = []
  let line = ''

  for (const word of text.split(/\s+/).filter(w => w !== '')) {
    if (line !== '' && line.length + 1 + word.length > width) {
      out.push(line)
      line = word
    } else {
      line = line === '' ? word : `${line} ${word}`
    }
  }

  return line === '' ? out : [...out, line]
}

/**
 * Puts a point of the spec in the prompt box as a quote: which node, which point,
 * and its whole text, on a line of its own. The box holds one such quote: a press
 * replaces the one an earlier press put there, where it stood, and what the person
 * typed around it stays. A quote they edited is theirs and is left alone. With none,
 * the quote goes after what they typed. Nothing is sent or recorded.
 */
async function citeInPrompt($: EngineInterface, node: AbsNode, point: string, text: string): Promise<void> {
  const quote = `> ${node.title} · ${point}: ${text.replace(/\s+/g, ' ').trim()}`
  const box = await $.prompt.read().catch(() => ({ text: '', cursor: 0 }))
  const earlier = await read($, quoted).catch(() => null)
  const lines = box.text === '' ? [] : box.text.split('\n')
  const at = earlier === null ? -1 : lines.indexOf(earlier)
  let draft: string[]
  let line: number

  if (at >= 0) {
    draft = [...lines.slice(0, at), quote, ...lines.slice(at + 1)]
    line = at
  } else {
    // After what was typed, on a line of its own; a box ending in a newline already has one.
    const kept = lines.length > 0 && lines[lines.length - 1] === '' ? lines.slice(0, -1) : lines

    draft = [...kept, quote, '']
    line = kept.length
  }

  const text2 = draft.join('\n')
  // The caret on the line after the quote, where the person goes on.
  const cursor = draft.slice(0, line + 1).join('\n').length + 1

  await update($, quoted, () => quote)
  await $.prompt.fill({ text: text2, mode: 'replace', cursor: Math.min(cursor, text2.length) })
}

/** Whose component a component is: the node it serves, or all the designs when it sits under the core. */
function whose(data: AbsSnapshot, node: AbsNode): string {
  const above = data.nodes.find(n => n.id === node.parent)

  return above !== undefined && above.kind !== 'core'
    ? `Component of "${above.title}"`
    : 'Component, shared by the designs'
}

/** A task's budget in one figure: the metric it is furthest into, such as "8/4 trials". */
function furthest(t: AbsTask): string {
  const spent = METRICS.filter(m => (t.budget[m] ?? 0) > 0).sort(
    (a, b) => (t.actual[b] ?? 0) / (t.budget[b] ?? 1) - (t.actual[a] ?? 0) / (t.budget[a] ?? 1),
  )[0]

  return spent === undefined
    ? 'no budget'
    : `${num(t.actual[spent] ?? 0)}/${num(t.budget[spent] ?? 0)} ${UNIT[spent]}`
}

/** The designs in reading order, each with how deep it sits under the core. */
function ordered(nodes: AbsNode[]): { node: AbsNode; depth: number }[] {
  const ids = new Set(nodes.map(n => n.id))
  const out: { node: AbsNode; depth: number }[] = []
  const seen = new Set<string>()
  const walk = (node: AbsNode, depth: number): void => {
    if (seen.has(node.id)) return
    seen.add(node.id)
    out.push({ node, depth })
    for (const child of nodes) {
      if (child.parent === node.id) walk(child, depth + 1)
    }
  }

  for (const node of nodes) {
    if (node.parent === null || !ids.has(node.parent)) walk(node, 0)
  }

  return out
}

/** The design to show when the person has picked none: the one that needs them. */
function needsAttention(data: AbsSnapshot): AbsNode | undefined {
  const blocked = data.tasks.find(t => t.status === 'blocked')
  // A design is flagged along with the component under it that has the
  // trouble: the one to look at is the deepest.
  const deepFirst = ordered(data.nodes)
    .sort((a, b) => b.depth - a.depth)
    .map(x => x.node)

  return (
    data.nodes.find(n => n.id === blocked?.parent) ??
    deepFirst.find(n => n.health.level === 'step_back') ??
    deepFirst.find(n => n.health.level === 'watch') ??
    // Nothing is in trouble: show the design that has work ready to hand over.
    data.nodes.find(n => data.tasks.some(t => t.parent === n.id && t.status === 'planned')) ??
    data.nodes[0]
  )
}

// A decision is the person's to make and to word, so a button only starts the
// sentence in the prompt box. They finish it and send it; Claude records it.
function extendDraft(t: AbsTask): string {
  const more = METRICS.filter(m => (t.budget[m] ?? 0) > 0).map(
    m => `${Math.max(1, Math.ceil((t.budget[m] ?? 0) / 2))} ${UNIT[m]}`,
  )

  return `Extend ${t.id} by ${more.join(', ')}. `
}

const stepBackDraft = (t: AbsTask, design: string): string =>
  `Step back from ${t.id}. What the design "${design}" missed: `

const banDraft = (t: AbsTask): string =>
  `Ban the approach of ${t.id} ("${t.title}"). Reason: `

// Handing a planned task over is the person's call as well. With no budget
// planned, the sentence stops where they name one.
function delegateDraft(t: AbsTask): string {
  const planned = METRICS.filter(m => (t.budget[m] ?? 0) > 0).map(
    m => `${num(t.budget[m] ?? 0)} ${UNIT[m]}`,
  )
  const task = `${t.id} ("${t.title}")`

  return planned.length > 0
    ? `Hand ${task} to a subagent with its planned budget (${planned.join(', ')}). `
    : `Hand ${task} to a subagent. Budget: `
}

/** The same graph as plain text, for where no pane can be drawn. */
function asText(data: AbsSnapshot): string {
  const lines = ordered(data.nodes).map(({ node, depth }) => {
    const marks = data.tasks
      .filter(t => t.parent === node.id)
      .map(t => MARK[t.status] ?? '?')
      .join('')

    // As in the picture it stands in for: a node says how it stands only when its work flags it.
    const tone = healthOf(node).tone
    const word = tone === 'warning' || tone === 'error' ? healthOf(node).word : ''

    return `${'  '.repeat(depth)}${node.title}${partMark(node)}  ${word}  ${marks}`.trimEnd()
  })
  const open = data.tasks
    .filter(isOpen)
    .map(t => `${MARK[t.status] ?? '?'} ${t.title}  ${usage(t)}`)
  const sessions = (data.sessions ?? []).map(
    s => `${sessionLine(data, s)} · ${sessionDetail(data, s)}`,
  )

  return [
    ...lines,
    ...(open.length > 0 ? ['', ...open] : []),
    ...(sessions.length > 0 ? ['', ...sessions] : []),
  ].join('\n')
}

// ---- the graph, where the surface draws vectors ---------------------------
//
// Layers, top to bottom: the core abstraction; the designs under it, which are
// the decisions; under each design the components that carry it out, a step
// in; and under each node its tasks. Components the designs share sit in a row
// of their own, under the designs. A component's box is dashed: it is built,
// it is not a decision. The drawing is an image, so every color is in the
// markup: dark as written, light where the surface says it is light.

const xml = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

/** `text` cut to what fits in `px` at about `per` pixels a character. */
function fit(text: string, px: number, per: number): string {
  const max = Math.max(4, Math.floor(px / per))

  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text
}

/**
 * `text` on one line if it fits in `px`, else broken at a space into two. The
 * second line has `px2` to itself and is cut where it has to be.
 */
function wrap(text: string, px: number, per: number, px2: number): string[] {
  const max = Math.max(4, Math.floor(px / per))
  const at = text.lastIndexOf(' ', max)

  if (text.length <= max || at <= 0) return [fit(text, px, per)]

  return [text.slice(0, at), fit(text.slice(at + 1), px2, per)]
}

// A task's mark: its fill, and a small drawing in a 12-pixel box.
type Chip = { fill: string; icon: string }
const OTHER_CHIP: Chip = { fill: '#8f8e86', icon: '<path d="M3.5 6h5"/>' }
const CHIP: Record<string, Chip> = {
  done: { fill: '#0ca30c', icon: '<path d="M3 6.4l2.1 2.1L9 4"/>' },
  banned: { fill: '#d03b3b', icon: '<path d="M3.5 3.5l5 5M8.5 3.5l-5 5"/>' },
  stepped_back: { fill: '#ec835a', icon: '<path d="M9 9V7.2a2 2 0 0 0-2-2H3.4M5.4 3.2l-2 2 2 2"/>' },
  active: { fill: '#2a78d6', icon: '<circle cx="6" cy="6" r="2" fill="#fff" stroke="none"/>' },
  blocked: { fill: '#fab219', icon: '<path d="M4.4 3.4v5.2M7.6 3.4v5.2"/>' },
  planned: { fill: 'none', icon: '<circle cx="6" cy="6" r="2.4"/>' },
}

const LIGHT =
  '@media (prefers-color-scheme: light){' +
  '.cd{fill:#fcfcfb;stroke:#c3c2b7}.co{fill:#f0efea}.ln{stroke:#c3c2b7}' +
  '.tt{fill:#0b0b0b}.sb{fill:#7a7973}.good{fill:#0a8a0a}.warn{fill:#a36a00}.crit{fill:#d03b3b}' +
  '.fw{stroke:#e0a000}.fc{stroke:#d03b3b}.sel{stroke:#2a78d6}' +
  '.pl rect{stroke:#b9b8ae}.pl text{fill:#52514e}.pl .ic{stroke:#7a7973}' +
  '.fn rect{stroke:#c9c8be}.fn text{fill:#3b3a37}}'

/** The whole graph as one SVG document, `columns` text cells wide. */
function graphSvg(
  data: AbsSnapshot,
  currentId: string | undefined,
  columns: number,
  zoomId?: string,
): string {
  const all = ordered(data.nodes)
  const core = all[0]?.node

  if (core === undefined) return ''

  // The node at the top of the picture: the core for the whole tree, or the
  // node zoomed into, drawn with everything under it and all of its work.
  const root = data.nodes.find(x => x.id === zoomId && x.id !== core.id) ?? core
  const isZoomed = root.id !== core.id

  const W = Math.max(280, Math.min(760, Math.round(columns * 7)))
  const PAD = 6
  const RAIL = 14 // the gutter the trunk runs down, from the core to each row under it
  const GAP = 8
  const STEP = 14 // how far a node sits in from the node it is under
  const CORE_H = 44
  const CARD_H = 42
  const PART_H = 38
  const ROW_H = 31 // a task: its name over its facts
  const ids = new Set(data.nodes.map(x => x.id))
  // What sits right under the core: the designs, and the components the designs share.
  const top = data.nodes.filter(
    x => x.id !== core.id && (x.parent === core.id || x.parent === null || !ids.has(x.parent)),
  )
  const left = PAD + RAIL
  const n = (v: number): string => String(Math.round(v * 10) / 10)
  const lines: string[] = []
  const body: string[] = []

  /** How a node's box and its state word are colored: by how the work under it goes, and whether it is picked. */
  const lookOf = (node: AbsNode) => {
    const state = healthOf(node)
    const isPart = node.kind === 'component'
    const isPicked = node.id === currentId
    const cls = state.tone === 'success' ? 'good' : state.tone === 'warning' ? 'warn' : state.tone === 'error' ? 'crit' : ''

    return {
      isPart,
      isPicked,
      cls,
      ink: cls === 'good' ? '#4cc24c' : cls === 'warn' ? '#fab219' : cls === 'crit' ? '#ef6a6a' : '',
      flag: cls === 'warn' ? ' fw' : cls === 'crit' ? ' fc' : '',
      stroke: isPicked ? '#5b9bea' : cls === 'warn' ? '#fab219' : cls === 'crit' ? '#ef6a6a' : isPart ? '#6a6961' : '#4d4c45',
      // A node on track says nothing: only one its work flags has a word.
      word: cls === 'warn' || cls === 'crit' ? `${state.glyph} ${state.word}` : '',
    }
  }

  /**
   * Draws the node zoomed into, across the top: its name, what kind of node it
   * is and how its work goes, and its summary. Answers how tall it came out.
   */
  const head = (node: AbsNode): number => {
    const { isPart, isPicked, cls, ink, flag, stroke, word } = lookOf(node)
    const w = W - 2 * PAD
    const above = data.nodes.find(x => x.id === node.parent)
    const kind = !isPart ? 'design' : above !== undefined && above.kind !== 'core' ? `component of “${above.title}”` : 'component shared by the designs'
    const name = wrap(node.title, w - 20, 7.5, w - 20)
    const kindY = PAD + 6 + name.length * 16 + 12
    const h = kindY - PAD + 10 // its story is told in words under the graph, not in the box

    body.push(
      `<rect class="cd co hd${flag}${isPicked ? ' sel' : ''}" x="${n(PAD)}" y="${n(PAD)}" width="${n(w)}" height="${n(h)}" rx="7" fill="#2a2a27" stroke="${stroke}" stroke-width="${isPicked ? 1.8 : 1}"${isPart ? ' stroke-dasharray="4 3"' : ''}/>`,
      ...name.map(
        (row, i) =>
          `<text class="tt" x="${n(PAD + 10)}" y="${n(PAD + 19 + i * 16)}" font-size="13.5" font-weight="600" fill="#f0efec">${xml(row)}</text>`,
      ),
      `<text class="sb" x="${n(PAD + 10)}" y="${n(kindY)}" font-size="10.5" fill="#a09f97">${xml(fit(kind, w - (word === '' ? 20 : 110), 5.4))}${word === '' ? '' : ` · <tspan class="${cls}" fill="${ink}">${xml(word)}</tspan>`}</text>`,
    )

    return h
  }

  /** Draws a node's box and answers how tall it came out: a long name takes a second line. */
  const card = (node: AbsNode, x: number, y: number, w: number, isCore: boolean): number => {
    const { isPart, isPicked, cls, ink, flag, stroke, word } = lookOf(node)
    const size = isPart ? 11.5 : 12.5
    const name = isCore ? [fit(node.title, w - 20, 6.9)] : wrap(node.title, w - 20, size * 0.56, w - 18)
    // What stands under the name: that this is the core, and a word only when its work flags it. Else the box is its name.
    const said = [isCore ? 'core' : '', word === '' ? '' : `<tspan class="${cls}" fill="${ink}">${xml(word)}</tspan>`]
      .filter(s => s !== '')
      .join(' · ')
    const h = (isCore ? CORE_H : (isPart ? PART_H : CARD_H) - (said === '' ? 12 : 0)) + (name.length - 1) * 14
    const base = y + (isPart ? 16 : 17.5)

    body.push(
      `<rect class="cd${isCore ? ' co' : ''}${isPart ? ' cmp' : ''}${flag}${isPicked ? ' sel' : ''}" x="${n(x)}" y="${n(y)}" width="${n(w)}" height="${n(h)}" rx="7" fill="${isCore ? '#2a2a27' : '#1f1f1d'}" stroke="${stroke}" stroke-width="${isPicked ? 1.8 : 1}"${isPart ? ' stroke-dasharray="4 3"' : ''}/>`,
      ...name.map(
        (row, i) =>
          `<text class="tt" x="${n(x + 10)}" y="${n(base + i * 14)}" font-size="${size}" font-weight="600" fill="#f0efec">${xml(row)}</text>`,
      ),
      ...(said === ''
        ? []
        : [`<text class="sb" x="${n(x + 10)}" y="${n(y + h - 9)}" font-size="10.5" fill="#a09f97">${said}</text>`]),
    )

    return h
  }

  // Work is drawn to be read with no key. An open task is a row: its name,
  // and under it its id, who is on it and how far into the budget. Finished
  // tasks are neither listed nor counted: what they came to is in the node's digest.

  /** The open tasks under a node: what waits for the person, what is being worked on, what is planned. */
  const openUnder = (id: string): AbsTask[] =>
    data.tasks
      .filter(t => t.parent === id && SHOWN_FIRST[t.status] !== undefined)
      .sort((a, b) => (SHOWN_FIRST[a.status] ?? 9) - (SHOWN_FIRST[b.status] ?? 9))

  const taskRow = (t: AbsTask, x: number, y: number, w: number): void => {
    const look = CHIP[t.status] ?? OTHER_CHIP
    const isPlanned = t.status === 'planned'
    // A finished task, listed when zoomed in, is drawn quiet: an outline, and its outcome in the mark's color.
    const isOver = SHOWN_FIRST[t.status] === undefined
    const ink = isOver ? '#d8d7d0' : isPlanned ? '#c3c2b7' : t.status === 'blocked' ? '#1a1a19' : '#ffffff'
    const by = tagOf(data, t)
    // Who, then how far in, then the id: what a reader wants comes first, and
    // where the row is narrow the last of them is left out whole.
    const facts = [...(by === '' ? [] : [by]), isPlanned ? 'planned' : furthest(t)]

    while (facts.length > 1 && facts.join(' · ').length > Math.floor((w - 25) / 5)) facts.pop()

    body.push(
      `<g class="ch${isPlanned ? ' pl' : isOver ? ' fn' : ''}" transform="translate(${n(x)} ${n(y)})">` +
        `<rect width="${n(w)}" height="${ROW_H}" rx="5" fill="${isOver ? 'none' : look.fill}"${isPlanned ? ' stroke="#77766e"' : isOver ? ' stroke="#55544d"' : ''}/>` +
        `<g class="ic" transform="translate(4 4)" fill="none" stroke="${isOver ? look.fill : ink}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${look.icon}</g>` +
        `<text class="nm" x="19" y="13" font-size="10.5" font-weight="600" fill="${ink}">${xml(fit(t.title, w - 25, 5.7))}</text>` +
        `<text class="by" x="19" y="25.5" font-size="9.5" fill="${ink}" fill-opacity="0.82">${xml(fit(facts.join(' · '), w - 25, 5))}</text>` +
        '</g>',
    )
  }

  const railX = PAD + RAIL / 2
  let y = PAD
  let railEnd = y

  /**
   * Draws what hangs under a node's box: its tasks, then the nodes under it,
   * each a step in with its own tasks and nodes under it in turn. Answers
   * where the drawing ends.
   */
  const under = (node: AbsNode, x: number, w: number, boxTop: number, boxH: number): number => {
    const trunk = x + 8
    const open = openUnder(node.id)
    let bottom = boxTop + boxH
    let reach = bottom // how far down the trunk has to run
    let cy = bottom + 7

    const listed = (t: AbsTask): void => {
      reach = cy + ROW_H / 2
      lines.push(`M${n(trunk)} ${n(reach)}H${n(x + 16)}`)
      taskRow(t, x + 16, cy, w - 16)
      bottom = cy + ROW_H
      cy = bottom + 4
    }

    const quietLine = (text: string): void => {
      reach = cy + 6
      lines.push(`M${n(trunk)} ${n(reach)}H${n(x + 14)}`)
      body.push(
        `<text class="sb fin" x="${n(x + 17)}" y="${n(cy + 9.5)}" font-size="10" fill="#a09f97">${text}</text>`,
      )
      bottom = cy + 13
      cy = bottom + 4
    }

    // Open work is named. Finished work is not drawn at all: what it came to is in the node's digest.
    open.slice(0, NAMED).forEach(listed)

    // One quiet line for the open tasks that did not fit.
    if (open.length > NAMED) quietLine(`+${open.length - NAMED} more open`)

    // A view goes one level down and no further. The node zoomed into has the
    // nodes under it drawn; any other node only says how many it has, and a
    // press on its name is how they are seen.
    const kids = data.nodes.filter(c => c.parent === node.id)

    if (isZoomed && node.id === root.id) {
      for (const child of kids) {
        const childTop = bottom + 8
        const childH = card(child, x + STEP, childTop, w - STEP, false)

        reach = childTop + childH / 2
        lines.push(`M${n(trunk)} ${n(reach)}H${n(x + STEP)}`)
        bottom = under(child, x + STEP, w - STEP, childTop, childH)
      }
    } else if (kids.length > 0) {
      // What is not drawn still says where the work is going on below this node, and where it
      // waits for the person. How many nodes are there is not said: it asks nothing of anyone.
      const below = new Set<string>()
      const gather = (id: string): void => {
        for (const c of data.nodes) {
          if (c.parent === id && !below.has(c.id)) {
            below.add(c.id)
            gather(c.id)
          }
        }
      }

      gather(node.id)

      const count = (status: string): number =>
        data.tasks.filter(t => below.has(t.parent) && t.status === status).length

      // Kept short: a line under a box has the box's width and no more.
      const held = [
        count('blocked') > 0 ? `${count('blocked')} waiting for you` : '',
        count('active') > 0 ? `${count('active')} in progress` : '',
      ]
        .filter(s => s !== '')
        .join(' · ')

      if (held !== '') quietLine(fit(held, w - 16, 4.8))
    }

    if (reach > boxTop + boxH) lines.push(`M${n(trunk)} ${n(boxTop + boxH)}V${n(reach)}`)

    return bottom
  }

  /** Draws nodes that sit right under the core, a row at a time, each with all that is under it. */
  const rows = (nodes: AbsNode[], from: number): number => {
    const cols = Math.max(1, Math.min(nodes.length, Math.floor((W - left - PAD + GAP) / (128 + GAP))))
    const cw = (W - left - PAD - (cols - 1) * GAP) / cols
    let at = from

    for (let r = 0; r * cols < nodes.length; r += 1) {
      const row = nodes.slice(r * cols, (r + 1) * cols)
      const busY = at + 9
      const boxTop = at + 18
      let bottom = boxTop

      row.forEach((node, c) => {
        const x = left + c * (cw + GAP)

        lines.push(`M${n(x + cw / 2)} ${n(busY)}V${n(boxTop)}`)
        bottom = Math.max(bottom, under(node, x, cw, boxTop, card(node, x, boxTop, cw, false)))
      })

      lines.push(`M${n(railX)} ${n(busY)}H${n(left + (row.length - 1) * (cw + GAP) + cw / 2)}`)
      railEnd = busY
      at = bottom
    }

    return at
  }

  if (isZoomed) {
    // One node, across the top, and under it all it holds: its own work, then
    // each node under it, a step in, with all of that node's work.
    y = under(root, PAD, W - 2 * PAD, PAD, head(root))
  } else {
    // Layer 1: the core abstraction, across the top.
    card(core, PAD, PAD, W - 2 * PAD, true)

    // Open work on the core itself is said inside its box.
    const onCore = openUnder(core.id).length > 0 ? `${openUnder(core.id).length} open` : ''

    if (onCore !== '') {
      body.push(
        `<text class="sb" x="${n(W - PAD - 10)}" y="${n(PAD + CORE_H - 9)}" text-anchor="end" font-size="10.5" fill="#a09f97">${onCore}</text>`,
      )
    }

    y = PAD + CORE_H
    railEnd = y

    // Layer 2: the designs. Under each: its components, and under every node its tasks.
    const designs = top.filter(x => x.kind !== 'component')
    const shared = top.filter(x => x.kind === 'component')

    y = rows(designs, y)

    // The components the designs share: a row of their own, named for what it holds.
    if (shared.length > 0) {
      if (designs.length > 0) {
        body.push(
          `<text class="sb" x="${n(left)}" y="${n(y + 15)}" font-size="10" fill="#a09f97">components shared by the designs</text>`,
        )
        y += 10
      }

      y = rows(shared, y)
    }

    if (top.length > 0) lines.push(`M${n(railX)} ${n(PAD + CORE_H)}V${n(railEnd)}`)
  }

  const H = n(y + PAD)

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif">` +
    `<style>${LIGHT}</style>` +
    `<path class="ln" d="${lines.join('')}" fill="none" stroke="#5a5952" stroke-width="1.2"/>` +
    body.join('') +
    '</svg>'
  )
}

let hasRepo = false

// How often the state is read again with no tool call of this session's to prompt it.
const WATCH_MS = 15_000

// Tools whose calls can move a budget: edits, check runs, and thinspec's own.
const MOVES_BUDGET = /^(Edit|Write|MultiEdit|NotebookEdit|Bash|mcp__.*thinspec.*)$/

/**
 * Reads the repo's state through the thinspec command. Never rejects.
 *
 * A read that fails says nothing about the repo: a timeout, or a file caught
 * halfway through a rename. So what was read before stays in view, with the
 * reason, and the next trigger reads again. Only thinspec's own answer that
 * there is no repo here empties the view. Resolves what is in view after it.
 */
async function refresh($: EngineInterface): Promise<AbsSnapshot | null> {
  let data: AbsSnapshot | null = null
  let why = ''

  try {
    // Naming this session lets the state mark it among the sessions at work.
    const me = await $.session.id().catch(() => undefined)
    const ask = ['thinspec', 'state', '--json']
    let ran = await $.process.run(me ? [...ask, '--session', me] : ask, {
      timeoutMs: 5_000,
    })

    // A thinspec command from before the sessions refuses the flag (exit 2).
    if (me && ran.exitCode === 2) ran = await $.process.run(ask, { timeoutMs: 5_000 })

    if (ran.exitCode === 0) {
      const parsed: unknown = JSON.parse(ran.stdout)
      const looksRight =
        typeof parsed === 'object' &&
        parsed !== null &&
        Array.isArray((parsed as AbsSnapshot).nodes) &&
        Array.isArray((parsed as AbsSnapshot).tasks)

      data = looksRight ? (parsed as AbsSnapshot) : null
      why = looksRight ? '' : 'thinspec printed something other than the state'
    } else {
      // The last line of what it wrote: its own message, or the error under a traceback.
      const said = String(ran.stderr ?? '').trim().split('\n').pop() ?? ''

      why = `thinspec exited with ${ran.exitCode}${said === '' ? '' : `: ${said.slice(0, 200)}`}`
    }
  } catch (err) {
    why = `the thinspec command could not be run or read (${String(err).slice(0, 160)})`
  }

  const isGone = /No ThinSpec repo/.test(why)

  try {
    if (data !== null) {
      hasRepo = true
      await update($, snapshot, () => data)
    } else if (isGone || !hasRepo) {
      hasRepo = false
      await update($, snapshot, () => null)
    } else {
      data = await read($, snapshot) // what was read before stays
    }

    // Why the view is empty or not fresh; nothing to say where there is no repo at all.
    await update($, problem, () => (why === '' || isGone ? null : why))
  } catch {
    // the session is ending; there is nobody left to draw for
  }

  return data
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // The person's one command, named after the thing it shows.
    await $.command.register({
      name: 'thinspec',
      description: 'Open the ThinSpec graph: the design, the work under it, and who is on what',
      immediate: true,
    })
    await refresh($)

    // Other sessions move the picture while this one sits idle, so look again
    // now and then. A reload of the module cancels the timer along with it.
    try {
      $.clock.every(WATCH_MS, () => {
        if (hasRepo) void refresh($)
      })
    } catch {
      // no timers here: the view still follows this session's own work
    }

    return next(e)
  })

  on('command.run', { command: 'thinspec' }, async $ => {
    const data = await refresh($)

    if (data === null) {
      const trouble = await read($, problem)

      return {
        text:
          trouble === null
            ? 'ThinSpec: nothing to show here. Run `thinspec init` at the root of the project (the thinspec command has to be on your PATH).'
            : `ThinSpec could not read this project's state: ${trouble}. Run /thinspec to read it again.`,
      }
    }

    const opened = await $.ui.open({ id: PANE, title: TITLE })

    return { text: opened.isPlaced ? 'ThinSpec pane opened.' : asText(data) }
  })

  // Budgets move with every edit and check run, so the view follows those
  // calls. This hook only watches: if it fails, the tool call goes on.
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)

    if (hasRepo && MOVES_BUDGET.test(String(e.tool))) await refresh($)

    return ran
  })

  // The settings hooks write the turn's time when it ends; read it then.
  on('turn.complete', async ($, e, next) => {
    const ended = await next(e)

    if (hasRepo) await refresh($)

    return ended
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const table = $.ui.resolve(e)
    // Boxes, text and buttons only: what every surface has, and what takes a press.
    const { Box, Button, Text } = table
    const data = await read($, snapshot)
    const trouble = await read($, problem)

    if (data === null) {
      // No repo here, or a first read that failed: say which, so the reader is not sent to init for nothing.
      return trouble === null ? (
        <Box flexDirection="column">
          <Text dimColor>No abstraction found in this project.</Text>
          <Text dimColor>Run thinspec init at its root.</Text>
        </Box>
      ) : (
        <Box flexDirection="column">
          <Text color="warning" wrap="wrap">
            ThinSpec could not read this project's state: {trouble}.
          </Text>
          <Text dimColor>Run /thinspec to read it again.</Text>
        </Box>
      )
    }

    const picked = await read($, selected)
    const root = ordered(data.nodes)[0]?.node
    // The node zoomed into, when one was picked. With none, the whole tree is
    // drawn and the text under it is about the node that needs a look.
    const focus = data.nodes.find(n => n.id === picked && n.id !== root?.id)
    const current = focus ?? needsAttention(data)
    // The level whose story is told: the node zoomed into, or the core for the whole tree.
    const shown = focus ?? root
    // From the core down to the node zoomed into: the way back out.
    const path: AbsNode[] = []

    for (let at = focus; at !== undefined && !path.includes(at); ) {
      path.unshift(at)
      at = data.nodes.find(n => n.id === at?.parent)
    }

    // What a press can zoom into from here: the nodes right under the one in view.
    const within = data.nodes.filter(n =>
      focus === undefined
        ? n.id !== root?.id && (n.parent === root?.id || !data.nodes.some(p => p.id === n.parent))
        : n.parent === focus.id,
    )
    const waiting = data.tasks.filter(t => t.status === 'blocked')
    const sessions = data.sessions ?? []

    // A minimized pane on the desktop app: what reads at a glance.
    if (e.props.placement === 'widget') {
      return (
        <Box flexDirection="column">
          <Text>
            {data.nodes.filter(n => n.kind === 'design').length} designs ·{' '}
            {data.tasks.filter(isOpen).length} open
            {sessions.length > 1 ? ` · ${sessions.length} sessions` : ''}
          </Text>
          {waiting.length > 0 && (
            <Text color="warning">{waiting.length} waiting for your call</Text>
          )}
        </Box>
      )
    }

    // The node that needs the person, when one does: a task far past its
    // estimate sits under it, or the work under it flags it. No other node is
    // pointed at.
    const needs =
      current !== undefined &&
      (waiting.some(t => t.parent === current.id) ||
        healthOf(current).tone === 'warning' ||
        healthOf(current).tone === 'error')
        ? current
        : undefined
    // The tree is one picture where the surface draws one: it is the clean way
    // to show what is under what. A picture takes no press, so the names under
    // it do. A terminal draws no vectors: there the tree is boxes joined by
    // line glyphs, and a name in its box is the button.
    const Svg = e.surface !== 'terminal' && 'Svg' in table ? table.Svg : undefined

    // A box is edged in the tone of its node's trouble, when it has one.
    const flagOf = (node: AbsNode): Tone | undefined => {
      const tone = healthOf(node).tone

      return tone === 'success' ? undefined : tone
    }
    // How a node stands, said only when its work flags it: a node on track says nothing.
    const stateOf = (node: AbsNode): string =>
      flagOf(node) === undefined ? '' : `${healthOf(node).glyph} ${healthOf(node).word}`
    const openOf = (id: string): AbsTask[] =>
      data.tasks
        .filter(t => t.parent === id && SHOWN_FIRST[t.status] !== undefined)
        .sort((a, b) => (SHOWN_FIRST[a.status] ?? 9) - (SHOWN_FIRST[b.status] ?? 9))
    // What is one level further down is not drawn, but it still says where work
    // is going on under a node and where it waits for the person. Nothing else
    // is counted: not finished work, not the nodes under it.
    const belowOf = (node: AbsNode): string => {
      const under = new Set<string>()
      const gather = (id: string): void => {
        for (const c of data.nodes) {
          if (c.parent === id && !under.has(c.id)) {
            under.add(c.id)
            gather(c.id)
          }
        }
      }

      gather(node.id)

      const count = (status: string): number =>
        data.tasks.filter(t => under.has(t.parent) && t.status === status).length

      return [
        count('blocked') > 0 ? `${count('blocked')} waiting for you` : '',
        count('active') > 0 ? `${count('active')} in progress` : '',
      ]
        .filter(s => s !== '')
        .join(' · ')
    }
    // Who is on a task, then how far in. Its id is a handle for the record and is not shown.
    const factsOf = (t: AbsTask): string =>
      [tagOf(data, t), t.status === 'planned' ? 'planned' : furthest(t)]
        .filter(s => s !== '')
        .join(' · ')

    // ---- the tree in a terminal: boxes, joined by line glyphs ----------------

    const INK = 'inactive'
    // How many boxes sit side by side under the node in view, and how wide each is.
    const across = Math.max(1, Math.min(3, Math.floor((e.props.bodyColumns - 3) / 34)))
    const span = Math.max(12, Math.floor((e.props.bodyColumns - 3) / across))

    /**
     * The rail beside one thing that hangs from it, two columns wide: down to
     * the thing, across to it, and on past it when more hangs below. A bare rail
     * only passes. `rows` is how tall the thing is, `at` the row the rail meets it at.
     */
    const joint = (hung: { rows: number; at: number; hasMore: boolean; isBare?: boolean }) => (
      <Box width={2} flexShrink={0}>
        <Text dimColor>
          {Array.from({ length: hung.rows }, (_, i) =>
            i === hung.at && hung.isBare !== true
              ? hung.hasMore
                ? '├─'
                : '└─'
              : i < hung.at || hung.hasMore
                ? '│'
                : ' ',
          ).join('\n')}
        </Text>
      </Box>
    )

    /** Over one box of a row: the branch, running on to the boxes after it, and the drop into this box. */
    const drop = (isLast: boolean) => (
      <Text dimColor wrap="truncate-end">
        {isLast ? '─┐' : `─┬${'─'.repeat(span - 2)}`}
      </Text>
    )

    /** An open task, hanging under its node in a box of its own: its name, then who is on it, how far in, and its id. */
    const chip = (t: AbsTask) => (
      <Box
        borderStyle="single"
        borderColor={t.status === 'blocked' ? 'warning' : INK}
        borderDimColor={t.status === 'planned'}
        paddingX={1}
        flexDirection="column"
      >
        <Text color={t.status === 'blocked' ? 'warning' : undefined} wrap="truncate-end">
          {MARK[t.status] ?? '?'} {t.title}
        </Text>
        <Text dimColor wrap="truncate-end">
          {factsOf(t)}
        </Text>
      </Box>
    )

    // One box of a layer with what hangs under it, and how many rows it is drawn in.
    type Tile = { rows: number; body: RenderElement }

    /**
     * One node of the level under the one in view: a box whose name is the
     * button that zooms into it, and on a rail from its foot what hangs from
     * it: its open work, each task in a box, then what is only counted.
     */
    const tile = (node: AbsNode): Tile => {
      const open = openOf(node.id)
      const counted = [
        open.length > NAMED ? `+${open.length - NAMED} more open` : '',
        belowOf(node),
      ].filter(s => s !== '')
      const hung = [
        ...open.slice(0, NAMED).map(t => ({ rows: 4, at: 1, body: chip(t) })),
        ...counted.map(line => ({
          rows: 1,
          at: 0,
          body: (
            <Text dimColor wrap="truncate-end">
              {line}
            </Text>
          ),
        })),
      ]

      return {
        rows: (stateOf(node) === '' ? 3 : 4) + hung.reduce((sum, item) => sum + item.rows, 0),
        body: (
          <Box flexDirection="column">
            <Box
              borderStyle={node.kind === 'component' ? 'dashed' : 'round'}
              borderColor={flagOf(node) ?? INK}
              borderDimColor={flagOf(node) === undefined}
              paddingX={1}
              flexDirection="column"
            >
              <Button plain key={`design-${node.id}`} onPress={() => update($, selected, () => node.id)}>
                {node.title}
              </Button>
              {stateOf(node) !== '' && (
                <Text color={flagOf(node)} wrap="truncate-end">
                  {stateOf(node)}
                </Text>
              )}
            </Box>
            {hung.length > 0 && (
              <Box flexDirection="column" paddingLeft={2}>
                {/* `h` is what JSX compiles to here: nothing in a drawing may take that name. */}
                {hung.map((item, i) => (
                  <Box flexDirection="row">
                    {joint({ ...item, hasMore: i < hung.length - 1 })}
                    <Box flexDirection="column" flexGrow={1} minWidth={0} paddingLeft={item.rows === 1 ? 1 : 0}>
                      {item.body}
                    </Box>
                  </Box>
                ))}
              </Box>
            )}
          </Box>
        ),
      }
    }

    /**
     * One layer under the node in view: its boxes side by side on a branch off
     * the spine, with a new branch for each row of them. The spine runs on past
     * a row when more is drawn below it.
     */
    const layer = (tiles: Tile[], hasMoreBelow: boolean) => {
      const rows: Tile[][] = []

      for (let i = 0; i < tiles.length; i += across) rows.push(tiles.slice(i, i + across))

      return rows.map((row, r) => (
        <Box flexDirection="row">
          {joint({
            rows: Math.max(...row.map(t => t.rows)) + 2,
            at: 0,
            hasMore: hasMoreBelow || r < rows.length - 1,
          })}
          <Box flexDirection="row" flexGrow={1} minWidth={0}>
            {row.map((t, i) => (
              <Box flexDirection="column" width={span} minWidth={0} paddingBottom={1}>
                {drop(i === row.length - 1)}
                <Box flexDirection="column" paddingRight={i === row.length - 1 ? 0 : 1}>
                  {t.body}
                </Box>
              </Box>
            ))}
          </Box>
        </Box>
      ))
    }

    // What sits under the node in view, in the order it is told: its designs, then its components.
    const designsUnder = within.filter(n => n.kind !== 'component')
    const partsUnder = within.filter(n => n.kind === 'component')
    const partsAre =
      shown?.kind === 'design' ? 'Carried out by' : focus === undefined ? 'Shared components' : 'Parts'
    const layers = [designsUnder, partsUnder].filter(nodes => nodes.length > 0)

    /**
     * A task the person can act on, kept short: its name, how far into the
     * budget it is, and the buttons. A planned one is a single line with the
     * button that hands it over. No check text: that is in the record.
     */
    const act = (t: AbsTask, node: AbsNode) =>
      t.status === 'planned' ? (
        <Box flexDirection="row" columnGap={1}>
          <Text wrap="truncate-end">
            {MARK[t.status] ?? '?'} {t.title}
          </Text>
          <Button
            key={`delegate-${t.id}`}
            label="Hand to a subagent"
            onPress={() => $.prompt.fill({ text: delegateDraft(t) })}
          />
        </Box>
      ) : (
        <Box flexDirection="column">
          <Text color={t.status === 'blocked' ? 'warning' : undefined} wrap="truncate-end">
            {MARK[t.status] ?? '?'} {t.title}
          </Text>
          <Text dimColor wrap="truncate-end">
            {'  '}
            {[tagOf(data, t), usage(t), node.id === focus?.id ? '' : node.title].filter(s => s !== '').join(' · ')}
          </Text>
          {t.status === 'blocked' && (
            <Box columnGap={1} paddingLeft={2}>
              <Button
                key={`extend-${t.id}`}
                label="Extend"
                variant="primary"
                onPress={() => $.prompt.fill({ text: extendDraft(t) })}
              />
              <Button
                key={`back-${t.id}`}
                label="Step back"
                onPress={() => $.prompt.fill({ text: stepBackDraft(t, node.title) })}
              />
              <Button
                key={`ban-${t.id}`}
                label="Ban"
                onPress={() => $.prompt.fill({ text: banDraft(t) })}
              />
            </Box>
          )}
        </Box>
      )

    // A node with no node under it: where the work is, and where a digest stands in for it.
    const isLeaf = (node: AbsNode): boolean => !data.nodes.some(c => c.parent === node.id)
    // One part of the level in view: its name in a column of one width, and beside it what it says.
    const partRow = (label: RenderElement, lines: RenderElement[]) => (
      <Box flexDirection="row" alignItems="flex-start" columnGap={1}>
        <Box width={Svg === undefined ? LABEL_COLUMNS.terminal : LABEL_COLUMNS.picture} flexShrink={0}>
          {label}
        </Box>
        <Box flexDirection="column" flexGrow={1} flexShrink={1}>
          {lines}
        </Box>
      </Box>
    )
    // Any point of the spec is pressed by its words: a press cites it in the prompt
    // box. The app draws a button on one line, so a long point is laid out in lines
    // here, each a button citing the whole point, lit together under the pointer.
    const textColumns = (indent: number): number =>
      Math.max(16, Math.floor((e.props.bodyColumns - indent) * (Svg === undefined ? 1 : 0.92)) - 1)
    const citable = (node: AbsNode, point: string, text: string, shownText: string, indent: number) => {
      const scope = `cite:${node.id}:${point}`.slice(0, 64)

      return (
        <Box flexDirection="column" flexGrow={1} flexShrink={1}>
          {lineUp(shownText, textColumns(indent)).map((line, i) => (
            <Button
              key={`${scope}:${i}`}
              plain
              hover={{ scope, underline: true }}
              onPress={() => citeInPrompt($, node, point, text)}
            >
              {line}
            </Button>
          ))}
        </Box>
      )
    }
    // A point with its mark before it: a rule, a ban, a line of a digest.
    const markedPoint = (node: AbsNode, p: Point, indent: number, markColor?: Tone) => (
      <Box flexDirection="row" alignItems="flex-start" columnGap={1}>
        <Text color={markColor}>{p.mark}</Text>
        {citable(node, p.point, p.text, p.text, indent + 2)}
      </Box>
    )
    const labelColumns = (Svg === undefined ? LABEL_COLUMNS.terminal : LABEL_COLUMNS.picture) + 1

    // Why a node is flagged, as the command words it, with the handles in it put into
    // words: a task by its name, a node by its title. An id says nothing to a reader.
    const reasonOf = (node: AbsNode): string =>
      node.health.reason
        .replace(/\bT\d+\b/g, id => {
          const t = data.tasks.find(x => x.id === id)

          return t === undefined ? id : `"${t.title.length > 48 ? `${t.title.slice(0, 47).trimEnd()}…` : t.title}"`
        })
        .replace(/'([\w-]+)'/g, (quoted, id) => data.nodes.find(n => n.id === id)?.title ?? quoted)

    // A part of the level in view, opened or not, and the press that turns it over. Each
    // part opens on its own: the person asks for what they want more of, and no more.
    const told = await read($, opened)
    const isOpened = (part: string): boolean => shown !== undefined && told.includes(`${shown.id}/${part}`)
    const turn = (part: string) => () =>
      update($, opened, was => {
        const key = `${shown?.id}/${part}`

        return was.includes(key) ? was.filter(k => k !== key) : [...was, key]
      })

    // What this view holds: the node in view and the nodes directly under it.
    const viewLines =
      shown === undefined
        ? 0
        : (shown.lines ?? 0) + data.nodes.filter(n => n.parent === shown.id).reduce((sum, n) => sum + (n.lines ?? 0), 0)

    return (
      <Box flexDirection="column">
        {/* The cap is on what one view holds. Its count is shown only when this view nears it. */}
        <Text dimColor>
          {data.repo}
          {viewLines >= 0.8 * data.size.cap ? ` · this view ${viewLines}/${data.size.cap} lines` : ''}
        </Text>
        {trouble !== null && (
          <Text color="warning" wrap="wrap">
            Not fresh: the last read of the state failed ({trouble}). This is what was read before; it
            is read again at the next edit, and every few seconds.
          </Text>
        )}

        {/* Zoomed in: the way back out, from the whole tree down to the node in view. */}
        {focus !== undefined && (
          <Box flexDirection="row" flexWrap="wrap" columnGap={1} marginTop={1}>
            {path.slice(0, -1).map(node => (
              <Button
                key={`crumb-${node.id}`}
                plain
                dimColor
                onPress={() => update($, selected, () => (node.id === root?.id ? null : node.id))}
              >
                {node.title} ›
              </Button>
            ))}
            <Text weight="semibold">{focus.title}</Text>
          </Box>
        )}

        {/* The tree as a picture, one level to a view. Under it, the nodes of
            its next level by name, in rows that say what they are: a press on
            a name zooms into that node. */}
        {Svg !== undefined && shown !== undefined && (
          <Box flexDirection="column" marginTop={1}>
            <Svg
              source={graphSvg(data, focus?.id ?? needs?.id, e.props.bodyColumns, focus?.id)}
              alt={asText(data)}
            />
            {layers.map(nodes => (
              <Box flexDirection="row" flexWrap="wrap" columnGap={1} rowGap={1} marginTop={1}>
                <Text dimColor>{nodes === partsUnder ? partsAre : 'Designs'}</Text>
                {nodes.map(node => (
                  <Button key={`design-${node.id}`} onPress={() => update($, selected, () => node.id)}>
                    {node.title}
                  </Button>
                ))}
              </Box>
            ))}
          </Box>
        )}

        {/* The same tree where no picture can be drawn: the node in view across
            the top, and on a spine down from it the nodes under it, side by
            side on a branch, each with its work hanging from it. Nothing is
            spaced apart here: a gap would break a line. */}
        {Svg === undefined && shown !== undefined && (
          <Box flexDirection="column" marginTop={1}>
            <Box
              borderStyle={shown.kind === 'component' ? 'dashed' : 'round'}
              borderColor={flagOf(shown) ?? INK}
              borderDimColor={flagOf(shown) === undefined}
              paddingX={1}
              flexDirection="column"
            >
              <Text weight="semibold">
                {shown.title}
              </Text>
              <Text dimColor wrap="wrap">
                {shown.kind === 'component' ? whose(data, shown) : shown.kind}
                {stateOf(shown) !== '' && ' · '}
                {stateOf(shown) !== '' && <Text color={flagOf(shown)}>{stateOf(shown)}</Text>}
              </Text>
              {focus === undefined && openOf(shown.id).length > 0 && (
                <Text dimColor>{openOf(shown.id).length} open</Text>
              )}
            </Box>
            {layers.length > 0 && (
              <Box flexDirection="column" paddingLeft={1}>
                <Box flexDirection="row" height={1}>
                  {joint({ rows: 1, at: 0, hasMore: true, isBare: true })}
                </Box>
                {layers.flatMap((nodes, i) => [
                  ...(nodes === partsUnder && designsUnder.length > 0 && focus === undefined
                    ? [
                        <Box flexDirection="row">
                          {joint({ rows: 1, at: 0, hasMore: true, isBare: true })}
                          <Text dimColor wrap="truncate-end">
                            Components shared by the designs
                          </Text>
                        </Box>,
                      ]
                    : []),
                  ...layer(nodes.map(tile), i < layers.length - 1),
                ])}
              </Box>
            )}
          </Box>
        )}

        {/* The plus under a design: one button, which starts the sentence that
            proposes a component. Nothing is thought up for the person ahead of time. */}
        {shown?.kind === 'design' && (
          <Box marginTop={Svg === undefined ? 0 : 1}>
            <Button
              key={`propose-${shown.id}`}
              label="+ Propose a component"
              onPress={() => $.prompt.fill({ text: `Propose a component under "${shown.title}": ` })}
            />
          </Box>
        )}

        {/* The node zoomed into: how it stands, and its open work with how far
            in it is and the buttons. Finished work is counted, never listed. */}
        {focus !== undefined &&
          (flagOf(focus) !== undefined || openOf(focus.id).length > 0) && (
          <Box flexDirection="column" rowGap={1} marginTop={1}>
            {/* Said only when the work under it flags it: a node on budget needs no line. */}
            {flagOf(focus) !== undefined && (
              <Text color={flagOf(focus)} wrap="wrap">
                {healthOf(focus).word}: {reasonOf(focus)}
              </Text>
            )}
            {openOf(focus.id).length > 0 && (
              <Box flexDirection="column">{openOf(focus.id).map(t => act(t, focus))}</Box>
            )}
          </Box>
        )}

        {/* The level in view, told in one column, in the order a leaf fills in:
            why it is needed, what makes it hard, how it is done, then, in place
            of a list of tasks, what it has now, what was turned back and what
            runs came to. A sentence a part, each opening on its own press, and
            its rules only counted. Nothing of the levels below but how much. */}
        {shown !== undefined && (
          <Box flexDirection="column" marginTop={1}>
            <Text weight="semibold">{shown.title}</Text>
            {shown.kind === 'component' && <Text dimColor wrap="wrap">{whose(data, shown)}</Text>}
            {storyOf(shown).map(part => {
              const name = part.label === '' ? 'Story' : part.label
              // A part that is one sentence has nothing more to open.
              const hasMore = lead(part.text) !== part.text

              return partRow(
                hasMore ? (
                  <Button key={`more-${name}`} plain onPress={turn(name)}>
                    {isOpened(name) ? '▾' : '▸'} {name}
                  </Button>
                ) : (
                  <Text>{`  ${name}`}</Text>
                ),
                [citable(shown, name, part.text, isOpened(name) ? part.text : lead(part.text), labelColumns)],
              )
            })}
            {/* A leaf with nothing in its digest: its approach has not been shown by any work. */}
            {isLeaf(shown) &&
              (shown.digest?.features ?? []).length === 0 &&
              partRow(<Text dimColor>{'  Has now'}</Text>, [
                <Text dimColor wrap="wrap">
                  Nothing shown yet: the approach is a plan.
                </Text>,
              ])}
            {digestOf(shown).map(([heading, points]) =>
              partRow(
                <Text>{`  ${heading}`}</Text>,
                points.map(p => markedPoint(shown, p, labelColumns)),
              ),
            )}
            {/* Beside a picture the names under it say what is one level down; without one, these lines do. */}
            {Svg === undefined &&
              layers.map(nodes => (
                <Text dimColor wrap="wrap">
                  {nodes === partsUnder ? partsAre : 'Designs'}: {nodes.map(n => n.title).join(', ')}
                </Text>
              ))}
            {(shown.invariants.length > 0 || shown.bans.length > 0) && (
              <Box>
                <Button key="more-rules" plain onPress={turn('rules')}>
                  {isOpened('rules') ? '▾' : '▸'}{' '}
                  {[
                    shown.invariants.length > 0 ? `${shown.invariants.length} rule${shown.invariants.length === 1 ? '' : 's'}` : '',
                    shown.bans.length > 0 ? `${shown.bans.length} banned` : '',
                  ]
                    .filter(part => part !== '')
                    .join(' · ')}
                </Button>
              </Box>
            )}
            {isOpened('rules') &&
              shown.invariants.map((text, i) => markedPoint(shown, { mark: '∙', point: `rule ${i + 1}`, text }, 0))}
            {isOpened('rules') &&
              shown.bans.map((text, i) => markedPoint(shown, { mark: '✗', point: `ban ${i + 1}`, text }, 0, 'error'))}
          </Box>
        )}

        {/* With the whole tree in view, only what needs the person is told
            under it: the node in trouble, named, wherever it sits, and every
            task that waits for their call, with the buttons. When nothing
            does, nothing is here. */}
        {focus === undefined && (needs !== undefined || waiting.length > 0) && (
          <Box flexDirection="column" marginTop={1}>
            {needs !== undefined && <Text weight="semibold">Needs you: {needs.title}</Text>}
            {needs !== undefined && needs.kind === 'component' && (
              <Text dimColor wrap="wrap">{whose(data, needs)}</Text>
            )}
            {needs !== undefined && (
              <Text color={healthOf(needs).tone} wrap="wrap">
                {healthOf(needs).word}: {reasonOf(needs)}
              </Text>
            )}
            {waiting.map(t => act(t, data.nodes.find(n => n.id === t.parent) ?? needs ?? data.nodes[0]!))}
          </Box>
        )}

        {/* Last, who is at work: it is about the moment, and the story comes first. */}
        {sessions.length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <Text dimColor>Sessions at work</Text>
            {sessions.map(s => (
              <Box flexDirection="column">
                {/* A press zooms to the node its task sits under. */}
                <Button
                  key={`session-${s.id}`}
                  plain
                  onPress={() =>
                    update(
                      $,
                      selected,
                      was => data.tasks.find(t => t.id === s.task)?.parent ?? was,
                    )
                  }
                >
                  {sessionLine(data, s)}
                </Button>
                <Text
                  color={DOING[s.state]?.tone}
                  dimColor={DOING[s.state]?.tone === undefined}
                  wrap="truncate-end"
                >
                  {'  '}
                  {sessionDetail(data, s)}
                </Text>
              </Box>
            ))}
          </Box>
        )}
      </Box>
    )
  })

  // One line above the prompt while work is open: the budget, as it is spent.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const data = await read($, snapshot)
    const open = data === null ? [] : data.tasks.filter(isOpen)
    const mine = data?.sessions?.find(s => s.me)?.task
    // What waits for the person comes first, then this session's own task.
    const first =
      open.find(t => t.status === 'blocked') ?? open.find(t => t.id === mine) ?? open[0]

    if (e.props.hasSurvey || data === null || first === undefined) {
      return next(e)
    }

    const { Box, Button, Text } = $.ui.resolve(e)
    const isBlocked = first.status === 'blocked'
    const by = who(data, first)
    // The other open tasks, each with who is on it: the work going on in parallel.
    const rest = open.filter(t => t !== first)
    const others = rest
      .slice(0, 3)
      .map(t => ` · ${MARK[t.status] ?? '?'} ${who(data, t) || t.title.slice(0, 24)}`)
      .join('')

    return (
      <Box columnGap={1}>
        <Text
          color={isBlocked ? 'warning' : undefined}
          dimColor={!isBlocked}
          wrap="truncate-end"
        >
          {MARK[first.status] ?? '?'} {first.title} · {usage(first)}
          {by === '' ? '' : ` · ${by}`}
          {isBlocked ? ' · far past its estimate, your call' : ''}
          {others}
          {rest.length > 3 ? ` · +${rest.length - 3} more` : ''}
        </Text>
        <Button
          key="pane-open"
          plain
          label="/thinspec"
          onPress={() => {
            void $.ui.open({ id: PANE, title: TITLE })
          }}
        />
      </Box>
    )
  })
}
