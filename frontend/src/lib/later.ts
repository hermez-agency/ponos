/* When a ticket is to run, as the console offers to say it.
 *
 * The shortcuts of « Scheduled for » — in an hour, tonight, tomorrow morning,
 * the day after, next Monday — and the date and hour typed into the picker are
 * moments of the *browser's* timezone: the one the person choosing them lives
 * in. They leave as ISO 8601 with that zone's offset, so the runner, wherever
 * it runs, reads the same instant (`later.py` keeps an offset as written).
 *
 * Nothing imported, so that `node --test` reads it as it stands.
 */

export type Shortcut = "hour" | "tonight" | "tomorrow" | "after-tomorrow" | "monday"

/** The shortcuts in the order they are offered. */
export const SHORTCUTS: Shortcut[] = ["hour", "tonight", "tomorrow", "after-tomorrow", "monday"]

/** The hour a morning starts at, and an evening. */
const MORNING = 9
const EVENING = 18

const at = (day: Date, hour: number, days = 0) => {
  const moment = new Date(day)
  moment.setDate(moment.getDate() + days)
  moment.setHours(hour, 0, 0, 0)
  return moment
}

/** The moment a shortcut names, as of `now`; null for « tonight » once the evening has begun. */
export function shortcut(name: Shortcut, now: Date): Date | null {
  switch (name) {
    case "hour": {
      // To the minute: a date ticking in seconds reads like a timestamp, not a plan.
      const moment = new Date(now.getTime() + 3_600_000)
      moment.setSeconds(0, 0)
      return moment
    }
    case "tonight": {
      const tonight = at(now, EVENING)
      return tonight > now ? tonight : null
    }
    case "tomorrow":
      return at(now, MORNING, 1)
    case "after-tomorrow":
      return at(now, MORNING, 2)
    case "monday": {
      // The next one, never today: on a Monday, « next Monday » is a week away.
      const ahead = (8 - now.getDay()) % 7 || 7
      return at(now, MORNING, ahead)
    }
  }
}

const two = (value: number) => String(value).padStart(2, "0")

/** A moment as the API takes it: ISO 8601 to the minute, with the browser's offset — `2026-11-21T09:00+01:00`. */
export function isoWithOffset(moment: Date): string {
  const offset = -moment.getTimezoneOffset()
  const sign = offset >= 0 ? "+" : "-"
  const hours = Math.floor(Math.abs(offset) / 60)
  const minutes = Math.abs(offset) % 60
  return (
    `${moment.getFullYear()}-${two(moment.getMonth() + 1)}-${two(moment.getDate())}` +
    `T${two(moment.getHours())}:${two(moment.getMinutes())}${sign}${two(hours)}:${two(minutes)}`
  )
}

/** What an `<input type="datetime-local">` holds for a moment: its wall time here, "" for none. */
export function localInput(value: string): string {
  if (!value) return ""
  const moment = new Date(value)
  if (Number.isNaN(moment.getTime())) return ""
  return (
    `${moment.getFullYear()}-${two(moment.getMonth() + 1)}-${two(moment.getDate())}` +
    `T${two(moment.getHours())}:${two(moment.getMinutes())}`
  )
}

/** The moment such an input says, read in the browser's zone, with its offset; "" for nothing readable. */
export function fromLocalInput(text: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(text)
  if (!match) return ""
  const [, year, month, day, hour, minute] = match.map(Number)
  return isoWithOffset(new Date(year, month - 1, day, hour, minute))
}

/** Whether a ticket's date still holds it back: a moment to come. */
export function upcoming(value: string | undefined, now: number): boolean {
  const moment = Date.parse(value ?? "")
  return !Number.isNaN(moment) && moment > now
}
