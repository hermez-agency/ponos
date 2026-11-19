import * as React from "react"

import type { RobotState } from "@/components/console/robot"
import { useConsole, useStatus } from "@/hooks/use-console"
import { useBoard } from "@/lib/board-store"
import type { Ticket } from "@/lib/types"

/* What the runner is doing, as a face.
 *
 * Read off what the console already holds — the stream's connection, the
 * sessions the server says are running, the board, the runner's state — and
 * nothing asked of the server for it. Most of it is a state: a session is
 * running or it is not. Two of it are events, and the board only says them
 * by changing: a ticket that has just come back (its pull request opened, or
 * it reached review or done) makes the robot jump for a few seconds, and one
 * that has just fallen into blocked leaves it sad for a few minutes — long
 * enough to be seen by somebody who looks up, short enough not to mourn a
 * ticket forever. The first board a page reads is remembered, not reacted to:
 * a ticket blocked yesterday is not news.
 *
 * Read once, for the whole console, and handed down. One face shows it now —
 * the mark, in the menu's corner on a wide screen and in the bar on a phone:
 * the bar's end had a second one, and lost it for being one more thing in a
 * row that already says the stream, the version and the sync.
 */

/** How long a ticket that came back keeps the robot jumping. */
const CHEER = 5_000
/** How long a ticket that has just been blocked keeps it sad. */
const GRIEF = 3 * 60_000

const DELIVERED = new Set(["review", "validated", "done"])
const STUCK = new Set(["blocked", "failed"])

export interface Mood {
  state: RobotState
}

function useReadMood(): Mood {
  const { runner } = useConsole()
  const board = useBoard()
  const { connection, running } = useStatus()
  // The tickets as last seen, themselves: the board keeps a ticket that did not
  // change as the same object, so nothing is copied, and it is passed over at once.
  const seen = React.useRef<Map<string, Ticket> | null>(null)
  const [cheer, setCheer] = React.useState(0)
  const [grief, setGrief] = React.useState(0)
  const [now, setNow] = React.useState(() => Date.now())

  React.useEffect(() => {
    const before = seen.current
    const latest = new Map<string, Ticket>()
    for (const ticket of board.tickets) latest.set(ticket.id, ticket)
    seen.current = latest
    if (!before?.size) return
    let delivered = false
    let stuck = false
    for (const ticket of board.tickets) {
      const was = before.get(ticket.id)
      if (!was || was === ticket) continue
      if (was.column !== ticket.column && DELIVERED.has(ticket.column)) delivered = true
      if (!was.pull_request && ticket.pull_request) delivered = true
      if (was.column !== ticket.column && STUCK.has(ticket.column)) stuck = true
    }
    if (!delivered && !stuck) return
    const at = Date.now()
    setNow(at)
    if (delivered) setCheer(at + CHEER)
    if (stuck) setGrief(at + GRIEF)
  }, [board])

  // Back to what the runner is doing once the moment has passed.
  React.useEffect(() => {
    const pending = [cheer, grief].filter((until) => until > now)
    if (!pending.length) return
    const timer = setTimeout(() => setNow(Date.now()), Math.min(...pending) - now + 50)
    return () => clearTimeout(timer)
  }, [cheer, grief, now])

  if (connection === "reconnecting") return { state: "error" }
  if (connection === "connecting") return { state: "thinking" }
  if (cheer > now) return { state: "success" }
  if (runner && !runner.claude) return { state: "error" }
  if (grief > now) return { state: "error" }
  if (running.length) return { state: "working" }
  if (runner?.credits) return { state: "waiting" }
  if (runner?.running || board.tickets.some((ticket) => ticket.column === "running"))
    return { state: "thinking" }
  if (board.tickets.some((ticket) => ticket.column === "ready")) return { state: "idle" }
  return { state: "sleep" }
}

const MoodContext = React.createContext<Mood | null>(null)

export function useRunnerMood(): Mood {
  const mood = React.useContext(MoodContext)
  if (!mood) throw new Error("useRunnerMood outside its provider")
  return mood
}

export function RunnerMoodProvider({ children }: { children: React.ReactNode }) {
  const mood = useReadMood()
  return <MoodContext.Provider value={mood}>{children}</MoodContext.Provider>
}
