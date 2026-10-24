import * as React from "react"
import { Target } from "lucide-react"
import { toast } from "sonner"
import { Link } from "react-resource-view"

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { api, why } from "@/lib/api"
import { patchTicket, useBoard } from "@/lib/board-store"
import { offeredTo } from "@/lib/goal-search"
import { useT } from "@/lib/i18n"
import type { Ticket } from "@/lib/types"
import { goalHref } from "@/resources/goals"

/* The goal a ticket serves, under its title: the link to the goal's page, and
 * the choice of another. The goals offered are the board's own choices
 * (`Tickets._choices`), which the stream already carries — those still worked
 * toward, the ticket's project's first — and the one it serves even once it is
 * over, by the name its card wears: the window asks nothing of `/api/goals`,
 * whose counting it never needed. The choice is offered only where the board
 * can point a ticket at a goal — the server gives the goal choices then, as it
 * does to the New ticket form — or writing it would only fail. A board
 * offering none draws nothing, and a ticket that serves none draws only the
 * choice. Written at once, and the card is redrawn before the board is read
 * again. */

const NONE = "none"

export function TicketGoal({ ticket }: { ticket: Ticket }) {
  const t = useT()
  const choices = useBoard().choices?.goal
  const pointable = Boolean(choices)
  const offered = React.useMemo(
    () => offeredTo(choices ?? [], ticket.project_id ?? "", { id: ticket.goal_id ?? "", name: ticket.goal ?? "" }),
    [choices, ticket.project_id, ticket.goal_id, ticket.goal]
  )
  if (!offered.length) return null
  const choose = async (value: string) => {
    const goal = offered.find((one) => one.id === value)
    const before = { goal: ticket.goal, goal_id: ticket.goal_id }
    patchTicket(ticket.id, { goal: goal?.name ?? "", goal_id: goal?.id ?? "" })
    try {
      await api.setTicketGoal(ticket.id, goal?.id ?? "")
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
