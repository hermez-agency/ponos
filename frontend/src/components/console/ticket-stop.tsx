import * as React from "react"
import { MoreHorizontal } from "lucide-react"

import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { columnTitle } from "@/components/console/ticket-bits"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { moveWithToast as move } from "@/hooks/use-console"
import { titleOf, useBoardWith } from "@/lib/board-store"
import { t, useT } from "@/lib/i18n"
import type { Board, Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"

/** The gestures of a ticket in progress and of one put aside, where the board has the column.
 *
 * Pausing keeps what was done and is one click; abandoning loses it, and asks.
 * The two used to sit side by side as twin buttons, one stray click apart:
 * pausing stays a button, abandoning waits behind "…", in red, and its window
 * says what goes with it and opens on Cancel. Both are a move: the console ends
 * the session before it writes the status. Resuming is the way back to ready,
 * asked for like every other: the session it starts is paid for. */
const columnsOf = (board: Board) => board.columns
const cancels = (board: Board) => board.cancel

export default function StopGestures({
  ticket,
  className,
  filled = false,
}: {
  ticket: Ticket
  className?: string
  /** On a card of the board, Pause or Resume is its one filled button. */
  filled?: boolean
}) {
  // What the gestures read of the board, which its moves leave as it was.
  const board = { columns: useBoardWith(columnsOf), cancel: useBoardWith(cancels) }
  useT()
  const [abandoning, setAbandoning] = React.useState(false)
  const running = ticket.column === "running"
  const pauses = board.columns.some((column) => column.key === "paused")
  // Nothing to offer: nothing is drawn, rather than an empty row where the gestures would be.
  if (running && !pauses && !board.cancel) return null
  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {running && pauses ? (
        <Button variant={filled ? "default" : "outline"} size="sm" onClick={() => void move(ticket, "paused")}>
          {t("Pause")}
        </Button>
      ) : null}
      {running ? null : (
        <ConfirmDialog
          title={t("Make “{{title}}” ready?", { title: titleOf(ticket) })}
          description={t(
            "The ticket goes to {{column}} and a session starts on it as soon as a place is free — a session that is paid for.",
            { column: columnTitle("ready", board.columns.find((column) => column.key === "ready")?.name) }
          )}
          confirm={t("Make it ready")}
          onConfirm={() => void move(ticket, "ready")}
          trigger={
            <Button variant={filled ? "default" : "outline"} size="sm">
              {t("Resume")}
            </Button>
          }
        />
      )}
      {board.cancel ? (
        <>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="icon-sm"
                className="shrink-0"
                aria-label={t("More actions")}
                title={t("More actions")}
              >
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem variant="destructive" onSelect={() => setAbandoning(true)}>
                {t("Abandon")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <ConfirmDialog
            open={abandoning}
            onOpenChange={setAbandoning}
            destructive
            focusCancel
            title={t("Abandon “{{title}}”?", { title: titleOf(ticket) })}
            description={
              running
                ? t(
                    "The session in progress is stopped, and the work it has not pushed is lost. This cannot be undone."
                  )
                : t("The work that was not pushed is lost. This cannot be undone.")
            }
            confirm={t("Abandon the ticket")}
            onConfirm={() => void move(ticket, "cancelled")}
          />
        </>
      ) : null}
    </div>
  )
}
