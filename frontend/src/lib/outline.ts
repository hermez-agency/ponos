/* A session read in its broad lines: what the agent said, each with the steps
 * that followed it folded under it.
 *
 * The journal of a session is two kinds of line in one list — a sentence, then
 * twelve `Bash`, an `Error`, three `Read`, a sentence — and read as it stands it
 * is the twelve `Bash` that take the screen. What somebody watching a ticket
 * wants is the sentences: they say what the agent is about, and the tool calls
 * after one are how it went about it. So each sentence heads a group, and the
 * calls up to the next sentence are that group's, to be opened when wanted.
 *
 * A group's key is where its first step stands in the run — the journal's
 * `position`, or the place in the stream where there is none — and not its
 * index on screen: older steps read on request are put *before* the ones held,
 * and a stream forgets its oldest, and either would otherwise move every key and
 * fold again whatever the reader had opened.
 *
 * This module imports nothing, so that `node --test` reads it as it stands,
 * like `composer.ts` and `thinking.ts`.
 */

export interface OutlineStep {
  label: string
  detail: string
  said?: boolean
  position?: number
  at?: string
}

export interface Line<S extends OutlineStep = OutlineStep> {
  /** Stable for as long as the run is read: see the module's docstring. */
  key: string
  /** What the agent said — absent for the steps it took before saying anything. */
  said?: S
  /** What it did after saying it, up to the next thing it said. */
  steps: S[]
  /** How many of those steps went wrong. */
  errors: number
  /** From what it said to what it said next — or to its last step — when the steps say when. */
  seconds?: number
}

const time = (at?: string): number | undefined => {
  if (!at) return undefined
  const value = Date.parse(at)
  return Number.isNaN(value) ? undefined : value
}

/**
 * The broad lines of a run's steps, oldest first.
 *
 * `offset` is where the first step given stands in the run, for steps that do
 * not carry their `position` — a stream that has forgotten its first hundred
 * passes 100.
 */
export function outline<S extends OutlineStep>(steps: readonly S[], offset = 0): Line<S>[] {
  const lines: Line<S>[] = []
  steps.forEach((step, index) => {
    const where = step.position ?? offset + index
    if (step.said) {
      lines.push({ key: `said-${where}`, said: step, steps: [], errors: 0 })
      return
    }
    let line = lines[lines.length - 1]
    if (!line) {
      line = { key: `lead-${where}`, steps: [], errors: 0 }
      lines.push(line)
    }
    line.steps.push(step)
    if (step.label === "Error") line.errors += 1
  })
  // A group lasts from its first step to the first step of the next one; the
  // last, to its own last step.
  lines.forEach((line, index) => {
    const first = line.said ?? line.steps[0]
    const next = lines[index + 1]
    const start = time(first?.at)
    const end = next ? time((next.said ?? next.steps[0])?.at) : time(line.steps[line.steps.length - 1]?.at ?? first?.at)
    if (start !== undefined && end !== undefined && end >= start) line.seconds = (end - start) / 1000
  })
  return lines
}

/** Which groups are open: all of them or none, and the ones the reader turned the other way. */
export interface Unfolded {
  all: boolean
  flipped: readonly string[]
}

export const FOLDED: Unfolded = { all: false, flipped: [] }

export const isOpen = (state: Unfolded, key: string): boolean => state.all !== state.flipped.includes(key)

/** One group opened or closed — the others left as they were, and so are the groups still to come. */
export function toggled(state: Unfolded, key: string): Unfolded {
  const flipped = state.flipped.includes(key)
    ? state.flipped.filter((item) => item !== key)
    : [...state.flipped, key]
  return { all: state.all, flipped }
}

/** Whether "unfold everything" is what the button would do. */
export const everythingOpen = (state: Unfolded): boolean => state.all && !state.flipped.length

/** A page of older steps put before the ones held, without a position held twice — the same page can arrive twice. */
export function prepended<S extends OutlineStep>(page: readonly S[], held: readonly S[]): S[] {
  const seen = new Set(held.map((step) => step.position).filter((position) => position !== undefined))
  const older = page.filter((step) => {
    if (step.position === undefined) return true
    if (seen.has(step.position)) return false
    seen.add(step.position)
    return true
  })
  return [...older, ...held]
}
