/* What a card in progress says when its session is not the whole story.
 *
 * A ticket in progress spends long stretches with no session at all: replayed
 * onto its base, its CI run here or waited for on GitHub, a session sent after
 * a red check. None of that writes a log, and the card, which reads the logs,
 * said « starting… » for an hour. The runner now writes down each phase and
 * when it began (`state.enter`); this turns it into the card's line — and keeps
 * « starting… » to the two minutes a launch really takes. It returns the
 * English sentence and its parameters, translated where it is drawn, and
 * imports nothing, so that `node --test` reads it as it stands.
 */

/** What the server sends: `phase` on a card in progress, null when the runner wrote none. */
export interface Phase {
  key: "starting" | "session" | "rebase" | "local-ci" | "checks" | "repair" | "resolve"
  detail: string
  since: string
}

export interface Said {
  key: string
  params: Record<string, string>
}

/** How long « starting… » may stand before the card says that nothing came. */
export const STARTING_SECONDS = 120

export interface Reading {
  /** The phase in words, or null for a plain session — its steps say it. */
  said: Said | null
  /** Seconds since it began. */
  seconds: number
  /** No session runs in it: the steps and the board's line belong to one that is over. */
  quiet: boolean
  /** Begun less than `STARTING_SECONDS` ago. */
  young: boolean
}

/** The number of a pull request, out of its address — "" for anything else. */
function numbered(url: string): string {
  return /\/pull\/(\d+)/.exec(url)?.[1] ?? ""
}

function words(phase: Phase): Said | null {
  const detail = phase.detail.trim()
  const number = numbered(detail)
  switch (phase.key) {
    case "rebase":
      return detail ? { key: "rebasing onto {{base}}", params: { base: detail } } : { key: "rebasing", params: {} }
    case "local-ci":
      return { key: "running the CI here", params: {} }
    case "checks":
      return number
        ? { key: "waiting for the CI of PR #{{number}}", params: { number } }
        : { key: "waiting for the CI of the pull request", params: {} }
    case "repair":
      return number
        ? { key: "fixing the CI of PR #{{number}}", params: { number } }
        : { key: "fixing the CI", params: {} }
    case "resolve":
      return detail
        ? { key: "resolving the conflicts with {{base}}", params: { base: detail } }
        : { key: "resolving the conflicts", params: {} }
    default:
      return null
  }
}

/** What a phase says at `now` (ms), or null when it cannot be read. */
export function reading(phase: Phase | null | undefined, now: number): Reading | null {
  if (!phase) return null
  const since = new Date(phase.since).getTime()
  if (Number.isNaN(since)) return null
  const seconds = Math.max(0, (now - since) / 1000)
  return {
    said: words(phase),
    seconds,
    quiet: phase.key === "rebase" || phase.key === "local-ci" || phase.key === "checks",
    young: seconds < STARTING_SECONDS,
  }
}
