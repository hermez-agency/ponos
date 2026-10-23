/* When a schedule fires, worked out the way the runner works it out.
 *
 * `schedules.next_occurrence` in the core is the calendar: four cadences, and
 * the first moment strictly after the one it is handed, in wall-clock hours of
 * the machine's timezone. The runner only ever stores the *next* one, so a
 * calendar that wants the ones after it has to walk the same rule — and this is
 * that walk, kept free of any import so `node --test` reads it as it is.
 *
 * Hours are wall-clock hours of the runner's zone, not of the browser's: 09:00
 * is nine in Paris for a console opened from anywhere, and it stays nine on
 * either side of the change of hour. Everything is therefore done on "wall
 * time" (the clock on the wall, as if it were UTC) and turned back into an
 * instant by the zone's rules — which is also where the two odd cases of a
 * clock change are settled the way the runner settles them: a wall time that
 * happens twice is its first pass, and one that never happens lands after the
 * jump.
 */

const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
// "09:00", "9h30", "9" — the same shapes `_CLOCK` accepts.
const CLOCK = /^(\d{1,2})\s*(?:[:hH]\s*(\d{1,2})?)?$/

const HOUR = 3_600_000
const DAY = 24 * HOUR

export interface Rule {
  cadence: string
  at: string
  day: string
}

const formatters = new Map<string, Intl.DateTimeFormat>()

/** A zone Intl knows, or the browser's own when it was not given one it knows. */
export function zoneOf(name: string | undefined): string {
  const fallback = Intl.DateTimeFormat().resolvedOptions().timeZone
  if (!name) return fallback
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: name })
    return name
  } catch {
    return fallback
  }
}

function formatterFor(zone: string): Intl.DateTimeFormat {
  let known = formatters.get(zone)
  if (!known) {
    known = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      hourCycle: "h23",
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
      second: "numeric",
    })
    formatters.set(zone, known)
  }
  return known
}

/** The clock on the wall in `zone` at this instant, written as if it were UTC. */
export function wallOf(instant: number, zone: string): number {
  const seconds = Math.floor(instant / 1000) * 1000
  const part: Record<string, number> = {}
  for (const { type, value } of formatterFor(zone).formatToParts(seconds)) {
    if (type !== "literal") part[type] = Number(value)
  }
  return Date.UTC(part.year, part.month - 1, part.day, part.hour, part.minute, part.second) + (instant - seconds)
}

const offsetAt = (instant: number, zone: string) => wallOf(instant, zone) - instant

/** The instant a wall time is read at in `zone`: the earlier one when it happens twice, after the jump when it never does. */
export function instantOf(wall: number, zone: string): number {
  const before = offsetAt(wall - DAY, zone)
  const after = offsetAt(wall + DAY, zone)
  const valid = [...new Set([before, after])].map((offset) => wall - offset).filter((instant) => offsetAt(instant, zone) === wall - instant)
  if (valid.length) return Math.min(...valid)
  return wall - before
}

function clock(at: string): [number, number] | null {
  const text = at.trim()
  if (!text) return [0, 0]
  const match = CLOCK.exec(text)
  if (!match) return null
  const hour = Number(match[1])
  const minute = Number(match[2] ?? 0)
  return hour < 24 && minute < 60 ? [hour, minute] : null
}

/** Monday → 0, “Mon” too; null when it names no day. */
function weekday(day: string): number | null {
  const text = day.trim().toLowerCase()
  if (!text) return null
  const index = WEEKDAYS.findIndex((name) => name.startsWith(text))
  return index < 0 ? null : index
}

/** "1".."31", nothing said meaning the first. */
function dayOfMonth(day: string): number | null {
  const text = day.trim()
  if (!text) return 1
  return /^\d+$/.test(text) && Number(text) >= 1 && Number(text) <= 31 ? Number(text) : null
}

function inMonth(year: number, month: number, day: number, hour: number, minute: number): number {
  const last = new Date(Date.UTC(year, month + 1, 0)).getUTCDate()
  return Date.UTC(year, month, Math.min(day, last), hour, minute)
}

/** The first moment the rule falls on strictly after `after` (ms), or null for a rule nobody can act on. */
export function nextAfter(rule: Rule, after: number, zone: string): number | null {
  const at = clock(rule.at)
  if (!at) return null
  const [hour, minute] = at
  const base = wallOf(after, zone)
  const day = new Date(base)
  const startOfDay = Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate())
  const name = rule.cadence.trim().toLowerCase()
  let moment: number

  if (name === "hourly") {
    moment = startOfDay + day.getUTCHours() * HOUR + minute * 60_000
    if (moment <= base) moment += HOUR
  } else if (name === "daily") {
    moment = startOfDay + hour * HOUR + minute * 60_000
    if (moment <= base) moment += DAY
  } else if (name === "weekly") {
    const today = (day.getUTCDay() + 6) % 7
    const wanted = rule.day.trim() ? weekday(rule.day) : today
    if (wanted === null) return null
    moment = startOfDay + hour * HOUR + minute * 60_000 + ((wanted - today + 7) % 7) * DAY
    if (moment <= base) moment += 7 * DAY
  } else if (name === "monthly") {
    const wanted = dayOfMonth(rule.day)
    if (wanted === null) return null
    const year = day.getUTCFullYear()
    const month = day.getUTCMonth()
    moment = inMonth(year, month, wanted, hour, minute)
    if (moment <= base) moment = inMonth(year, month + 1, wanted, hour, minute)
  } else {
    return null
  }
  return instantOf(moment, zone)
}

/** The most occurrences one schedule is walked through: an hourly one over a year is 8,760 of them. */
const LIMIT = 20_000

/** The occurrences in [from, to], the first one being `first` when the server said it, else the first after `from`. */
export function occurrences(rule: Rule, first: number | null, from: number, to: number, zone: string): number[] {
  const found: number[] = []
  let current = first ?? nextAfter(rule, from - 1, zone)
  while (current !== null && current <= to && found.length < LIMIT) {
    if (current >= from) found.push(current)
    const following = nextAfter(rule, current, zone)
    if (following === null || following <= current) break
    current = following
  }
  return found
}

/* -- what the calendar draws ----------------------------------------------- */

/** The few fields of a schedule the calendar reads. */
export interface Row extends Rule {
  id: string
  active: boolean
  problem: string
  next: string
  last: string
}

/** One thing on the calendar: a launch, or the day's launches of one schedule folded into one. */
export interface Entry {
  /** Unique across the calendar: the schedule and the moment it is drawn at. */
  key: string
  schedule: string
  /** Where it is drawn: the first of its launches. */
  start: number
  /** Every launch it stands for, earliest first. */
  times: number[]
  /** A launch that has happened (`Last`) or one that is due. */
  kind: "past" | "upcoming"
}

/** From this many launches a day, one schedule is drawn once: an hourly one would otherwise bury the day. */
export const FOLD_FROM = 4

/** How far ahead the calendar is laid out, in days. A month away is a click away; two years is not. */
export const HORIZON = 366

const dayKey = (instant: number, zone: string) => {
  const wall = new Date(wallOf(instant, zone))
  return `${wall.getUTCFullYear()}-${wall.getUTCMonth()}-${wall.getUTCDate()}`
}

/** The launches to come, a day's worth of one schedule folded into one event from `FOLD_FROM` of them. */
function folded(schedule: string, instants: number[], cut: string): Entry[] {
  const byDay = new Map<string, number[]>()
  for (const instant of instants) {
    const key = dayKey(instant, cut)
    byDay.set(key, [...(byDay.get(key) ?? []), instant])
  }
  const result: Entry[] = []
  for (const times of byDay.values()) {
    const groups = times.length >= FOLD_FROM ? [times] : times.map((instant) => [instant])
    for (const group of groups) {
      result.push({ key: `${schedule}@${group[0]}`, schedule, start: group[0], times: group, kind: "upcoming" })
    }
  }
  return result
}

/** What the search for ideas draws: its passes, which the server walked since a cron line or an interval is not a cadence, and the last one. */
export const IDEAS_PASS = "ideas-pass"

export function listed(upcoming: string[], last: string, days?: string): Entry[] {
  const result = folded(IDEAS_PASS, upcoming.map((instant) => Date.parse(instant)).filter((instant) => !Number.isNaN(instant)), zoneOf(days))
  const done = Date.parse(last)
  if (!Number.isNaN(done)) {
    result.push({ key: `${IDEAS_PASS}@past@${done}`, schedule: IDEAS_PASS, start: done, times: [done], kind: "past" })
  }
  return result.sort((a, b) => a.start - b.start)
}

/**
 * Everything the calendar draws, for these schedules, as of `now`.
 *
 * The future of a schedule that is on and readable, starting with exactly the
 * moment the list calls "Next" (the server's `next`, which is now when it is
 * due) — and nothing for one that is off or unreadable, since nothing is born
 * from it. The past is `Last`, the one launch the board remembers, whatever the
 * schedule is doing now. `days` is the zone the days are cut in: the browser's,
 * since that is what the calendar's cells are.
 */
export function entries(rows: Row[], now: number, zone: string, days?: string): Entry[] {
  const cut = zoneOf(days)
  const result: Entry[] = []
  for (const row of rows) {
    const last = Date.parse(row.last)
    if (!Number.isNaN(last)) {
      result.push({ key: `${row.id}@past@${last}`, schedule: row.id, start: last, times: [last], kind: "past" })
    }
    if (!row.active || row.problem) continue
    const next = Date.parse(row.next)
    const first = Number.isNaN(next) ? null : next
    const upcoming = occurrences(row, first, now, now + HORIZON * DAY, zone)
    result.push(...folded(row.id, upcoming, cut))
  }
  return result.sort((a, b) => a.start - b.start)
}
