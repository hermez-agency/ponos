/* A ticket's priority: a score from 0 to 100, the highest run first (see
 * `priority.py`). What the console decides about one without a DOM — what a
 * typed value is worth, and the colour a score is drawn in — so that
 * `node --test` reads it as it is: it imports nothing.
 *
 * The colour is a gradient rather than four tones, because a score is not
 * four levels: grey-blue towards 0, green at 25, yellow at 50, orange at 75,
 * red at 100, and every score between two of them a shade between the two.
 * The hue and the saturation only: how light, the badge says per theme. */

/** What an empty cell is worth, and what a ticket nobody ranked is given. */
export const DEFAULT_SCORE = 50

export const LOWEST_SCORE = 0
export const HIGHEST_SCORE = 100

/** The stops of the gradient: a score, and the hue and saturation it is drawn in. */
const STOPS: [number, number, number][] = [
  [0, 215, 22],
  [25, 142, 58],
  [50, 48, 92],
  [75, 27, 92],
  [100, 0, 78],
]

/** The hue (degrees) and saturation (percent) a score is drawn in. */
export function scoreTone(score: number): { hue: number; saturation: number } {
  const at = Math.min(Math.max(Number.isFinite(score) ? score : DEFAULT_SCORE, LOWEST_SCORE), HIGHEST_SCORE)
  for (let index = 1; index < STOPS.length; index++) {
    const [to, hue, saturation] = STOPS[index]
    if (at > to) continue
    const [from, fromHue, fromSaturation] = STOPS[index - 1]
    const share = (at - from) / (to - from)
    return {
      hue: Math.round(fromHue + (hue - fromHue) * share),
      saturation: Math.round(fromSaturation + (saturation - fromSaturation) * share),
    }
  }
  const [, hue, saturation] = STOPS[STOPS.length - 1]
  return { hue, saturation }
}

/** A score as somebody typed it: the whole number, `null` for nothing typed,
 * `undefined` for what is not a score from 0 to 100 — which the form refuses
 * rather than round into one. */
export function readScore(value: unknown): number | null | undefined {
  if (value === null || value === undefined) return null
  const text = String(value).trim()
  if (!text) return null
  if (!/^\d+([.,]\d+)?$/.test(text)) return undefined
  const number = Math.round(Number(text.replace(",", ".")))
  return number >= LOWEST_SCORE && number <= HIGHEST_SCORE ? number : undefined
}

/* The mark a card of the board wears for its priority: a thin bar along its
 * left edge rather than a badge, since a badge read as loud as the title, and
 * the red end of the gradient was the red of a failed CI. A single hue — the
 * console's orange — from no colour at all at 0 to its full strength at 100,
 * the strength rising with the score: neutral for what can wait, orange for
 * the urgent, and red left to the errors. The lightness is the theme's. */
export const MARK_HUE = 28

/** How strong the mark of a score is: its saturation (percent) and opacity (0 to 1). */
export function scoreMark(score: number): { saturation: number; opacity: number } {
  const at = Math.min(Math.max(Number.isFinite(score) ? score : DEFAULT_SCORE, LOWEST_SCORE), HIGHEST_SCORE)
  const share = at / HIGHEST_SCORE
  return {
    saturation: Math.round(92 * share),
    opacity: Math.round((0.35 + 0.65 * share) * 100) / 100,
  }
}
