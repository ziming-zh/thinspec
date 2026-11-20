// What `thinspec state --json` prints, as far as the pane reads it.

export type AbsUsage = { trials?: number; lines?: number; patches?: number; minutes?: number }

export type AbsTask = {
  id: string
  title: string
  parent: string
  status: string
  check: string
  budget: AbsUsage
  /** `lines` is absent from a thinspec command older than budgets in lines. */
  actual: { trials: number; patches: number; minutes: number; lines?: number }
  result: string | null
}

export type AbsNode = {
  id: string
  title: string
  kind: string
  parent: string | null
  version: number
  summary: string
  invariants: string[]
  bans: string[]
  /** Non-empty lines of the node's file: what a person reads. Absent from an older thinspec command. */
  lines?: number
  /** What a person reads in place of the node's tasks. Absent from an older thinspec command. */
  digest?: {
    features: string[]
    /** Where what is built departs from the node's story, and why. Absent from an older thinspec command. */
    as_built?: string[]
    reverts: string[]
    positive: string[]
    negative: string[]
  }
  health: { level: string; reason: string }
}

/** One agent session working in the project: who it is, its task, what it is doing. */
export type AbsSession = {
  id: string
  /** The agent and the start of the id, such as "codex 60b8". */
  name: string
  agent: string | null
  host: string | null
  dir: string | null
  /** On this machine. */
  here: boolean
  /** The session that asked for the state. */
  me: boolean
  /** The open task its latest work is on. */
  task: string | null
  /** "working", "waiting" (for its person) or "quiet". */
  state: string
  /** When it was last heard from, in local time. */
  since: string
}

export type AbsSnapshot = {
  repo: string
  size: { nodes: number; lines: number; cap: number }
  nodes: AbsNode[]
  tasks: AbsTask[]
  /** Absent from a thinspec command older than the sessions. */
  sessions?: AbsSession[]
}

declare module 'claude-code' {
  interface PluginState {
    thinspec: {
      snapshot: Shaped<AbsSnapshot | null>
      selected: string | null
      /** Why the last read of the state failed; null when it went well. */
      problem: string | null
      /** The quote a press last put in the prompt box, as written: the next press replaces it. */
      quoted: string | null
      /** The parts the person opened, each "<node>/<part>". */
      opened: string[]
    }
  }
}
