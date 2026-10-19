import * as React from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import type { TicketDetail, Transition } from "@/lib/types"
import { cn } from "@/lib/utils"

import { Eyebrow } from "./frame"
import { lasted, when } from "./ticket-bits"

/* The « On » prompt of a ticket, and what it has done.
 *
 * A prompt run by the runner at every change of the ticket's status — see
 * `transitions.py` for what counts as a change and for the guardrails. Written
 * here as plain text, saved straight to the board's « On » column; below it,
 * one line per execution with the transition it answered, what it cost and what
 * it said. A ticket without the column on its board says so rather than
 * offering a box that would save nothing.
 */

const STATE: Record<string, { word: string; tone: string }> = {
  pending: { word: "not started", tone: "text-muted-foreground" },
  running: { word: "being run", tone: "text-tr-amber" },
  ok: { word: "ran", tone: "text-tr-green" },
  failed: { word: "stopped on an error", tone: "text-destructive" },
  skipped: { word: "not run", tone: "text-muted-foreground" },
}

export function TicketOn({ ticket }: { ticket: TicketDetail }) {
  const t = useT()
  const saved = ticket.on ?? ""
  const [text, setText] = React.useState(saved)
  const [busy, setBusy] = React.useState(false)
  const [runs, setRuns] = React.useState<Transition[]>([])
  const edited = ticket.edited

  // Another copy of the page (Notion, a second tab) wins over what was typed
  // only when nothing was typed since the last save.
  const written = React.useRef(saved)
  React.useEffect(() => {
    setText((now) => (now === written.current ? saved : now))
    written.current = saved
  }, [saved])

  // Read again whenever the board says the ticket moved: a change of status is
  // what an execution is for.
  React.useEffect(() => {
    let live = true
    api.transitions(ticket.id).then(
      (answer) => live && setRuns(answer.transitions),
      () => live && setRuns([])
    )
    return () => {
      live = false
    }
  }, [ticket.id, ticket.status, edited])

  const save = async () => {
    setBusy(true)
    try {
      await api.setOn(ticket.id, text)
      written.current = text.trim()
      toast.success(text.trim() ? t("Prompt saved") : t("Prompt removed"))
    } catch (error) {
      toast.error(why(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section data-slot="ticket-on" className="mt-6 flex flex-col gap-2 border-t pt-4">
      <Eyebrow>{t("Prompt on status change")}</Eyebrow>
      <p className="text-muted-foreground text-sm">
        {t("A prompt Ponos runs at every change of this ticket's status, with the old status, the new one and the ticket. Empty, nothing runs.")}
      </p>
      <Textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder={t("If it goes to validated, create the deployment ticket.")}
        rows={4}
        className="font-mono text-sm"
        aria-label={t("Prompt on status change")}
      />
      <div>
        <Button size="sm" variant="outline" disabled={busy || text.trim() === saved.trim()} onClick={save}>
          {t("Save the prompt")}
        </Button>
      </div>
      {runs.length ? (
        <ul className="mt-2 flex flex-col divide-y rounded-xl border text-sm" data-slot="ticket-on-runs">
          {runs.map((run) => (
            <li key={run.id} className="flex flex-col gap-0.5 px-3 py-2">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className="font-medium">
                  {run.old} → {run.new}
                </span>
                <span className={cn("text-xs", STATE[run.state]?.tone)}>
                  {t(STATE[run.state]?.word ?? run.state)}
                </span>
                <span className="text-muted-foreground text-xs">{when(run.seen_at)}</span>
                {run.cost_usd ? <span className="text-xs">{money(run.cost_usd, 3)}</span> : null}
                {run.seconds ? <span className="text-muted-foreground text-xs">{lasted(run.seconds / 60)}</span> : null}
                {run.depth ? (
                  <span className="text-muted-foreground text-xs">
                    {t("generation")} {run.depth}
                  </span>
                ) : null}
              </div>
              {run.result ? <p className="text-muted-foreground break-words">{run.result}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
