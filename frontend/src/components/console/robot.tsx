// Registers <ponos-robot>: the very module the landing page loads.
import "@mascot/ponos-robot.js"
import type { STATES } from "@mascot/ponos-robot.js"

import { useShownTheme } from "@/hooks/use-theme"
import type { ColumnKey } from "@/lib/types"

/* Ponos, the mascot, as the console draws it.
 *
 * The drawing is not here: it is `docs/mascot/ponos-robot.js`, a Web
 * Component in vanilla JavaScript because the landing page has no build step,
 * and bundled into the console as it stands. What this adds is what a page of
 * React needs around it — the theme the console is in rather than the one the
 * system prefers, and nothing for a screen reader to trip over.
 *
 * Every robot here is decoration. What it means is always said beside it in
 * words — a column's name, a sentence in the bar — so it is hidden from
 * assistive technology rather than labelled twice.
 */

export type RobotState = keyof typeof STATES

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "ponos-robot": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
        state?: string
        theme?: string
        size?: number
        still?: string
      }
    }
  }
}

export function Robot({
  state,
  size,
  still = false,
  className,
}: {
  state: RobotState
  /** In pixels; without it the robot takes the width of its container. */
  size?: number
  /** The pose, and no movement: for a robot among many that is not doing anything. */
  still?: boolean
  className?: string
}) {
  const theme = useShownTheme()
  return (
    <ponos-robot
      aria-hidden="true"
      state={state}
      theme={theme}
      size={size}
      still={still ? "" : undefined}
      className={className}
    />
  )
}

/* What a ticket's robot does, by the column it is in.
 *
 * Only a ticket in progress moves: a board is a hundred robots, and a hundred
 * robots bobbing is a page nobody can read — the one card whose session is
 * typing is the one that should catch the eye. The others hold the pose of
 * their column, which says as much and costs nothing. */
export const MOOD: Record<ColumnKey, RobotState> = {
  draft: "sleep",
  ready: "idle",
  running: "working",
  review: "waiting",
  validated: "waiting",
  blocked: "error",
  paused: "sleep",
  failed: "error",
  done: "success",
  cancelled: "sleep",
}

export function TicketRobot({
  column,
  size,
  className,
}: {
  column: string
  size?: number
  className?: string
}) {
  return (
    <Robot
      state={MOOD[column as ColumnKey] ?? "sleep"}
      still={column !== "running"}
      size={size}
      className={className}
    />
  )
}
