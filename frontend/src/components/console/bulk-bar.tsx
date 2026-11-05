import * as React from "react"
import { Ban, Gauge, PauseCircle, Play, Target, X } from "lucide-react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { columnTitle } from "@/components/console/ticket-bits"
import { TicketEstimate } from "@/components/console/ticket-estimate"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { api } from "@/lib/api"
import { moveTicket, patchTicket, titleOf, useBoard } from "@/lib/board-store"
import { asideable, cancellable, costOf, launchable } from "@/lib/bulk"
import { counted, useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import { optimistic } from "@/lib/optimistic"
import { DEFAULT_SCORE, readScore } from "@/lib/priority"
import { clearSelection, useSelection } from "@/lib/selection-store"
import type { ColumnKey, Ticket } from "@/lib/types"

/* The bar the board's selection acts through — see `bulk.ts` for what each of
 * its gestures takes, and `selection-store.ts` for the selection itself.
 *
 * Drawn at the bottom of the screen, over the board, the way a phone draws the
 * actions on what was picked: the thumb is there, and the cards stay where
 * they were. On a phone it stands on the bottom bar, and the gestures other
 * than launching are their icons alone, so that the bar holds on one line. Fetched when a first card is picked: most visits to the board
 * select nothing, and its first load has a budget.
 *
 * The two gestures that cost or lose something ask first, once for the lot:
 * launching says how many sessions start and what they are likely to cost;
 * giving up says how many. Setting aside, ranking and pointing at a goal are
 * done at once, as on a card — each is undone the same way. Every gesture then
 * empties the selection: what was picked has been told what to do.
 */
export function BulkBar() {
  const t = useT()
  const board = useBoard()
  const selection = useSelection()
  const [launching, setLaunching] = React.useState(false)
  const [cancelling, setCancelling] = React.useState(false)
  const picked = React.useMemo(
    () => board.tickets.filter((ticket) => selection.has(ticket.id)),
    [board.tickets, selection]
  )
  const launched = picked.filter(launchable)
  const aside = picked.filter(asideable)
  const given = picked.filter(cancellable)
  const goals = board.choices?.goal

  // Escape lets the selection go — unless a window or a menu of the bar is
  // open, which Escape closes first.
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return
      if (document.querySelector("[role=dialog], [role=alertdialog], [role=menu]")) return
      clearSelection()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [])

  if (!picked.length) return null

  const named = (key: string) => columnTitle(key, board.columns.find((column) => column.key === key)?.name)

  /** Moved, each as its card would; `one` and `other` say how many did. */
  const move = (tickets: Ticket[], column: ColumnKey, one: string, other: string) => {
    let moved = 0
    for (const ticket of tickets)
      if (moveTicket(ticket.id, column, t("could not move “{{title}}”", { title: titleOf(ticket) }))) moved += 1
    if (moved) toast.success(counted(moved, one, other))
    clearSelection()
  }

  /* One write per ticket, all drawn at once; those refused go back as they
   * were, and one toast says how many — not one per ticket. */
  const write = (
    patch: Partial<Ticket>,
    send: (ticket: Ticket) => Promise<unknown>,
    failure: string,
    success: string
  ) => {
    const before = new Map(picked.map((ticket) => [ticket.id, ticket]))
    let refused: Ticket[] = []
    void optimistic({
      apply: () => picked.forEach((ticket) => patchTicket(ticket.id, patch)),
      request: async () => {
        const results = await Promise.allSettled(picked.map(send))
        refused = picked.filter((_, index) => results[index].status === "rejected")
        const first = results.find((result) => result.status === "rejected")
        if (first) throw (first as PromiseRejectedResult).reason
      },
      rollback: () =>
        refused.forEach((ticket) => {
          const was = before.get(ticket.id)
          if (was) patchTicket(ticket.id, Object.fromEntries(Object.keys(patch).map((key) => [key, was[key as keyof Ticket]])))
        }),
      failure,
      success: { title: success },
    })
    clearSelection()
  }

  const cost = costOf(launched)

  return (
    <div
      role="toolbar"
      aria-label={t("Selected tickets")}
      data-slot="bulk-bar"
      className="bg-popover text-popover-foreground fixed inset-x-0 bottom-[calc(var(--bottom-nav)+1rem+env(safe-area-inset-bottom))] z-40 mx-auto flex w-fit max-w-[calc(100vw-1rem)] flex-wrap items-center justify-center gap-1 sm:gap-1.5 rounded-2xl border p-2 shadow-lg"
    >
      <span className="px-2 text-sm font-medium tabular-nums" data-slot="bulk-count">
        <span className="max-sm:sr-only">
          {counted(picked.length, "{{count}} ticket selected", "{{count}} tickets selected")}
        </span>
        <span aria-hidden className="bg-primary/15 text-primary rounded-full px-2 py-0.5 sm:hidden">
          {picked.length}
        </span>
      </span>

      {launched.length ? (
        <Button size="sm" onClick={() => setLaunching(true)} data-slot="bulk-launch">
          <Play />
          {t("Make ready")}
          {launched.length !== picked.length ? <span className="tabular-nums opacity-75">{launched.length}</span> : null}
        </Button>
      ) : null}

      {aside.length ? (
        <Button
          variant="outline"
          size="sm"
          title={t("The runner no longer touches them, until they are made ready again.")}
          onClick={() => move(aside, "blocked", "{{count}} ticket set aside", "{{count}} tickets set aside")}
        >
          <PauseCircle />
          <span className="max-sm:sr-only">{t("Set aside")}</span>
          {aside.length !== picked.length ? <span className="tabular-nums opacity-75">{aside.length}</span> : null}
        </Button>
      ) : null}

      {board.priority ? (
        <PriorityPicker
          onPick={(score) =>
            write(
              { priority: score },
              (ticket) => api.setPriority(ticket.id, score),
              t("The priority could not be changed"),
              counted(picked.length, "{{count}} ticket ranked", "{{count}} tickets ranked")
            )
          }
        />
      ) : null}

      {goals ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm">
              <Target />
              <span className="max-sm:sr-only">{t("Goal")}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="center" side="top" className="max-h-72 overflow-y-auto">
            {goals.map((goal) => (
              <DropdownMenuItem
                key={goal.value}
                onSelect={() =>
                  write(
                    { goal: goal.label, goal_id: goal.value },
                    (ticket) => api.setTicketGoal(ticket.id, goal.value),
                    t("The goal could not be changed"),
                    counted(picked.length, "{{count}} ticket pointed at the goal", "{{count}} tickets pointed at the goal")
                  )
                }
              >
                {goal.label}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() =>
                write(
                  { goal: "", goal_id: "" },
                  (ticket) => api.setTicketGoal(ticket.id, ""),
                  t("The goal could not be changed"),
                  counted(picked.length, "{{count}} ticket serves no goal", "{{count}} tickets serve no goal")
                )
              }
            >
              {t("No goal")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}

      {board.cancel && given.length ? (
        <Button
          variant="outline"
          size="sm"
          className="text-destructive hover:text-destructive"
          onClick={() => setCancelling(true)}
        >
          <Ban />
          <span className="max-sm:sr-only">{t("Give up")}</span>
          {given.length !== picked.length ? <span className="tabular-nums opacity-75">{given.length}</span> : null}
        </Button>
      ) : null}

      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={t("Clear the selection")}
        title={t("Clear the selection")}
        onClick={clearSelection}
      >
        <X />
      </Button>

      <ConfirmDialog
        open={launching}
        onOpenChange={setLaunching}
        title={counted(launched.length, "Launch {{count}} ticket?", "Launch {{count}} tickets?")}
        description={t(
          "They go to {{column}} and the next passes start a session on each — sessions that are paid for.",
          { column: named("ready") }
        )}
        confirm={counted(launched.length, "Launch {{count}} ticket", "Launch {{count}} tickets")}
        onConfirm={() => move(launched, "ready", "{{count}} ticket launched", "{{count}} tickets launched")}
      >
        <div className="flex flex-col gap-2 text-sm" data-slot="bulk-cost">
          <p className="font-medium">
            {cost.estimated
              ? t("Estimated cost: ≈ {{cost}}, up to {{high}}", { cost: money(cost.cost), high: money(cost.high) })
              : t("No estimate yet: too few tickets like these have run.")}
          </p>
          {cost.estimated && cost.unknown ? (
            <p className="text-muted-foreground text-xs">
              {counted(
                cost.unknown,
                "{{count}} of them has no estimate and is not counted.",
                "{{count}} of them have no estimate and are not counted."
              )}
            </p>
          ) : null}
          <ul className="scroll-thin bg-muted/40 max-h-48 overflow-y-auto rounded-lg border px-3 py-2 text-xs">
            {launched.map((ticket) => (
              <li key={ticket.id} className="flex items-baseline justify-between gap-3 py-0.5">
                <span className="min-w-0 truncate">{titleOf(ticket)}</span>
                <TicketEstimate estimate={ticket.estimate} className="text-muted-foreground shrink-0 tabular-nums" />
              </li>
            ))}
          </ul>
        </div>
      </ConfirmDialog>

      <ConfirmDialog
        open={cancelling}
        onOpenChange={setCancelling}
        destructive
        title={counted(given.length, "Give up {{count}} ticket?", "Give up {{count}} tickets?")}
        description={t(
          "They go to {{column}}: the runner no longer touches them. Each one can be reopened from its card.",
          { column: named("cancelled") }
        )}
        confirm={counted(given.length, "Give up {{count}} ticket", "Give up {{count}} tickets")}
        onConfirm={() => move(given, "cancelled", "{{count}} ticket given up", "{{count}} tickets given up")}
      />
    </div>
  )
}

/** The score given to all of them: typed, or one of the four the old select had. */
function PriorityPicker({ onPick }: { onPick: (score: number) => void }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const [typed, setTyped] = React.useState("")
  const read = readScore(typed)
  const score = read === null ? DEFAULT_SCORE : read
  const give = (value: number) => {
    setOpen(false)
    setTyped("")
    onPick(value)
  }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm">
          <Gauge />
          <span className="max-sm:sr-only">{t("Priority")}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent side="top" className="flex w-64 flex-col gap-2">
        <div className="grid grid-cols-4 gap-1">
          {[100, 75, 50, 25].map((value) => (
            <Button key={value} variant="outline" size="sm" className="tabular-nums" onClick={() => give(value)}>
              {value}
            </Button>
          ))}
        </div>
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            if (score !== undefined) give(score)
          }}
        >
          <Input
            type="number"
            inputMode="numeric"
            min={0}
            max={100}
            placeholder={String(DEFAULT_SCORE)}
            aria-label={t("Priority, from 0 to 100")}
            aria-invalid={score === undefined || undefined}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            className="h-8 flex-1 tabular-nums"
          />
          <Button type="submit" size="sm" disabled={score === undefined}>
            {t("Apply")}
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  )
}
