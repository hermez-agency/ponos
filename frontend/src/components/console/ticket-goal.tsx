import * as React from "react"
import { Target } from "lucide-react"
import { toast } from "sonner"
import { Link } from "react-resource-view"

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { api, why } from "@/lib/api"
import { patchTicket, useBoard } from "@/lib/board-store"
import { offeredTo } from "@/lib/goal-search"
import { useT } from "@/lib/i18n"
import type { Goal, Ticket } from "@/lib/types"
import { goalHref, goalsOnce } from "@/resources/goals"

/* The goal a ticket serves, under its title: the link to the goal's page, and
 * the choice of another. The goals are those of the Goals database, read once
 * for the whole console; a workspace without any draws nothing, and a ticket
 * that serves none draws only the choice. Offered are those still worked
 * toward, the ticket's project's first, and the one it serves even once it is
 * over (`offeredTo`). The choice is offered only where the board can point a
 * ticket at a goal — the server gives the goal choices then, as it does to the
 * New ticket form — or writing it would only fail. Written at once, and the
 * card is redrawn before the board is read again. */

const NONE = "none"

export function TicketGoal({ ticket }: { ticket: Ticket }) {
  const t = useT()
  const pointable = Boolean(useBoard().choices?.goal)
  const [goals, setGoals] = React.useState<Goal[]>([])
  React.useEffect(() => {
    let live = true
    goalsOnce()
      .then((every) => live && setGoals(every))
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [])
  if ((!pointable || !goals.length) && !ticket.goal_id) return null
  const offered = offeredTo(goals, ticket.project_id ?? "", ticket.goal_id ?? "")
  const choose = async (value: string) => {
    const goal = goals.find((one) => one.id === value)
    const before = { goal: ticket.goal, goal_id: ticket.goal_id }
    patchTicket(ticket.id, { goal: goal?.name ?? "", goal_id: goal?.id ?? "" })
    try {
      await api.setTicketGoal(ticket.id, goal?.id ?? "")
      void goalsOnce().catch(() => undefined)
    } catch (error) {
      patchTicket(ticket.id, before)
      toast.error(t("The goal could not be changed"), { description: why(error) })
    }
  }
  return (
    <span className="inline-flex max-w-full items-center gap-2" data-slot="ticket-goal-picker">
      {ticket.goal && ticket.goal_id ? (
        <Link
          to={goalHref(ticket.goal_id)}
          data-slot="ticket-goal"
          title={t("The goal this ticket serves")}
          className="hover:text-foreground inline-flex min-w-0 items-center gap-1.5 underline-offset-2 hover:underline"
        >
          <Target className="size-3.5 shrink-0" />
          <span className="truncate">{ticket.goal}</span>
        </Link>
      ) : null}
      {pointable ? (
        <Select value={ticket.goal_id || NONE} onValueChange={(value) => void choose(value === NONE ? "" : value)}>
          <SelectTrigger size="sm" className="h-6 w-auto gap-1 px-2 text-xs" aria-label={t("Change the goal")} data-slot="ticket-goal-select">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>{t("No goal")}</SelectItem>
            {offered.map((goal) => (
              <SelectItem key={goal.id} value={goal.id}>
                {goal.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
    </span>
  )
}
