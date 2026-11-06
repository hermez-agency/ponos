import * as React from "react"

import { api } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { AuditEntry, TicketDetail } from "@/lib/types"

import { Eyebrow } from "./frame"
import { columnTitle, when } from "./ticket-bits"

/* Who did what to this ticket from the console.
 *
 * The board's own history names the runner's token for everything, and a
 * move leaves no comment — one on a blocked ticket would be read as an answer
 * — so the console keeps its own line per gesture, with the name as it was
 * then (`web/accounts.py`). Nothing is drawn for a ticket nobody touched from
 * here: most tickets, on a console used alone.
 */

const DECIDED: Record<string, string> = {
  validate: "validated it",
  reject: "rejected it",
  retry: "ran it again",
  abandon: "abandoned it",
}

function said(t: ReturnType<typeof useT>, entry: AuditEntry): string {
  switch (entry.action) {
    case "created":
      return entry.detail === "draft" ? t("created it as a draft") : t("created it")
    case "moved":
      return t("moved it to {{column}}", { column: columnTitle(entry.detail) })
    case "told":
      return t("wrote in its discussion")
    case "decided":
      return t(DECIDED[entry.detail] ?? "answered it")
    case "priority":
      return t("set its priority to {{priority}}", { priority: entry.detail || "50" })
    case "on":
      return entry.detail ? t("changed its « On » prompt") : t("removed its « On » prompt")
    case "goal":
      return entry.detail ? t("tied it to a goal") : t("untied it from its goal")
    case "launched":
      return entry.detail === "forced" ? t("ran it now, past the limit") : t("ran it now")
  }
}

export function TicketAudit({ ticket }: { ticket: TicketDetail }) {
  const t = useT()
  const [entries, setEntries] = React.useState<AuditEntry[]>([])
  // Read again when the ticket moves: a gesture made in another tab moves it too.
  React.useEffect(() => {
    let live = true
    api.audit(ticket.id).then(
      (answer) => live && setEntries(answer.entries),
      () => live && setEntries([])
    )
    return () => {
      live = false
    }
  }, [ticket.id, ticket.status, ticket.edited])
  if (!entries.length) return null
  return (
    <section className="mt-6" data-slot="ticket-audit">
      <Eyebrow>{t("From the console")}</Eyebrow>
      <ul className="mt-2 flex flex-col gap-1 text-sm">
        {entries.map((entry, index) => (
          <li key={index} className="flex flex-wrap gap-x-1.5">
            <span className="font-medium">{entry.who || t("The token")}</span>
            <span>{said(t, entry)}</span>
            <span className="text-muted-foreground">· {when(entry.at)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
