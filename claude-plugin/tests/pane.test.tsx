import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import type { AbsSnapshot } from '../types'

// What `thinspec state --json` would print for a small repo: one design on
// budget, one with a task that went far past its estimate and one still running.
const SNAPSHOT: AbsSnapshot = {
  repo: 'demo',
  size: { nodes: 3, lines: 14, cap: 150 },
  nodes: [
    {
      id: 'core',
      title: 'Storage level',
      kind: 'core',
      parent: null,
      version: 2,
      summary: '',
      invariants: ['Capture, then probe, then apply only if the probe passes.'],
      bans: [],
      health: { level: 'idle', reason: 'no work yet under this version' },
    },
    {
      id: 'instrument',
      title: 'Instrument',
      kind: 'design',
      parent: 'core',
      version: 1,
      summary: '',
      invariants: ['One unique hook point per step.'],
      bans: ['Stable node names across steps'],
      health: { level: 'ok', reason: 'work is within budget' },
    },
    {
      id: 'offload',
      title: 'Offload',
      kind: 'design',
      parent: 'core',
      version: 1,
      summary: '',
      invariants: ['The transfer ends before the peak.'],
      bans: [],
      health: { level: 'watch', reason: 'T7 went far past its estimate' },
    },
  ],
  tasks: [
    {
      id: 'T6',
      title: 'Register autograd hooks during forward',
      parent: 'instrument',
      status: 'done',
      check: 'overhead under 0.5%',
      budget: { trials: 4, patches: 25, minutes: 60 },
      actual: { trials: 3, patches: 18, minutes: 41 },
      result: 'Per-op overhead under 0.5%.',
    },
    {
      id: 'T7',
      title: 'Probe transfer time per storage',
      parent: 'offload',
      status: 'blocked',
      check: 't_xfer within 10% of predicted',
      budget: { trials: 4, patches: 20, minutes: 60 },
      actual: { trials: 8, patches: 16, minutes: 57 },
      result: null,
    },
    {
      id: 'T8',
      title: 'UVM probing for transfer-safe windows',
      parent: 'offload',
      status: 'active',
      check: 'no page fault inside a chosen window',
      budget: { trials: 5, patches: 30 },
      actual: { trials: 4, patches: 11, minutes: 52.4 },
      result: null,
    },
  ],
}

const PANE = {
  plugin: 'thinspec',
  component: 'Pane',
  requestId: 'thinspec',
  props: {
    title: 'ThinSpec',
    isFocused: false,
    bodyColumns: 48,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

const BAND = {
  plugin: 'thinspec',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isCollapsed: false,
    isWorking: false,
    maxRows: 6,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 6 },
    view: {},
  },
} as const

const SURFACES = ['terminal', 'desktop', 'vscode'] as const

// The person typing /thinspec at the prompt: the one command they have.
const OPEN = {
  command: 'thinspec',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: true, columns: 160 },
} as const

// Nothing sits beneath the plugin in a test: these hooks stand for the engine
// and for the thinspec command on the person's machine.
function standIn(
  on: On,
  state: () => { exitCode: number; stdout: string; stderr?: string },
): { drafts: string[]; runs: string[][]; commands: string[]; box: string; modes: string[] } {
  // The prompt box as the person left it, and how each fill wrote into it.
  const seen = { drafts: [] as string[], runs: [] as string[][], commands: [] as string[], box: '', modes: [] as string[] }

  on('command.register', (_, e) => {
    seen.commands.push(e.name)

    return { value: { command: e.name } }
  })
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('tool.call', () => ({ result: {} }))
  on('turn.complete', () => ({ text: '' }))
  on('process.run', (_, e) => {
    seen.runs.push([...e.argv])

    return {
      value: { stderr: '', ...state(), isStdoutTruncated: false, isStderrTruncated: false },
    }
  })
  on('prompt.read', () => ({ value: { text: seen.box, cursor: seen.box.length } }))
  on('prompt.fill', (_, e) => {
    seen.drafts.push(e.text)
    seen.modes.push(e.mode)
    seen.box = e.mode === 'append' ? seen.box + e.text : e.text

    return { isFilled: true }
  })

  return seen
}

const fromRepo = (data: AbsSnapshot) => () => ({
  exitCode: 0,
  stdout: JSON.stringify(data),
})

test('the pane shows each design and opens on the one that needs a decision', async ($, on) => {
  const seen = standIn(on, fromRepo(SNAPSHOT))

  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  // The person has one command, named after the thing: /thinspec. It opens the pane.
  expect(seen.commands).toEqual(['thinspec'])
  const ran = await $.command.run(OPEN)

  expect(ran.text).toBe('ThinSpec pane opened.')
  expect(seen.runs[0]).toEqual(['thinspec', 'state', '--json'])

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...PANE, surface })

    // Each design under the core has its name as a button. The core is the view,
    // so there is nothing to press for it.
    for (const id of ['instrument', 'offload']) {
      expect(await ui.find({ key: `design-${id}` })).toBeDefined()
    }
    expect(await ui.find({ key: 'design-core' })).toBeUndefined()
    // Offload holds the task that went far past its estimate, so it is the one named under
    // the tree, with that task and nothing else: no other task, no check text.
    expect(await ui.find({ type: 'Text', text: /^Needs you: Offload$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /watch: "Probe transfer time per storage" went far past its estimate/ })).toBeDefined()
    expect(
      await ui.find({ type: 'Text', text: /8\/4 trials · 16\/20 patches · 57\/60 min/ }),
    ).toBeDefined()
    expect(wordsOf(await ui.drawn())).not.toContain('t_xfer within 10% of predicted')
    expect(await ui.find({ type: 'Text', text: /11\/30 patches/ })).toBeUndefined()
    // Zoomed into Offload its other open task is told too. A metric with no budget is
    // left out, and minutes are not shown to the tenth.
    await ui.press({ key: 'design-offload' })
    expect(await ui.find({ type: 'Text', text: /4\/5 trials · 11\/30 patches$/ })).toBeDefined()
    await home(ui)
    await ui.unmount()
  }
})

test('pressing a design shows its invariants, bans and tasks', async ($, on) => {
  standIn(on, fromRepo(SNAPSHOT))
  await $.command.run(OPEN)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...PANE, surface })

    await home(ui)
    await ui.press({ key: 'design-instrument' })
    await tellAll(ui)
    expect(flat(await ui.drawn())).toContain('One unique hook point per step')
    expect(flat(await ui.drawn())).toContain('Stable node names across steps')
    // Its finished work is neither listed nor counted, and a node on track says nothing of itself.
    expect(wordsOf(await ui.drawn())).not.toMatch(NOISE)
    expect(wordsOf(await ui.drawn())).not.toMatch(/Register autograd hooks|Done · 1|T6/)
    expect(await ui.find({ key: 'extend-T7' })).toBeUndefined()
    await ui.unmount()
  }
})

test('a decision button starts the sentence in the prompt box and records nothing', async ($, on) => {
  const seen = standIn(on, fromRepo(SNAPSHOT))

  await $.command.run(OPEN)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  const runsBefore = seen.runs.length

  await ui.press({ key: 'extend-T7' })
  await ui.press({ key: 'back-T7' })
  await ui.press({ key: 'ban-T7' })

  expect(seen.drafts).toEqual([
    'Extend T7 by 2 trials, 10 patches, 30 min. ',
    'Step back from T7. What the design "Offload" missed: ',
    'Ban the approach of T7 ("Probe transfer time per storage"). Reason: ',
  ])
  // The person's words go through Claude; the pane itself runs no decision.
  expect(seen.runs.slice(runsBefore)).toEqual([])
  await ui.unmount()
})

test('a planned task has a button that starts handing it to a subagent and records nothing', async ($, on) => {
  const planned: AbsSnapshot['tasks'][number] = {
    id: 'T9',
    title: 'Schedule the offload to end before the peak',
    parent: 'offload',
    status: 'planned',
    check: 'end <= t_peak - t_xfer holds on every step',
    budget: { trials: 4, patches: 25, minutes: 90 },
    actual: { trials: 0, patches: 0, minutes: 0 },
    result: null,
  }
  const unbudgeted = { ...planned, id: 'T10', title: 'Pick the storage tier', budget: {} }
  let data: AbsSnapshot = { ...SNAPSHOT, tasks: [...SNAPSHOT.tasks, planned, unbudgeted] }
  const seen = standIn(on, () => ({ exitCode: 0, stdout: JSON.stringify(data) }))

  await $.command.run(OPEN)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...PANE, surface })
    const runsBefore = seen.runs.length

    // Under the whole tree only what waits for the person is told: nothing is handed over
    // from there. The button is on the task's line once its node is zoomed into.
    await home(ui)
    expect(await ui.find({ key: 'delegate-T9' })).toBeUndefined()
    await ui.press({ key: 'design-offload' })
    seen.drafts.length = 0
    await ui.press({ key: 'delegate-T9' })
    await ui.press({ key: 'delegate-T10' })
    expect(wordsOf(await ui.drawn())).not.toContain('end <= t_peak') // the check stays in the record

    expect(seen.drafts).toEqual([
      'Hand T9 ("Schedule the offload to end before the peak") to a subagent with its planned budget (4 trials, 25 patches, 90 min). ',
      'Hand T10 ("Pick the storage tier") to a subagent. Budget: ',
    ])
    // The sentence is the person's to finish and send; the pane runs nothing.
    expect(seen.runs.slice(runsBefore)).toEqual([])
    // A task that is already running, or waiting for a decision, has no such button.
    expect(await ui.find({ key: 'delegate-T7' })).toBeUndefined()
    expect(await ui.find({ key: 'delegate-T8' })).toBeUndefined()
    await home(ui)
    await ui.unmount()
  }

  // With nothing in trouble, nothing is told under the whole tree: no node is named, and
  // the planned task is in the tree and nowhere else.
  data = {
    ...SNAPSHOT,
    nodes: SNAPSHOT.nodes.map(n => ({ ...n, health: { level: 'ok', reason: 'work is within budget' } })),
    tasks: [...SNAPSHOT.tasks.filter(t => t.status === 'done'), planned],
  }
  await $.command.run(OPEN)

  for (const surface of SURFACES) {
    const calm = await $.ui.mount({ ...PANE, surface })

    expect(await calm.find({ key: 'delegate-T9' })).toBeUndefined()
    expect(wordsOf(await calm.drawn())).not.toMatch(/Needs you|Ready to hand over|ready to delegate/)
    expect(wordsOf(await calm.drawn())).toContain('Schedule the offlo') // cut where a picture is narrow
    await calm.unmount()
  }
})

/** Back to the whole tree, where an earlier press zoomed into a node. */
async function home(ui: {
  find: (query: { key: string }) => Promise<unknown>
  press: (query: { key: string }) => Promise<unknown>
}): Promise<void> {
  if ((await ui.find({ key: 'crumb-core' })) !== undefined) await ui.press({ key: 'crumb-core' })
}

// Everything the pane says, in the order drawn, a line for each text and button. Where the
// tree is a picture, the words in the picture are among them.
function wordsOf(tree: unknown): string {
  if (typeof tree === 'string') return tree
  if (tree === null || typeof tree !== 'object') return ''

  const el = tree as { type?: unknown; source?: unknown; props?: { source?: unknown; label?: unknown }; children?: unknown[] }

  if (el.type === 'Svg') {
    return String(el.props?.source ?? el.source ?? '')
      .replace(/<style>.*?<\/style>/g, '')
      .replace(/<\/?tspan[^>]*>/g, '')
      .replace(/<[^>]+>/g, '\n')
  }

  const inside = (el.children ?? []).map(wordsOf).join(el.type === 'Text' ? '' : '\n')

  return el.type === 'Button' && inside === '' ? String(el.props?.label ?? '') : inside
}

/** The names of the parts of the level in view, in the order drawn: each sits in the column of one width. */
function labelsOf(tree: unknown): string[] {
  if (tree === null || typeof tree !== 'object') return []

  const el = tree as { type?: unknown; props?: { width?: unknown }; children?: unknown[] }

  if (el.type === 'Box' && (el.props?.width === 11 || el.props?.width === 14)) return [wordsOf(tree).replace(/\s+/g, ' ').trim()]

  return (el.children ?? []).flatMap(labelsOf)
}

// What asks nothing of the person and is not drawn: that a node is on track, how much
// finished work it has, and how many nodes are under it.
const NOISE = /on budget|no work yet|\b\d+ (done|abandoned|stepped back)\b|\b\d+ (components?|parts?|nodes? under it)\b|it can do/

/** What the pane says as running text: a point laid out over several lines reads as one sentence. */
const flat = (tree: unknown): string => wordsOf(tree).replace(/\s+/g, ' ')

/** The picture of the tree, where the surface draws one: its markup. */
function pictureOf(tree: unknown): string | undefined {
  if (tree === null || typeof tree !== 'object') return undefined

  const el = tree as { type?: unknown; source?: unknown; props?: { source?: unknown } }

  if (el.type === 'Svg') return String(el.props?.source ?? el.source ?? '')

  for (const child of Object.values(tree)) {
    const found = pictureOf(child)

    if (found !== undefined) return found
  }

  return undefined
}

/** Every part of the level in view opened: its whole story and its rules. Each opens on its own press. */
async function tellAll(ui: {
  find: (query: { key: string }) => Promise<unknown>
  press: (query: { key: string }) => Promise<unknown>
}): Promise<void> {
  for (const part of ['Motivation', 'Challenge', 'Approach', 'Insight', 'rules']) {
    const more = (await ui.find({ key: `more-${part}` })) as { text?: string } | undefined

    if (more?.text?.startsWith('▸')) await ui.press({ key: `more-${part}` })
  }
}

// The boxes of nodes a terminal drew, in the order drawn: how each is edged, and the name
// on the button in it. The box across the top holds no button. A task's box is edged
// 'single', and is read by joinsOf.
function boxesOf(tree: unknown): { edge: string; name: string }[] {
  const out: { edge: string; name: string }[] = []
  const walk = (x: unknown): void => {
    if (x === null || typeof x !== 'object') return

    const el = x as { type?: unknown; props?: { borderStyle?: unknown }; children?: unknown[] }

    if (el.type === 'Box' && typeof el.props?.borderStyle === 'string' && el.props.borderStyle !== 'single') {
      const button = (el.children ?? []).find(
        c => typeof c === 'object' && c !== null && (c as { type?: unknown }).type === 'Button',
      ) as { props?: { label?: unknown } } | undefined

      out.push({ edge: el.props.borderStyle, name: String(button?.props?.label ?? '') })
    }

    for (const child of Object.values(x)) walk(child)
  }

  walk(tree)

  return out
}

test('where the app draws pictures the tree is one, clean, and the names under it are pressed', async ($, on) => {
  standIn(on, fromRepo(SNAPSHOT))
  await $.command.run(OPEN)

  for (const surface of ['desktop', 'vscode'] as const) {
    for (const bodyColumns of [48, 100]) {
      const ui = await $.ui.mount({ ...PANE, props: { ...PANE.props, bodyColumns }, surface })

      await home(ui)

      // One picture: the core, its designs joined to it by lines, their open work by name
      // under them. Finished work is not counted, and only the node in trouble says how it stands.
      const picture = pictureOf(await ui.drawn()) ?? ''

      expect(picture).toContain('<path class="ln"')
      for (const said of ['>Storage level</text>', '>Instrument</text>', '>Offload</text>', '>8/4 trials</text>', '>! watch</tspan>']) {
        expect(picture).toContain(said)
      }
      expect(picture.replace(/<style>.*?<\/style>/, '')).not.toMatch(NOISE)
      expect(picture).not.toMatch(/>T\d+<\/text>/) // nothing is labelled with an id alone
      expect(boxesOf(await ui.drawn())).toEqual([])
      expect(joinsOf(await ui.drawn())).toEqual({ glyphs: [], tasks: [] })

      // A picture takes no press. Under it, in a row that says what they are, the nodes of
      // the next level by name: a press on a name zooms the picture into that node.
      const told = JSON.stringify(await ui.drawn())

      expect(await ui.find({ type: 'Text', text: /^Designs$/ })).toBeDefined()
      expect(told.indexOf('"type":"Svg"')).toBeLessThan(told.indexOf('design-instrument'))
      await ui.press({ key: 'design-instrument' })
      expect(pictureOf(await ui.drawn())).toContain('<rect class="cd co hd')
      expect(pictureOf(await ui.drawn())).not.toMatch(/>v\d+<\/text>|Register autograd hooks/) // no version, no finished task
      expect(pictureOf(await ui.drawn())).not.toContain('>Offload</text>')
      expect(await ui.find({ key: 'design-offload' })).toBeUndefined()
      await ui.press({ key: 'crumb-core' })
      expect(await ui.find({ key: 'design-offload' })).toBeDefined()
      await ui.unmount()
    }
  }
})

test('a terminal draws the same tree in boxes, one level to a view, a name in its box the button', async ($, on) => {
  standIn(on, fromRepo(SNAPSHOT))
  await $.command.run(OPEN)

  for (const surface of ['terminal'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })

    await home(ui)

    // A terminal draws no picture. The node in view is a box across the top, and each
    // node under it is a box whose name is a button.
    expect(pictureOf(await ui.drawn())).toBeUndefined()
    expect(boxesOf(await ui.drawn())).toEqual([
      { edge: 'round', name: '' },
      { edge: 'round', name: 'Instrument' },
      { edge: 'round', name: 'Offload' },
    ])
    expect(await ui.find({ type: 'Text', text: /^Storage level$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^! watch$/ })).toBeDefined()

    // It reads with no key. Open work has its name, and under it how far in and its id.
    // Finished work is not counted. Nothing is labelled with an id alone.
    for (const line of [
      /^⏸ Probe transfer time per storage$/,
      /^\s*8\/4 trials$/,
      /^● UVM probing for transfer-safe windows$/,
      /^\s*4\/5 trials$/,
    ]) {
      expect(await ui.find({ type: 'Text', text: line })).toBeDefined()
    }
    expect(wordsOf(await ui.drawn())).not.toMatch(NOISE)
    expect(await ui.find({ type: 'Text', text: /^T\d+$/ })).toBeUndefined()

    // A press on a design's name zooms into it: that design across the top, nothing of the
    // other one, all of its own work by name, and above the tree the way back.
    await ui.press({ key: 'design-instrument' })
    expect(boxesOf(await ui.drawn())).toEqual([{ edge: 'round', name: '' }])
    expect(await ui.find({ type: 'Text', text: /^Instrument$/ })).toBeDefined()
    expect(await ui.find({ key: 'design-offload' })).toBeUndefined()
    expect(wordsOf(await ui.drawn())).not.toMatch(NOISE)
    expect(await ui.find({ type: 'Text', text: /Register autograd hooks/ })).toBeUndefined()
    expect(wordsOf(await ui.drawn())).not.toMatch(/\bv\d\b|\bT\d+\b/) // no version and no task id anywhere
    await ui.press({ key: 'crumb-core' })
    expect(await ui.find({ key: 'design-offload' })).toBeDefined()
    expect(await ui.find({ key: 'crumb-core' })).toBeUndefined()
    await ui.unmount()
  }
})

// The joins of the tree as a terminal draws them, in the order drawn: each a text of line
// glyphs. And the boxes of tasks, which are edged 'single': the lines in each.
function joinsOf(tree: unknown): { glyphs: string[]; tasks: string[][] } {
  const out = { glyphs: [] as string[], tasks: [] as string[][] }
  const said = (x: unknown): string =>
    typeof x === 'string'
      ? x
      : ((x as { children?: unknown[] } | null)?.children ?? []).map(said).join('')
  const walk = (x: unknown): void => {
    if (x === null || typeof x !== 'object') return

    const el = x as { type?: unknown; props?: { borderStyle?: unknown }; children?: unknown[] }

    if (el.type === 'Text' && /^[│├└─┬┐ \n]*[│├└─][│├└─┬┐ \n]*$/.test(said(el))) out.glyphs.push(said(el))
    if (el.type === 'Box' && el.props?.borderStyle === 'single') out.tasks.push((el.children ?? []).map(said))

    for (const child of Object.values(x)) walk(child)
  }

  walk(tree)

  return out
}

test('in a terminal the boxes are joined into a tree: a spine, a branch to each node, and its work hanging under it', async ($, on) => {
  standIn(on, fromRepo(SNAPSHOT))
  await $.command.run(OPEN)

  // The open work of Offload, each task in a box of its own under Offload's box.
  const hanging = [
    ['⏸ Probe transfer time per storage', '8/4 trials'],
    ['● UVM probing for transfer-safe windows', '4/5 trials'],
  ]

  // A pane too narrow for two boxes side by side: each design on a branch of its own.
  const narrow = await $.ui.mount({ ...PANE, surface: 'terminal' })

  await home(narrow)
  expect(joinsOf(await narrow.drawn())).toEqual({
    glyphs: [
      '│', // the spine leaves the core's box
      ['├─', '│', '│', '│', '│'].join('\n'), // a branch to Instrument, and on down past it
      '─┐', // the drop into its box: it is on track, so the box holds its name and nothing hangs from it
      ['└─', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' '].join('\n'), // the last branch: to Offload
      '─┐',
      ['│', '├─', '│', '│'].join('\n'), // its rail meets the first task's box and goes on
      ['│', '└─', ' ', ' '].join('\n'), // and ends at the second
    ],
    tasks: hanging,
  })
  // A node's name is still the button that zooms in, and the path leads back.
  await narrow.press({ key: 'design-offload' })
  expect(await narrow.find({ key: 'crumb-core' })).toBeDefined()
  await home(narrow)
  await narrow.unmount()

  // Wide enough for both: one branch off the spine runs over the two boxes, with a drop into each.
  const wide = await $.ui.mount({ ...PANE, props: { ...PANE.props, bodyColumns: 80 }, surface: 'terminal' })

  expect(joinsOf(await wide.drawn()).glyphs.slice(0, 5)).toEqual([
    '│',
    ['└─', ...Array.from({ length: 13 }, () => ' ')].join('\n'),
    `─┬${'─'.repeat(36)}`, // over Instrument, and on to Offload
    '─┐', // nothing hangs from Instrument: the drop into Offload comes next
    ['│', '├─', '│', '│'].join('\n'),
  ])
  await wide.unmount()
})

test('a press on any point of the spec quotes it in the prompt box, one quote at a time, and keeps what was typed', async ($, on) => {
  const seen = standIn(on, fromRepo(NESTED))

  await $.command.run(OPEN)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...PANE, surface })
    const runsBefore = seen.runs.length

    // The prompt box, as the person left it: one line typed, no newline after it.
    seen.box = 'Look at this:'
    seen.modes.length = 0
    await home(ui)
    await ui.press({ key: 'design-hold' })
    await ui.press({ key: 'design-spec-graph' })

    // A part of the story, by its words.
    const motivation = (await ui.findAll({ type: 'Button' })).filter(b => /^cite:spec-graph:Motivation:/.test(String(b.key)))

    expect(motivation.length).toBeGreaterThan(0)
    await ui.press({ key: String(motivation[0]?.key) })
    // A rule, once the rules are open (they stay open from one view to the next), and a line of the digest.
    if ((await ui.find({ key: 'more-rules' }))?.text?.startsWith('▸')) await ui.press({ key: 'more-rules' })
    const rule = (await ui.findAll({ type: 'Button' })).find(b => /^cite:spec-graph:rule 1:0$/.test(String(b.key)))

    expect(rule?.text).toBe('A node is a short file.')
    await ui.press({ key: 'cite:spec-graph:rule 1:0' })
    const turnedBack = (await ui.findAll({ type: 'Button' })).filter(b => /^cite:spec-graph:turned back:/.test(String(b.key)))

    // A long point is laid out over several lines, each one citing the whole of it.
    expect(turnedBack.length).toBeGreaterThan(surface === 'terminal' ? 1 : 0)
    await ui.press({ key: String(turnedBack.at(-1)?.key) })

    // One quote at a time: each press replaces the quote the one before put in the box,
    // and what the person typed stays.
    expect(seen.modes).toEqual(['replace', 'replace', 'replace'])
    expect(seen.box).toBe(
      ['Look at this:', '> Spec graph · turned back: A node for every code module: nobody read the tree.', ''].join('\n'),
    )
    // The person goes on under the quote; a press on another point puts its quote where the
    // last one stood, and their words stay under it.
    seen.box += 'make it shorter'
    await ui.press({ key: 'cite:spec-graph:rule 1:0' })
    expect(seen.box).toBe(['Look at this:', '> Spec graph · rule 1: A node is a short file.', 'make it shorter'].join('\n'))
    // A quote the person edited is theirs: it stays, and the next quote goes after it.
    seen.box = ['Look at this:', '> Spec graph · rule 1: a node is short, and in my words', ''].join('\n')
    await ui.press({ key: String(motivation[0]?.key) })
    expect(seen.box).toBe(
      [
        'Look at this:',
        '> Spec graph · rule 1: a node is short, and in my words',
        '> Spec graph · Motivation: A spec is read in one sitting.',
        '',
      ].join('\n'),
    )
    // An empty box takes the quote alone.
    seen.box = ''
    await ui.press({ key: 'cite:spec-graph:rule 1:0' })
    expect(seen.box).toBe('> Spec graph · rule 1: A node is a short file.\n')
    // The quote is the person's to go on from, by typing or speaking: nothing is sent or recorded.
    expect(seen.runs.slice(runsBefore)).toEqual([])
    await home(ui)
    await ui.unmount()
  }
})

test('the line above the prompt names the task that waits, and stays away when nothing is open', async ($, on) => {
  let data = SNAPSHOT
  standIn(on, () => ({ exitCode: 0, stdout: JSON.stringify(data) }))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine</Text>
  })

  await $.command.run(OPEN)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...BAND, surface })
    const row = await ui.find({ type: 'Text', text: /Probe transfer/ })

    expect(row?.text).toContain('Probe transfer time per storage · 8/4 trials · 16/20 patches · 57/60 min')
    expect(row?.text).toContain('far past its estimate, your call')
    expect(row?.text).toContain(' · ● UVM probing for transfer') // the other open task, named after it
    await ui.unmount()
  }

  data = { ...SNAPSHOT, tasks: SNAPSHOT.tasks.filter(t => t.status === 'done') }
  await $.command.run(OPEN)
  const quiet = await $.ui.mount({ ...BAND, surface: 'terminal' })

  expect((await quiet.find({ type: 'Text', text: /engine/ }))?.text).toBe('engine')
  await quiet.unmount()
})

test('the view follows the work: an edit or a check run re-reads the repo', async ($, on) => {
  let data = SNAPSHOT
  const seen = standIn(on, () => ({ exitCode: 0, stdout: JSON.stringify(data) }))

  await $.command.run(OPEN)
  data = {
    ...SNAPSHOT,
    tasks: SNAPSHOT.tasks.map(t =>
      t.id === 'T8' ? { ...t, actual: { ...t.actual, patches: 12 } } : t,
    ),
  }
  await $.tool.call({ tool: 'Read', file_path: '/repo/a.py' })
  expect(seen.runs.length).toBe(1) // reading moves no budget
  await $.tool.call({ tool: 'Bash', command: 'pytest -q' })
  expect(seen.runs.length).toBe(2)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })

  await ui.press({ key: 'design-offload' }) // a task's every measure is told where its node is zoomed into
  expect(await ui.find({ type: 'Text', text: /4\/5 trials · 12\/30 patches/ })).toBeDefined()
  await ui.unmount()
})

// What the thinspec command answers where there is no ThinSpec repo.
const NO_REPO = {
  exitCode: 1,
  stdout: '',
  stderr: 'thinspec: No ThinSpec repo here. Run `thinspec init` at the root of your project.\n',
}

test('a read of the state that fails keeps the last picture, says why, and is tried again', async ($, on) => {
  let answer: { exitCode: number; stdout: string; stderr?: string } = fromRepo(SNAPSHOT)()
  const seen = standIn(on, () => answer)
  const crash = {
    exitCode: 1,
    stdout: '',
    stderr: 'Traceback (most recent call last):\n  File "store.py", line 147, in load_nodes\nFileNotFoundError: abstraction/offload.md\n',
  }

  await $.command.run(OPEN)

  for (const surface of SURFACES) {
    // The state cannot be read: a node file was caught halfway through a rename.
    answer = crash
    await $.tool.call({ tool: 'Bash', command: 'thinspec node rename offload spill' })

    const ui = await $.ui.mount({ ...PANE, surface })

    // The graph that was read before is still there, with the reason it is not fresh.
    expect(await ui.find({ key: 'design-offload' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /No abstraction/ })).toBeUndefined()
    expect(
      (await ui.find({ type: 'Text', text: /Not fresh/ }))?.text,
    ).toContain('thinspec exited with 1: FileNotFoundError: abstraction/offload.md')

    // The next edit reads again, and the pane follows it: nothing was switched off.
    answer = fromRepo({
      ...SNAPSHOT,
      tasks: SNAPSHOT.tasks.map(t => (t.id === 'T8' ? { ...t, actual: { ...t.actual, patches: 12 } } : t)),
    })()
    const before = seen.runs.length

    await $.tool.call({ tool: 'Bash', command: 'pytest -q' })
    expect(seen.runs.length).toBe(before + 1)
    await ui.press({ key: 'design-offload' })
    expect(await ui.find({ type: 'Text', text: /4\/5 trials · 12\/30 patches/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Not fresh/ })).toBeUndefined()
    await home(ui)
    await ui.unmount()
  }

  // Only thinspec's own word that there is no repo here empties the pane, and then nothing is run per tool call.
  answer = NO_REPO
  await $.tool.call({ tool: 'Bash', command: 'rm -rf .thinspec' })
  const gone = await $.ui.mount({ ...PANE, surface: 'desktop' })

  expect(await gone.find({ type: 'Text', text: /No abstraction found in this project/ })).toBeDefined()
  const after = seen.runs.length

  await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(seen.runs.length).toBe(after)
  await gone.unmount()
})

test('a first read that fails says why and does not send the reader to init', async ($, on) => {
  standIn(on, () => ({ exitCode: 1, stdout: '', stderr: 'Traceback (most recent call last):\nPermissionError: .thinspec/ledger.jsonl\n' }))

  const ran = await $.command.run(OPEN)

  expect(ran.text).toContain("could not read this project's state: thinspec exited with 1: PermissionError")
  expect(ran.text).not.toContain('thinspec init')

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })

  expect(await ui.find({ type: 'Text', text: /No abstraction/ })).toBeUndefined()
  expect((await ui.find({ type: 'Text', text: /could not read/ }))?.text).toContain('PermissionError: .thinspec/ledger.jsonl')
  await ui.unmount()
})

test('outside a ThinSpec repo it says so and runs nothing per tool call', async ($, on) => {
  const seen = standIn(on, () => NO_REPO)

  const ran = await $.command.run(OPEN)

  expect(ran.text).toContain('thinspec init')
  await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(seen.runs.length).toBe(1)

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })

  expect((await ui.find({ type: 'Text', text: /No abstraction/ }))?.text).toBe(
    'No abstraction found in this project.',
  )
  await ui.unmount()
})

test('a minimized pane on the desktop app shows the count that matters', async ($, on) => {
  standIn(on, fromRepo(SNAPSHOT))
  await $.command.run(OPEN)

  const ui = await $.ui.mount({
    ...PANE,
    props: { ...PANE.props, placement: 'widget' },
    surface: 'desktop',
  })

  expect((await ui.find({ type: 'Text', text: /waiting/ }))?.text).toBe('1 waiting for your call')
  await ui.unmount()
})

// Two sessions at work: this one on T8, and one in another agent, on another
// machine, on T7, which waits for its person.
const WITH_SESSIONS: AbsSnapshot = {
  ...SNAPSHOT,
  tasks: SNAPSHOT.tasks.map(t => (t.id === 'T7' ? { ...t, status: 'active' } : t)),
  sessions: [
    {
      id: 'me-1234',
      name: 'claude-code me12',
      agent: 'claude-code',
      host: 'laptop',
      dir: 'demo',
      here: true,
      me: true,
      task: 'T8',
      state: 'working',
      since: '14:10',
    },
    {
      id: 'c0dec0de',
      name: 'codex c0de',
      agent: 'codex',
      host: 'devbox',
      dir: 'demo',
      here: false,
      me: false,
      task: 'T7',
      state: 'waiting',
      since: '14:02',
    },
  ],
}

test('the line above the prompt names who is working on each open task', async ($, on) => {
  const seen = standIn(on, fromRepo(WITH_SESSIONS))

  on('session.id', () => ({ value: 'me-1234' }))
  await $.command.run(OPEN)
  // The state is asked for by this session's id, so that it can mark it.
  expect(seen.runs[0]).toEqual(['thinspec', 'state', '--json', '--session', 'me-1234'])

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...BAND, surface })
    const row = await ui.find({ type: 'Text', text: /UVM probing/ })

    // This session's own task leads. The other session's follows, with its name.
    expect(row?.text).toContain(
      '● UVM probing for transfer-safe windows · 4/5 trials · 11/30 patches · you',
    )
    expect(row?.text).toContain(' · ● codex c0de on devbox')
    await ui.unmount()
  }
})

test('a thinspec command from before the sessions is asked again the way it knows', async ($, on) => {
  const seen: { drafts: string[]; runs: string[][] } = standIn(on, () =>
    seen.runs.at(-1)?.includes('--session') ? { exitCode: 2, stdout: '' } : fromRepo(SNAPSHOT)(),
  )

  on('session.id', () => ({ value: 'me-1234' }))
  expect((await $.command.run(OPEN)).text).toBe('ThinSpec pane opened.')
  expect(seen.runs).toEqual([
    ['thinspec', 'state', '--json', '--session', 'me-1234'],
    ['thinspec', 'state', '--json'],
  ])
})

// A third session, quiet for days, still holds a task under the other design.
const THREE_SESSIONS: AbsSnapshot = {
  ...WITH_SESSIONS,
  tasks: [
    ...WITH_SESSIONS.tasks,
    {
      id: 'T9',
      title: 'Hook the backward pass',
      parent: 'instrument',
      status: 'active',
      check: 'hooks match on workload B',
      budget: { patches: 5 },
      actual: { trials: 0, patches: 2, minutes: 3 },
      result: null,
    },
  ],
  sessions: [
    ...(WITH_SESSIONS.sessions ?? []),
    {
      id: 'third-01',
      name: 'claude-code thir',
      agent: 'claude-code',
      host: 'laptop',
      dir: 'demo-wt',
      here: true,
      me: false,
      task: 'T9',
      state: 'quiet',
      since: 'Nov 12 09:30',
    },
  ],
}

test('the pane lists each session at work with its task, and a press shows the design above it', async ($, on) => {
  standIn(on, fromRepo(THREE_SESSIONS))
  on('session.id', () => ({ value: 'me-1234' }))
  await $.command.run(OPEN)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...PANE, surface })

    for (const id of ['me-1234', 'c0dec0de', 'third-01']) {
      expect(await ui.find({ key: `session-${id}` })).toBeDefined()
    }
    // Under each: the design above its task, how far into the budget, and what it is doing.
    expect(
      await ui.find({ type: 'Text', text: /Offload · 4\/5 trials · 11\/30 patches · working$/ }),
    ).toBeDefined()
    expect(
      await ui.find({
        type: 'Text',
        text: /Offload · 8\/4 trials · 16\/20 patches · 57\/60 min · waiting for its person since 14:02$/,
      }),
    ).toBeDefined()
    expect(
      await ui.find({ type: 'Text', text: /Instrument · 2\/5 patches · quiet since Nov 12 09:30$/ }),
    ).toBeDefined()

    // With Offload in view, a press on the quiet session moves to the design its task is under.
    await home(ui)
    await ui.press({ key: 'design-offload' })
    expect(flat(await ui.drawn())).not.toContain('One unique hook point per step')
    await ui.press({ key: 'session-third-01' })
    await tellAll(ui) // what is opened is kept per node
    expect(flat(await ui.drawn())).toContain('One unique hook point per step')
    await ui.unmount()
  }

  // In the tree, a task a session is on says who: "you", or the end of the session's name.
  for (const surface of ['terminal', 'desktop'] as const) {
    const wide = await $.ui.mount({ ...PANE, props: { ...PANE.props, bodyColumns: 100 }, surface })

    await home(wide)

    const said = wordsOf(await wide.drawn())

    // Who is on it, then how far in, then its id.
    for (const facts of ['you · 4/5 trials', 'c0de · 8/4 trials', 'thir · 2/5 patches']) {
      expect(said).toContain(facts)
    }
    expect(said).not.toMatch(NOISE) // T6 is done: neither listed nor counted
    expect(said).not.toMatch(/^T\d+$/m) // nothing is labelled with an id alone
    await wide.unmount()
  }

  const widget = await $.ui.mount({
    ...PANE,
    props: { ...PANE.props, placement: 'widget' },
    surface: 'desktop',
  })

  expect(await widget.find({ type: 'Text', text: /2 designs|3 designs/ })).toBeDefined()
  expect((await widget.find({ type: 'Text', text: /sessions/ }))?.text).toContain('3 open · 3 sessions')
  await widget.unmount()
})

test('the pane follows the other sessions while this one sits idle', async ($, on) => {
  let data = WITH_SESSIONS
  const seen = standIn(on, () => ({ exitCode: 0, stdout: JSON.stringify(data) }))
  const clock = mock.clock(on)

  await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true })
  expect(seen.runs.length).toBe(1)

  // The other session's person answers it: it works again. This session calls no tool.
  data = {
    ...WITH_SESSIONS,
    sessions: (WITH_SESSIONS.sessions ?? []).map(s => (s.me ? s : { ...s, state: 'working' })),
  }
  await clock.advance(14_000)
  expect(seen.runs.length).toBe(1)
  await clock.advance(1_000)
  expect(seen.runs.length).toBe(2)

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })

  expect(await ui.find({ type: 'Text', text: /57\/60 min · working$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /waiting for its person/ })).toBeUndefined()
  await ui.unmount()
})

type Row = AbsSnapshot['nodes'][number]

const row = (
  id: string,
  title: string,
  kind: string,
  parent: string | null,
  level: string,
  reason: string,
  invariant: string,
): Row => ({
  id,
  title,
  kind,
  parent,
  version: 1,
  summary: '',
  invariants: [invariant],
  bans: [],
  health: { level, reason },
})

// A spec in the shape ThinSpec's own has: two designs, which are decisions, each
// carried out by a component, and one component the designs share. The task
// under one component is past its estimate, which shows on the design above it.
const NESTED: AbsSnapshot = {
  repo: 'demo',
  size: { nodes: 6, lines: 40, cap: 150 },
  nodes: [
    {
      ...row('core', 'ThinSpec', 'core', null, 'watch', "'overrun' under it: T2 is past its estimate", 'x'),
      summary:
        '**Motivation.** Nobody can read what agents write. **Challenge.** A wrong design is patched around until every check passes. **Insight.** Hold a thin spec.',
    },
    {
      ...row('hold', 'People hold the spec, not the code', 'design', 'core', 'ok', 'the work under it is within budget', 'The spec is small enough to read whole.'),
      summary:
        '**Motivation.** Agents write faster than anyone can read. So the person is the bottleneck. **Challenge.** Whatever the person holds has to stay small. **Approach.** The person holds a thin spec.',
    },
    {
      ...row('spec-graph', 'Spec graph', 'component', 'hold', 'ok', 'work is within budget', 'A node is a short file.'),
      summary: '**Motivation.** A spec is read in one sitting. **Challenge.** Left alone it grows like code. **Approach.** A tree of short files.',
      // What the person reads under it in place of its tasks.
      digest: {
        features: ['A node is one short file a person edits by hand.'],
        as_built: ['Kept as plain files, with no database: a person has to be able to edit one (likely).'],
        reverts: ['A node for every code module: nobody read the tree.'],
        positive: ['Two-level trees were read whole in a sitting.'],
        negative: ['Rule lists with no story: readers found no logic.'],
      },
    },
    row('overrun', 'Overrun signals a wrong design', 'design', 'core', 'watch', "'budget-monitor' under it: T2 is past its estimate", 'A budget is an estimate, not a limit.'),
    row('budget-monitor', 'Budget monitor', 'component', 'overrun', 'watch', 'T2 is past its estimate', 'A task cannot start without a budget.'),
    row('agent-integration', 'Agent integration', 'component', 'core', 'idle', 'no work yet under this version', 'It never calls a model.'),
  ],
  tasks: [
    { id: 'T1', title: 'Node files', parent: 'spec-graph', status: 'done', check: 'c', budget: { patches: 5 }, actual: { trials: 0, patches: 4, minutes: 3 }, result: 'ok' },
    { id: 'T2', title: 'Count patches', parent: 'budget-monitor', status: 'active', check: 'c', budget: { patches: 5 }, actual: { trials: 0, patches: 7, minutes: 9 }, result: null },
    { id: 'T3', title: 'Draw the pane', parent: 'agent-integration', status: 'planned', check: 'c', budget: {}, actual: { trials: 0, patches: 0, minutes: 0 }, result: null },
  ],
}

test('a view goes one level down: a design with what carries it out, then a component with all of its work', async ($, on) => {
  const seen = standIn(on, fromRepo(NESTED))

  await $.command.run(OPEN)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...PANE, surface })

    await home(ui)

    const isBoxes = surface === 'terminal' // elsewhere the tree is a picture
    let said = wordsOf(await ui.drawn())

    // The whole tree goes one level down and no further: the core across the top, a box for
    // each of its two designs, and a dashed box, apart, for the component the designs share.
    if (isBoxes) {
      expect(boxesOf(await ui.drawn())).toEqual([
        { edge: 'round', name: '' },
        { edge: 'round', name: 'People hold the spec, not the code' },
        { edge: 'round', name: 'Overrun signals a wrong design' },
        { edge: 'dashed', name: 'Agent integration' },
      ])
    } else {
      expect(pictureOf(await ui.drawn())?.match(/<rect class="cd cmp[^>]*stroke-dasharray=/g)?.length).toBe(1)
    }
    // What carries a design out is not drawn here and not counted: only where work is going on below.
    // Nothing is proposed in the tree: what a design lacks is not thought up ahead of time.
    for (const line of [/^1 in progress$/m, /^[Cc]omponents shared by the designs$/m, /^planned$/m]) {
      expect(said).toMatch(line)
    }
    expect(surface === 'terminal' ? said : said.replace(/\.[a-z]+\{[^}]*\}/g, '')).not.toMatch(NOISE)
    expect(said).not.toMatch(/proposed|Change digest/)
    for (const below of ['design-spec-graph', 'design-budget-monitor']) {
      expect(await ui.find({ key: below })).toBeUndefined()
    }

    // Named apart: the component that has the trouble, not the design or the core flagged with it.
    expect(await ui.find({ type: 'Text', text: /watch: "Count patches" is past its estimate/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Component of "Overrun signals a wrong design"/ })).toBeDefined()

    // One level in, by a press on the design's name: the design across the top, and its
    // component in a dashed box under it, with its open work named and nothing listed below.
    await ui.press({ key: 'design-overrun' })
    said = wordsOf(await ui.drawn())
    if (isBoxes) {
      expect(boxesOf(await ui.drawn())).toEqual([
        { edge: 'round', name: '' },
        { edge: 'dashed', name: 'Budget monitor' },
      ])
    }
    for (const line of [/^design · ! watch$/m, /^(● )?Count patches$/m, /^7\/5 patches$/m]) {
      expect(said).toMatch(line)
    }
    expect(said).not.toContain('In progress · 1') // the groups are the component's own level
    await home(ui)

    // A design says which components carry it out, and has one button that starts a
    // proposal; a shared component says that it is shared.
    await ui.press({ key: 'design-hold' })
    expect(wordsOf(await ui.drawn())).toMatch(/Carried out by:?\s+Spec graph/)
    expect((await ui.find({ key: 'propose-hold' }))?.text).toBe('+ Propose a component')
    expect(await ui.find({ key: 'take-hold-0' })).toBeUndefined()
    await home(ui)
    expect(await ui.find({ key: 'propose-core' })).toBeUndefined() // only under a design
    await ui.press({ key: 'design-agent-integration' })
    expect(await ui.find({ type: 'Text', text: /Component, shared by the designs/ })).toBeDefined()
    await home(ui)
    await ui.unmount()
  }

  // Zooming in: one design, then one of its components, and back out.
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  // The pane's words as running text, with the keys of what can be pressed among them.
  const words = async (): Promise<string> => `${flat(await ui.drawn())} ${JSON.stringify(await ui.drawn())}`

  // With the whole tree in view the words under it tell the top level and only that: the
  // core's story, what is one level down, its own rules. The node in trouble is named apart.
  let told = await words()

  for (const part of ['Motivation', 'Nobody can read what agents write.', 'Challenge', 'Insight', 'Hold a thin spec.']) {
    expect(told).toContain(part)
  }
  for (const named of ['Designs', 'design-hold', 'design-overrun', 'Shared components', 'design-agent-integration']) {
    expect(told).toContain(named) // what is one level down, by name, under the picture
  }
  expect(told).toContain('Needs you')
  expect(told).not.toContain('The spec is small enough to read whole.') // a rule of the level below

  await ui.press({ key: 'design-hold' })

  // Zoomed in: under the picture what carries the design out, by name; then the words tell
  // that level, in the order of a story: why it is needed, what makes it hard, how it is
  // done; then the rules of its level.
  // The level is told a sentence a part, with its rules counted, until all of it is asked for.
  told = await words()
  expect(told).toContain('Agents write faster than anyone can read.')
  expect(told).not.toContain('So the person is the bottleneck.') // the second sentence waits for Show all
  expect(told).not.toContain('The spec is small enough to read whole.') // its rule is counted, not told
  expect((await ui.find({ key: 'more-rules' }))?.text).toBe('▸ 1 rule')
  // Each part opens on its own. The motivation has a second sentence; a press tells it and
  // leaves the rules folded. A part that is one sentence has nothing to press.
  expect((await ui.find({ key: 'more-Motivation' }))?.text).toBe('▸ Motivation')
  expect(await ui.find({ key: 'more-Challenge' })).toBeUndefined()
  await ui.press({ key: 'more-Motivation' })
  expect((await ui.find({ key: 'more-Motivation' }))?.text).toBe('▾ Motivation')
  expect(await words()).toContain('So the person is the bottleneck.')
  expect(await words()).not.toContain('The spec is small enough to read whole.')
  await ui.press({ key: 'more-Motivation' }) // and folds back
  expect(await words()).not.toContain('So the person is the bottleneck.')
  // What the component under it has is the component's to tell: a level up it is not counted.
  expect(await words()).not.toMatch(NOISE)
  expect(labelsOf(await ui.drawn())).toEqual(['▸ Motivation', 'Challenge', 'Approach'])
  // A design is not a leaf: what it has is under it, so it has no line of its own to be empty.
  expect(await words()).not.toContain('Nothing shown yet')
  await tellAll(ui)
  expect((await ui.find({ key: 'more-rules' }))?.text).toBe('▾ 1 rule')
  told = await words()
  expect(told).toContain('So the person is the bottleneck.')
  const order = ['Carried out by', 'Motivation', 'Agents write faster than anyone can read.', 'Challenge', 'Approach', '1 rule', 'The spec is small enough to read whole.'].map(
    part => told.indexOf(part),
  )

  expect(order.every(at => at >= 0)).toBe(true)
  expect([...order].sort((a, b) => a - b)).toEqual(order)
  expect(told).not.toContain('Nobody can read what agents write.') // the core's story is the level above
  expect(told).not.toContain('A node is a short file.') // a rule of the component under it

  // The picture: the design across the top, with what kind of node it is, and under it
  // its component, dashed. Nothing of the other design or of the components the designs
  // share, and nothing proposed: only what is there is drawn.
  let said = wordsOf(await ui.drawn())

  expect(pictureOf(await ui.drawn())).toContain('<rect class="cd co hd sel"')
  expect(pictureOf(await ui.drawn())?.match(/<rect class="cd cmp/g)?.length).toBe(1)
  expect(said).toMatch(/^design$/m) // on track: what kind of node it is, and no word on how it stands
  expect(said).not.toMatch(/proposed|Proposed|Change digest|Question queue/)
  for (const gone of ['design-overrun', 'design-budget-monitor', 'design-agent-integration', 'take-hold-0']) {
    expect(await ui.find({ key: gone })).toBeUndefined()
  }
  expect(said).not.toMatch(/omponents shared by the designs/)
  // A view tells one level: the component is the next one down, and its finished work is neither listed nor counted.
  expect(said).not.toMatch(NOISE)
  expect(said).not.toContain('Node files')

  // The plus under a design is one button. Nothing is built or recorded: a press only
  // starts the sentence, and the person says what the component is.
  await ui.press({ key: 'propose-hold' })
  expect(seen.drafts).toEqual(['Propose a component under "People hold the spec, not the code": '])

  // One level further, by a press on the component's name: the component across the top,
  // with whose component it is. Its finished work is counted, and in place of a list of
  // tasks is its digest: what it has now, what was turned back, what runs came to.
  expect(await ui.find({ key: 'crumb-core' })).toBeDefined()
  await ui.press({ key: 'design-spec-graph' })
  said = wordsOf(await ui.drawn())
  expect(pictureOf(await ui.drawn())?.match(/<rect class="cd cmp/g)).toBeNull()
  expect(said).toMatch(/^component of “People hold the spec[^\n·]*$/m) // cut where the pane is narrow
  expect(said).not.toMatch(NOISE)
  for (const heading of [/^  Has now$/m, /^  As built$/m, /^  Turned back$/m, /^  Results$/m]) {
    expect(said).toMatch(heading)
  }
  // Each line with its mark: what it has, where what is built departs from the story and
  // why, what was turned back, and what runs came to.
  for (const line of [
    '∙ A node is one short file a person edits by hand.',
    '≠ Kept as plain files, with no database: a person has to be able to edit one (likely).',
    '↩ A node for every code module: nobody read the tree.',
    '+ Two-level trees were read whole in a sitting.',
    '− Rule lists with no story: readers found no logic.',
  ]) {
    expect(flat(await ui.drawn())).toContain(line)
  }
  expect(said).not.toMatch(/Node files|Done · 1|\bT1\b/) // no task is listed, and none by its id
  // One column, in the order a leaf fills in: its story first, then what the work under it
  // came to. Each name sits in a column of one width, so what the parts say lines up.
  expect(labelsOf(await ui.drawn())).toEqual(['Motivation', 'Challenge', 'Approach', 'Has now', 'As built', 'Turned back', 'Results'])
  expect(said).not.toContain('Nothing shown yet') // it has something
  expect(await ui.find({ key: 'propose-spec-graph' })).toBeUndefined() // a component is not proposed under
  expect(await ui.find({ key: 'crumb-hold' })).toBeDefined()

  // And out again, a level at a time.
  await ui.press({ key: 'crumb-hold' })
  expect(await ui.find({ key: 'design-spec-graph' })).toBeDefined()
  await ui.press({ key: 'crumb-core' })
  expect(await ui.find({ key: 'design-overrun' })).toBeDefined()
  expect(await ui.find({ key: 'crumb-core' })).toBeUndefined()

  // A component with open work: its groups, each with its heading and count, and how it stands.
  await ui.press({ key: 'design-overrun' })
  await ui.press({ key: 'design-budget-monitor' })
  expect(await ui.find({ type: 'Text', text: /^● Count patches$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^watch: "Count patches" is past its estimate$/ })).toBeDefined()
  // A leaf with nothing in its digest: no work has shown its approach, and the pane says so.
  expect(labelsOf(await ui.drawn())).toEqual(['Has now'])
  expect(await ui.find({ type: 'Text', text: /^Nothing shown yet: the approach is a plan\.$/ })).toBeDefined()
  await home(ui)
  await ui.unmount()

  const widget = await $.ui.mount({
    ...PANE,
    props: { ...PANE.props, placement: 'widget' },
    surface: 'desktop',
  })

  expect((await widget.find({ type: 'Text', text: /designs/ }))?.text).toContain('2 designs · 1 open')
  await widget.unmount()
})

test("the pane shows no count of the whole spec, and a view's size only when it nears the cap", async ($, on) => {
  let data: AbsSnapshot = SNAPSHOT
  standIn(on, () => ({ exitCode: 0, stdout: JSON.stringify(data) }))
  await $.command.run(OPEN)

  const calm = await $.ui.mount({ ...PANE, surface: 'desktop' })

  expect(wordsOf(await calm.drawn())).toMatch(/^demo$/m) // the repository alone: nothing is near the cap
  expect(wordsOf(await calm.drawn())).not.toMatch(/abstraction|lines/)
  await calm.unmount()

  // The core and its two designs hold 130 of 150 lines: the view in sight is near the cap, so it says so.
  data = { ...SNAPSHOT, nodes: SNAPSHOT.nodes.map(n => ({ ...n, lines: n.id === 'core' ? 30 : 50 })) }
  await $.command.run(OPEN)
  const full = await $.ui.mount({ ...PANE, surface: 'desktop' })

  expect(wordsOf(await full.drawn())).toMatch(/^demo · this view 130\/150 lines$/m)
  await full.unmount()
})
