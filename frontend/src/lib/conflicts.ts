/* A card changed on the board meanwhile: said in the page's words, and said once.
 *
 * Why it was not overwritten reaches the page as the English the server wrote
 * in the sync journal — the runner's refusal in `reports.py`, the console's in
 * `web/board.py` — and that journal is read in English. So the page
 * recognises the sentence and says it again with the two statuses it names,
 * which the caller draws in the columns' own words: a toast that said
 * "the page says cancelled" beside a board headed « Abandonné » spoke two
 * languages at once. A test holds both templates to the Python
 * (`tests/test_release.py`).
 *
 * And a refusal stays on the card until somebody does something about it — a
 * ticket cancelled since is still wearing it — so a toast said each time the
 * board arrived was said on every load of every tab. What has been shown is
 * remembered, by ticket and by sentence: a refusal is news once.
 *
 * Imports nothing, like `composer.ts`, so that `node --test` reads it as it is.
 */

/** The runner's refusal, as `reports.py` journals it. */
const RUNNER =
  /^the runner would have written (.*), but the page says (.*) \(it said .* when the runner last read it\); not overwritten$/
/** The console's own, as `web/board.py` raises it — the move it wanted is on the card. */
const CONSOLE = /^The board already says (.*)$/
/** What the runner writes for a page whose status is empty. */
const NONE = "no status"

export const BY_RUNNER = "Ponos wanted to move it to {{wanted}}, but it is {{found}} on the board: left as it is."
export const BY_CONSOLE = "You moved it to {{wanted}}, but it is {{found}} on the board: left as it is."

export interface Conflict {
  /** The sentence to say it with, `wanted` and `found` to be put in. */
  key: typeof BY_RUNNER | typeof BY_CONSOLE
  /** The status the move was to — empty for none. */
  wanted: string
  /** The status the board has instead — empty for none. */
  found: string
}

interface Card {
  id: string
  sync?: string
  sync_error?: string
  sync_status?: string
}

const status = (said: string): string => (said === NONE ? "" : said)

/** Why a card was not moved, if it is a sentence this page knows. */
export function conflictOf(card: Pick<Card, "sync_error" | "sync_status">): Conflict | undefined {
  const said = card.sync_error ?? ""
  const runner = RUNNER.exec(said)
  if (runner) return { key: BY_RUNNER, wanted: status(runner[1]), found: status(runner[2]) }
  const console = CONSOLE.exec(said)
  if (console) return { key: BY_CONSOLE, wanted: card.sync_status ?? "", found: console[1] }
  return undefined
}

/** What a refusal is remembered by: a new one on the same ticket is another. */
const keyOf = (card: Card): string => `${card.id}\n${card.sync_error ?? ""}`

/** The board's conflicts not shown yet, and what to remember after showing them.
 *
 * `kept` is every conflict on the board now — those settled since are let go,
 * so that the same refusal made again later is news again. */
export function unshown<T extends Card>(cards: readonly T[], shown: readonly string[]): { fresh: T[]; kept: string[] } {
  const seen = new Set(shown)
  const conflicting = cards.filter((card) => card.sync === "conflict")
  return {
    fresh: conflicting.filter((card) => !seen.has(keyOf(card))),
    kept: conflicting.map(keyOf),
  }
}
