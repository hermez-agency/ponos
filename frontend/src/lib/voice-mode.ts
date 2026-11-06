/* The decisions of the voice mode that need no browser: when a sentence is
 * over, when somebody talks over the voice, and what is left to say of a
 * reply. Imports nothing, so `node --test` reads it as it is.
 *
 * The end of a sentence is found on the microphone's level, the same peak the
 * recording meter draws (0 to 1, sampled every 80 ms): loud enough for long
 * enough is speech, and quiet for long enough after speech is the end. No model,
 * no worker — a room with a fan running will want `QUIET_MS` and `SPEECH_LEVEL`
 * moved, which is why they are named here and not buried in a hook.
 */

/** Above this peak the microphone hears somebody. */
export const SPEECH_LEVEL = 0.18
/** Speech has to last this long before it counts: a door slamming is not a sentence. */
export const MIN_SPEECH_MS = 300
/** This much silence after speech ends the sentence. */
export const QUIET_MS = 1400
/** A sentence that never stops is cut here and sent as it is. */
export const LONGEST_MS = 60_000

/* While the voice speaks, its own sound reaches the microphone through the
 * loudspeakers: only a louder, longer interruption counts as somebody talking. */
export const BARGE_LEVEL = 0.4
export const BARGE_MS = 350

export type Mode = "off" | "listening" | "thinking" | "speaking"

export interface Gate {
  /** Time spent above the speech level, in total. */
  loud: number
  /** Time since the last loud sample, once speech was heard. */
  quiet: number
  /** Time since the gate was opened. */
  elapsed: number
  heard: boolean
}

export const opened = (): Gate => ({ loud: 0, quiet: 0, elapsed: 0, heard: false })

/** One sample of the microphone, `ms` after the previous one. */
export function advance(gate: Gate, level: number, ms: number): Gate {
  const elapsed = gate.elapsed + ms
  if (level >= SPEECH_LEVEL) {
    const loud = gate.loud + ms
    return { loud, quiet: 0, elapsed, heard: gate.heard || loud >= MIN_SPEECH_MS }
  }
  return { loud: gate.loud, quiet: gate.heard ? gate.quiet + ms : 0, elapsed, heard: gate.heard }
}

/** Whether the sentence is over: heard, then quiet — or simply too long. */
export const finished = (gate: Gate) => (gate.heard && gate.quiet >= QUIET_MS) || gate.elapsed >= LONGEST_MS

/** Somebody talking over the voice, as a count of the time spent loudly. */
export const interruption = (so_far: number, level: number, ms: number) =>
  level >= BARGE_LEVEL ? so_far + ms : 0

export const interrupts = (so_far: number) => so_far >= BARGE_MS

/** The sentences of a plan not said yet. */
export const unsaid = (planned: readonly string[], said: number) => planned.slice(said)

/** The words of a message, from its parts — what is read aloud, before the server cleans it. */
export function wordsOf(parts: ReadonlyArray<{ type: string; content?: unknown }>): string {
  return parts
    .filter((part) => part.type === "text" && typeof part.content === "string")
    .map((part) => part.content as string)
    .join("\n\n")
}

/** Whether a reply grew a sentence's worth since the plan was last asked for. */
export const mayHaveGrown = (before: string, now: string) =>
  now.length > before.length && /[.!?…:;\n]/.test(now.slice(before.length))
