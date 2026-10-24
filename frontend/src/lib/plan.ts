/* A session's plan — the todo list its agent keeps — and how far along it is.
 *
 * A share of steps would be a guess: nobody knows how many tool calls a session
 * will make. The plan is what the agent does know, so the figure comes from it
 * alone, and a session without one has no figure at all.
 *
 *     npm test          (node --test, nothing to install)
 */

export type TaskStatus = "pending" | "in_progress" | "completed"

export interface Task {
  content: string
  active: string
  status: TaskStatus
}

export interface Advance {
  done: number
  total: number
  percent: number
  /** The task under way, in the agent's words — empty when none is. */
  current: string
}

const STATUSES: readonly string[] = ["pending", "in_progress", "completed"]

/** The tasks a `Plan` step carries in its detail; none when it is not one. */
export function readPlan(detail: string): Task[] {
  try {
    const parsed: unknown = JSON.parse(detail)
    if (!Array.isArray(parsed)) return []
    return parsed.flatMap((item): Task[] => {
      if (!item || typeof item.content !== "string" || !item.content) return []
      const status = STATUSES.includes(item.status) ? (item.status as TaskStatus) : "pending"
      return [{ content: item.content, active: String(item.active ?? ""), status }]
    })
  } catch {
    return []
  }
}

/** The plan as it stands in these steps: the last one the agent wrote. */
export function planOf(steps: { label: string; detail: string }[]): Task[] {
  const last = steps.findLast((step) => step.label === "Plan")
  return last ? readPlan(last.detail) : []
}

/** How far a plan is. Null without one: the bar then claims no length. */
export function advance(tasks: Task[]): Advance | null {
  if (!tasks.length) return null
  const done = tasks.filter((task) => task.status === "completed").length
  const under = tasks.find((task) => task.status === "in_progress")
  return {
    done,
    total: tasks.length,
    percent: Math.round((done / tasks.length) * 100),
    current: under ? under.active || under.content : "",
  }
}
