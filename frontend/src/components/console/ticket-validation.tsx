import * as React from "react"
import { toast } from "sonner"

import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { isFinished } from "@/lib/result"
import { canAct } from "@/lib/role"
import type { TicketDetail } from "@/lib/types"
import { cn } from "@/lib/utils"

import { Eyebrow } from "./frame"

/* « Review » of one ticket — « Force validated » in the code — over the
 * project's and the global one.
 *
 * Three states: as the project (what the project says, else the global
 * setting — said with its source, as the report will say it), never (`forced`:
 * validated as soon as the session succeeds), or always (`free`: waits for the
 * review even where the project or the file forces). The question asked is
 * whether you read the work first, not the code's word for it. Saved
 * straight to the ledger, and read when the validation is decided, so a change
 * made while the session runs counts. Not offered once the ticket is done.
 */

const CHOICES = [
  { value: "", label: "As the project" },
  { value: "forced", label: "Never" },
  { value: "free", label: "Always" },
]

export function TicketValidation({
  ticket,
  compact = false,
}: {
  ticket: TicketDetail
  /** A row among the ticket's facts, under its name: no heading of its own, no rule above. */
  compact?: boolean
}) {
  const t = useT()
  const saved = ticket.validation ?? ""
  const inherited = ticket.validation_inherited ?? ""
  const [value, setValue] = React.useState(saved)
  const [busy, setBusy] = React.useState(false)
  const writable = canAct() && !isFinished(ticket.column)

  React.useEffect(() => setValue(saved), [saved])

  const choose = async (next: string) => {
    if (busy || next === value) return
    setBusy(true)
    try {
      await api.setValidation(ticket.id, next)
      setValue(next)
      toast.success(t("Review saved"))
    } catch (error) {
      toast.error(why(error))
    } finally {
      setBusy(false)
    }
  }

  const effective =
    value === "forced"
      ? t("Validated as soon as the session succeeds — the ticket's setting.")
      : value === "free"
        ? t("Waits for your review — the ticket's setting.")
        : inherited === "project"
          ? t("Validated as soon as the session succeeds — the project's setting.")
          : inherited === "global"
            ? t("Validated as soon as the session succeeds — the global setting.")
            : t("Waits for your review.")

  return (
    <section
      data-slot="ticket-validation"
      aria-label={compact ? t("Review") : undefined}
      className={cn("flex flex-col", compact ? "gap-1" : "gap-2 border-t pt-4")}
    >
      {compact ? null : <Eyebrow>{t("Review")}</Eyebrow>}
      <div
        role="group"
        aria-label={t("Review")}
        className="bg-field flex w-fit flex-wrap gap-0.5 rounded-lg border p-0.5"
      >
        {CHOICES.map((choice) => (
          <button
            key={choice.value || "inherited"}
            type="button"
            aria-pressed={value === choice.value}
            disabled={!writable || busy}
            onClick={() => choose(choice.value)}
            className={cn(
              "text-muted-foreground hover:bg-accent hover:text-foreground rounded-md px-2 py-1 text-xs font-medium transition-colors outline-none disabled:opacity-60",
              value === choice.value && "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground"
            )}
          >
            {t(choice.label)}
          </button>
        ))}
      </div>
      <p className={cn("text-muted-foreground", compact ? "text-xs" : "text-sm")}>{effective}</p>
    </section>
  )
}
