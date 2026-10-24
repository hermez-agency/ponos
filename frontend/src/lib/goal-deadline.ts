/* Which goal comes first, and whether one is late, without a DOM.
 *
 * Kept apart from `goal-search.ts`, which the first load carries for the
 * filters: the order and the badge are only wanted by the cards, loaded when
 * the Goals page is opened, and the first load has no bytes to spare (see
 * `test_release.py`). The cards are drawn in the order of what is due, since
 * the query's is Notion's, which says nothing about which goal comes first.
 */

/** How many days a goal due this soon is said to be close: a week, the time to do something about it. */
export const SOON = 7

/** The day a due date names, "" for what is not one: Notion may give it a time, which says nothing more. */
function dayOf(due: string | undefined): string {
  return /^\d{4}-\d{2}-\d{2}/.exec(due ?? "")?.[0] ?? ""
}

/** The reader's day, as a due date writes it: the goal is late from the morning after, where they are. */
export function todayOf(now: Date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, "0")
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** Where a goal stands against its due date, for the badge beside it: late once
 * the day is past, "in n days" within `SOON` of it (0 is today), nothing
 * otherwise — nor for a goal without a date, or one no longer worked toward: a
 * goal met after its date is not late. */
export function deadlineOf(
  goal: { due?: string; active?: boolean },
  today: string
): { late: true } | { late: false; days: number } | null {
  const due = dayOf(goal.due)
  if (!due || !dayOf(today) || goal.active === false) return null
  const days = Math.round((Date.parse(`${due}T00:00:00Z`) - Date.parse(`${dayOf(today)}T00:00:00Z`)) / 86_400_000)
  if (Number.isNaN(days)) return null
  if (days < 0) return { late: true }
  return days <= SOON ? { late: false, days } : null
}

/** The goals in the order the list draws them: the soonest due first, those
 * without a date last, and among the same day the highest priority first —
 * a goal without one after those that have one; the rest in the order they came. */
export function byDeadline<Goal extends { due?: string; priority?: number | null }>(goals: Goal[]): Goal[] {
  const rank = (goal: Goal) => [dayOf(goal.due), goal.priority ?? -1] as const
  return [...goals].sort((a, b) => {
    const [dueA, scoreA] = rank(a)
    const [dueB, scoreB] = rank(b)
    if (dueA !== dueB) return !dueA ? 1 : !dueB ? -1 : dueA < dueB ? -1 : 1
    return scoreB - scoreA
  })
}
