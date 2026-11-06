import * as React from "react"
import { Play } from "lucide-react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { titleOf } from "@/lib/board-store"
import { useT } from "@/lib/i18n"
import type { Launched, Ticket } from "@/lib/types"

/** « Run now », on a ready ticket: a free place at once, rather than its turn in the queue.
 *
 * The daemon decides (`web/tickets.py`, `scheduler.py`): it starts the ticket
 * in a free place, or answers that none is — every place taken, or its
 * project at its limit. Then, and only then, the page offers to run it past
 * the limit, once: a place the limit does not count, asked for in so many
 * words, since it is one more session than you said the machine should run. */
/* Why no place was free, in the page's language: the daemon says it in English,
 * in one of two shapes (`Scheduler._fullness`). */
function fullness(message: string, t: ReturnType<typeof useT>): string {
  const places = /^all (\d+) place\(s\) are taken$/.exec(message)
  if (places) return t("All {{count}} places are taken", { count: places[1] })
  const project = /^(.+) already holds (\d+) place\(s\)$/.exec(message)
  if (project) return t("{{project}} already holds its {{count}} places", { project: project[1], count: project[2] })
  return message
}

export function RunNow({ ticket }: { ticket: Ticket }) {
  const t = useT()
  const [busy, setBusy] = React.useState(false)
  const [full, setFull] = React.useState("")

  const said = (answer: Launched) => {
    if (answer.status === "started")
      toast.success(t("“{{title}}” is starting now", { title: titleOf(ticket) }))
    else if (answer.status === "full") setFull(answer.message)
    else toast.error(t("“{{title}}” was not started", { title: titleOf(ticket) }), { description: answer.message })
  }
  const launch = async (force: boolean) => {
    setBusy(true)
    try {
      said(await api.launch(ticket.id, force))
    } catch (error) {
      toast.error(t("“{{title}}” was not started", { title: titleOf(ticket) }), {
        description: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {/* An icon beside « Set aside » and « … »: a card is narrow, and three
          worded buttons on it go to two lines. Its name is the tooltip's. */}
      <Button
        variant="outline"
        size="icon-sm"
        className="shrink-0"
        disabled={busy}
        data-slot="run-now"
        aria-label={t("Run now")}
        title={`${t("Run now")} — ${t("Start it in a free place now, ahead of its turn in the queue.")}`}
        onClick={() => void launch(false)}
      >
        <Play />
      </Button>
      <ConfirmDialog
        open={Boolean(full)}
        onOpenChange={(open) => !open && setFull("")}
        title={t("No place is free")}
        description={t(
          "{{why}}. Run “{{title}}” anyway, past the limit — one more session at once than the settings allow, this once?",
          { why: fullness(full, t), title: titleOf(ticket) }
        )}
        confirm={t("Run it past the limit")}
        onConfirm={() => {
          setFull("")
          void launch(true)
        }}
      />
    </>
  )
}
