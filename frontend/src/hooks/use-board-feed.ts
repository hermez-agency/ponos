import * as React from "react"
import { toast } from "sonner"

import { applyChanges, currentBoard, publishBoard, titleOf } from "@/lib/board-store"
import { unshown } from "@/lib/conflicts"
import { goalsMoved, movesGoals } from "@/lib/goals-store"
import { t } from "@/lib/i18n"
import type { Board, BoardChanges, Ticket } from "@/lib/types"
import { conflictSaid } from "@/components/console/ticket-bits"

/* The board as the stream brings it: whole once, then by what changed.
 *
 * Besides holding it, this is where a move that went wrong is said — once,
 * when it stops being on its way, and not again by the next tab or reload.
 */

/* The refusals this browser has already toasted, one line each (`conflicts.ts`).
 * Kept in `localStorage`, so that a reload or a new tab does not say them
 * again; in memory where the browser keeps nothing. */
const SHOWN = "ponos:conflicts-shown"
let shownHere: string[] = []

function shownConflicts(): string[] {
  try {
    const kept = localStorage.getItem(SHOWN)
    return kept ? (JSON.parse(kept) as string[]) : []
  } catch {
    return shownHere
  }
}

function rememberConflicts(kept: string[]) {
  shownHere = kept
  try {
    localStorage.setItem(SHOWN, JSON.stringify(kept))
  } catch {
    // Private browsing, a full quota: this tab still remembers.
  }
}

const syncs = () => new Map((currentBoard()?.tickets ?? []).map((item) => [item.id, item.sync]))

/** `follow`: the tickets that moved, for the open one (`useTicketTalk`).
 *  `lost`: changes that do not follow from the board held here, which asks for it whole. */
export function useBoardFeed(follow: (touched: Ticket[]) => void, lost: () => void) {
  const [board, setBoard] = React.useState<Board>({ tickets: [], columns: [] })

  /* The board moved, whole or by a few tickets: `touched` are the tickets
   * that are new or changed, the only ones worth a look. */
  const boardMoved = React.useCallback(
    (fresh: Board, touched: Ticket[], before: Map<string, Ticket["sync"]>) => {
      // A move that did not reach the board is said once, when it stops being on
      // its way — the card keeps saying it after the toast is gone.
      for (const item of touched) {
        if (item.sync !== "failed" || before.get(item.id) === item.sync) continue
        toast.error(t("“{{title}}” did not reach the board", { title: titleOf(item) }), {
          description: item.sync_error,
        })
      }
      // A move not made because the board had changed is said once as well — but
      // it is read from the journal, and stays on the card until somebody acts:
      // what this browser has already shown is remembered across loads, or
      // every new tab said an old refusal again (`conflicts.ts`).
      const { fresh: refused, kept } = unshown(fresh.tickets, shownConflicts())
      for (const item of refused) {
        toast.error(t("“{{title}}” was changed on the board meanwhile", { title: titleOf(item) }), {
          description: conflictSaid(item),
        })
      }
      rememberConflicts(kept)
      setBoard(fresh)
      follow(touched)
    },
    [follow]
  )

  const on = {
    // Whole: on connecting, and when the columns changed.
    board: (fresh: Board) => {
      const before = syncs()
      if (movesGoals(currentBoard(), fresh)) goalsMoved()
      // The same board, where the resource views read it from.
      publishBoard(fresh)
      boardMoved(fresh, fresh.tickets, before)
    },

    // Only what moved since the last one. Changes that do not follow from the
    // board held here — one was lost on the way — are worth nothing: the whole
    // board is asked for again.
    changes: (changes: BoardChanges) => {
      const before = syncs()
      const held = currentBoard()
      const fresh = applyChanges(changes)
      if (!fresh) return lost()
      // A card of a goal changed column: the progress its page shows did too.
      if (movesGoals(held, fresh)) goalsMoved()
      boardMoved(
        fresh,
        changes.changed.map((entry) => entry.ticket),
        before
      )
    },
  }

  return { board, on }
}
