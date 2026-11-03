import * as React from "react"

import { api } from "@/lib/api"
import { planOf, readPlan, type Task } from "@/lib/plan"
import type { Running, SessionsEvent, Step, StepEvent } from "@/lib/types"

/* The running sessions and their steps.
 *
 * What makes it more than a list is the catching up: a session this page did
 * not see start has its steps read back from its log, once, and the steps
 * the stream brings meanwhile are not lost to it. Its values are the console's
 * two fast contexts (`useStatus`, `useSteps`), built here once per change.
 */

/** How many steps a session's panel keeps before it starts forgetting. */
const KEPT = 200

export interface Session {
  source: string
  steps: Step[]
  /** How many steps the session has taken, the forgotten ones included. */
  count: number
  /** The agent's todo list as it stands; empty while it has not written one. */
  plan: Task[]
}

/** What the running sessions are doing. Changes with every step. */
export interface StepsValue {
  sessions: Session[]
  /** The steps of the open ticket's session, if it has one this console saw. */
  ticketSteps: Step[]
}

/** `openShort`: the open ticket's short name, whose steps stay after its run. */
export function useCatchUp(openShort: string) {
  const [running, setRunning] = React.useState<Running[]>([])
  const [steps, setSteps] = React.useState<Record<string, Step[]>>({})
  // Counted apart from the steps kept: a card says how far a run has come,
  // and the panel forgets all but its last two hundred.
  const [counts, setCounts] = React.useState<Record<string, number>>({})
  // Kept apart too: the plan was written once, a long way back, and is the
  // one thing the last two hundred steps must not push out.
  const [plans, setPlans] = React.useState<Record<string, Task[]>>({})
  // The logs whose steps were already asked for, so a list announced twice
  // does not read the same log twice.
  const asked = React.useRef(new Set<string>())

  /* A session this page did not see start — the page was reloaded, or opened
   * mid-run — has its steps read back from its log, once, rather than
   * starting blank and filling from wherever it happened to be. */
  const catchUp = React.useCallback((sessions: Running[]) => {
    setRunning(sessions)
    for (const session of sessions) {
      if (asked.current.has(session.log)) continue
      asked.current.add(session.log)
      // Another run of the same ticket: the last one's plan is not this one's.
      setPlans(({ [session.source]: _, ...others }) => others)
      void api
        .log(session.log)
        .then((payload) => {
          const read = payload.steps.slice(-KEPT)
          const plan = planOf(payload.steps)
          if (plan.length) setPlans((current) => ({ ...current, [session.source]: plan }))
          // Steps that arrived on the stream while the log was being read are
          // in the log too: whichever says more is the one kept.
          setSteps((current) => {
            const seen = current[session.source] ?? []
            return seen.length >= read.length ? current : { ...current, [session.source]: read }
          })
          setCounts((current) =>
            (current[session.source] ?? 0) >= payload.count
              ? current
              : { ...current, [session.source]: payload.count }
          )
        })
        .catch(() => {
          // A log that cannot be read leaves the session to fill from the
          // stream, as it did before there was anything to catch up with.
        })
    }
  }, [])

  const on = {
    // Which sessions are running: the server's word, not a count of the steps
    // this tab happened to see. A session that ended leaves the list here.
    sessions: (event: SessionsEvent) => catchUp(event.sessions ?? []),

    step: (event: StepEvent) => {
      const line: Step = { label: event.label, detail: event.detail, said: event.said }
      setSteps((current) => ({
        ...current,
        [event.source]: [...(current[event.source] ?? []), line].slice(-KEPT),
      }))
      setCounts((current) => ({ ...current, [event.source]: (current[event.source] ?? 0) + 1 }))
      if (event.label === "Plan") {
        const plan = readPlan(event.detail)
        if (plan.length) setPlans((current) => ({ ...current, [event.source]: plan }))
      }
    },
  }

  const live = React.useMemo<StepsValue>(
    () => ({
      sessions: running.map((session) => ({
        source: session.source,
        steps: steps[session.source] ?? [],
        count: counts[session.source] ?? steps[session.source]?.length ?? 0,
        plan: plans[session.source] ?? [],
      })),
      // Kept after the session ends: the open ticket's terminal shows how the
      // run it just finished went, until another ticket is opened.
      ticketSteps: openShort ? (steps[openShort] ?? []) : [],
    }),
    [running, steps, counts, plans, openShort]
  )

  return { running, live, catchUp, on }
}
