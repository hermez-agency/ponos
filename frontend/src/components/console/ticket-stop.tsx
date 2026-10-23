import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { columnTitle } from "@/components/console/ticket-bits"
import { Button } from "@/components/ui/button"
import { moveWithToast as move } from "@/hooks/use-console"
import { titleOf, useBoard } from "@/lib/board-store"
import { t, useT } from "@/lib/i18n"
import type { Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"

/** The gestures of a ticket in progress and of one put aside, where the board has the column.
 *
 * Pausing keeps what was done and is one click; abandoning loses it, and asks.
 * Both are a move: the console ends the session before it writes the status.
 * Resuming is the way back to ready, asked for like every other: the session
 * it starts is paid for. */
export default function StopGestures({ ticket, className }: { ticket: Ticket; className?: string }) {
  const board = useBoard()
  useT()
  const running = ticket.column === "running"
  const pauses = board.columns.some((column) => column.key === "paused")
  // Nothing to offer: nothing is drawn, rather than an empty row where the gestures would be.
  if (running && !pauses && !board.cancel) return null
  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {running && pauses ? (
        <Button variant="outline" size="sm" onClick={() => void move(ticket, "paused")}>
          {t("Pause")}
        </Button>
      ) : null}
      {running ? null : (
        <ConfirmDialog
          title={t("Make “{{title}}” ready?", { title: titleOf(ticket) })}
          description={t(
            "The ticket goes to {{column}} and the next pass starts a session on it — a session that is paid for.",
            { column: columnTitle("ready", board.columns.find((column) => column.key === "ready")?.name) }
          )}
          confirm={t("Make it ready")}
          onConfirm={() => void move(ticket, "ready")}
          trigger={
            <Button variant="outline" size="sm">
              {t("Resume")}
            </Button>
          }
        />
      )}
      {board.cancel ? (
        <ConfirmDialog
          title={t("Cancel the ticket")}
          description={t("This cannot be undone.")}
          confirm={t("Abandon")}
          onConfirm={() => void move(ticket, "cancelled")}
          trigger={
            <Button variant="outline" size="sm">
              {t("Abandon")}
            </Button>
          }
        />
      ) : null}
    </div>
  )
}
