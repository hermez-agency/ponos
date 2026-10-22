/* Numbers, amounts and plurals, in the language the console is in.
 *
 * A number is not a sentence either: no dictionary can say that 2734.75 is
 * « 2 734,75 $ » in French and "$2,734.75" in English, or that French has one
 * ticket at 0 and English has none. `Intl` knows both, so the console asks it
 * rather than writing `toFixed(2)` in a few places and "ticket(s)" in all the
 * others — a "(s)" is a plural nobody bothered to choose.
 *
 * The locale is a module-level value, set by `i18n.ts` whenever the language
 * changes, so that a caller says `money(n)` and nothing more. This module
 * imports nothing, so that `node --test` reads it as it stands, like
 * `composer.ts`; what `count` returns is the English sentence and its
 * parameters, translated where it is drawn, like `thinking.ts`.
 */

let locale = "en-GB"

/** Which locale numbers are written in: `fr-FR`, `en-GB`. */
export function setNumberLocale(next: string) {
  locale = next
}

/** A count, with the separator the language puts between thousands. */
export function number(value: number): string {
  return new Intl.NumberFormat(locale).format(value)
}

/** Dollars — what the sessions cost — written where the language writes them.
 *  `digits` is how far past the cents it may go: 0 drops them, for a figure big
 *  enough not to need them, and 4 keeps what a single chat turn costs. */
export function money(value: number, digits = 2): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    // "$", not "US$": the console has only ever counted in one currency.
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: Math.min(2, digits),
    maximumFractionDigits: digits,
  }).format(value)
}

/** A size, the way the runner's `doctor` says it — powers of 1000, one decimal
 *  under ten — in the units the language writes: "4.2 GB" in English, « 4,2 Go »
 *  in French. Bytes alone are spelled out: `Intl` has "12 byte" for the short
 *  form, and nobody writes that. */
export function bytes(size: number): string {
  const units = ["byte", "kilobyte", "megabyte", "gigabyte"]
  let unit = 0
  while (size >= 1000 && unit < units.length - 1) {
    size /= 1000
    unit += 1
  }
  const digits = unit === 0 || size >= 10 ? 0 : 1
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: units[unit],
    unitDisplay: unit === 0 ? "long" : "short",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(size)
}

export interface Counted {
  /** The sentence, in English: it is also the key it is translated by. */
  key: string
  params: { count: string }
}

/** The sentence about `value` things, in the form the language gives that
 *  many: `one` for 1 in English but for 0 and 1 in French, `other` otherwise.
 *  The count is already written as a number, so a 0 is "0" — never the empty
 *  parameter react-mini-i18n would leave as `{{count}}`. */
export function count(value: number, one: string, other: string): Counted {
  const form = new Intl.PluralRules(locale).select(value)
  return { key: form === "one" ? one : other, params: { count: number(value) } }
}
