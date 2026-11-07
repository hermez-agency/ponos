/* What the settings page decides without a DOM: where a field's help is cut,
 * and which fields a search finds.
 *
 * Kept apart and importing nothing, like `composer.ts`, so `node --test` reads
 * it as it stands. The page hands in what it drew — the words already
 * translated — so a search for « jeton » finds the token on a console in
 * French, and a search for `notify.telegram.token` finds it in either language.
 */

/** One field, as the search reads it. */
export interface Searchable {
  /** The key in `config.toml`, or a secret's variable — found as typed. */
  name: string
  /** The label and the help, in the console's language and in English. */
  words: string[]
}

/** The same text with its case and its accents gone: « Réglages » is « reglages ». */
export function folded(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
}

/* The line under a label, and what goes behind its « ? ».
 *
 * The first sentence is the one that says what the setting does; what follows
 * is the detail — the floor, the exception, the variable that wins over it.
 * A sentence ends on a stop followed by a capital or a quote, so "e.g. `opus`"
 * and "github.com/settings" are not ends of anything. */
export function splitHelp(text: string): [string, string] {
  const match = /^(.*?[.!?…])\s+(?=[A-ZÀ-ÖØ-Þ“«])/s.exec(text)
  if (!match) return [text, ""]
  return [match[1], text.slice(match[0].length)]
}

/** How well one field answers a search: 0 is not at all. */
function score(item: Searchable, query: string): number {
  const name = item.name.toLowerCase()
  if (name === query) return 4
  if (name.includes(query)) return 3
  const [label, ...rest] = item.words.map(folded)
  if (label.includes(query)) return 2
  return rest.some((words) => words.includes(query)) ? 1 : 0
}

/** The fields a search finds, best first, and no more than `most`. */
export function search<T extends Searchable>(items: T[], typed: string, most = 8): T[] {
  const query = folded(typed.trim())
  if (query.length < 2) return []
  return items
    .map((item, index) => ({ item, index, score: score(item, query) }))
    .filter((found) => found.score > 0)
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .slice(0, most)
    .map((found) => found.item)
}
