import { X } from "lucide-react"

import { Input } from "@/components/ui/input"
import { useFrench, useT } from "@/lib/i18n"
import { SHORTCUTS, fromLocalInput, isoWithOffset, localInput, shortcut, type Shortcut } from "@/lib/later"
import { cn } from "@/lib/utils"

/* « Scheduled for »: when a ticket may start, said by a shortcut or typed.
 *
 * The same few words in the New ticket dialog and in a ticket's view, so the
 * two never offer different things. A shortcut is a moment of the browser's
 * timezone, the person's own (`lib/later.ts`); what leaves is ISO with its
 * offset, or "" for « as soon as a place is free ». The runner refuses a
 * moment already past, and says so — the picker does not try to guess first.
 */

/* Its words in French, fetched once the picker is drawn: see `later-french.ts`. */
const words = () => import("@/lib/later-french").then((module) => module.LATER_FRENCH)

const LABELS: Record<Shortcut, string> = {
  hour: "In 1 h",
  tonight: "Tonight",
  tomorrow: "Tomorrow morning",
  "after-tomorrow": "The day after tomorrow",
  monday: "Next Monday",
}

export function SchedulePicker({
  value,
  onChange,
  id,
  disabled,
}: {
  value: string
  onChange: (next: string) => void
  id?: string
  disabled?: boolean
}) {
  const t = useT()
  // Drawn in English for the moment its words take to arrive, rather than not at all.
  useFrench(words)
  // Read once per draw: a dialog left open over the evening drops « Tonight » on its next draw.
  const now = new Date()
  return (
    <div className="flex flex-col gap-1.5" data-slot="schedule-picker">
      <div role="group" aria-label={t("Shortcuts")} className="flex flex-wrap gap-1.5">
        {SHORTCUTS.map((name) => {
          const moment = shortcut(name, now)
          if (!moment) return null
          const iso = isoWithOffset(moment)
          const chosen = localInput(iso) === localInput(value)
          return (
            <button
              key={name}
              type="button"
              disabled={disabled}
              aria-pressed={chosen}
              data-shortcut={name}
              onClick={() => onChange(chosen ? "" : iso)}
              className={cn(
                "bg-field text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 rounded-full border px-2.5 py-0.5 text-xs transition-colors outline-none focus-visible:ring-[3px] disabled:opacity-50",
                chosen && "border-primary bg-primary/15 text-foreground"
              )}
            >
              {t(LABELS[name])}
            </button>
          )
        })}
      </div>
      <div className="flex items-center gap-1.5">
        <Input
          id={id}
          type="datetime-local"
          disabled={disabled}
          aria-label={t("Date and hour")}
          value={localInput(value)}
          onChange={(event) => onChange(fromLocalInput(event.target.value))}
          className="h-8 min-w-0 flex-1 text-xs"
        />
        {value ? (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange("")}
            aria-label={t("Remove the date")}
            title={t("Remove the date")}
            className="text-muted-foreground hover:text-foreground rounded-md p-1"
          >
            <X className="size-4" />
          </button>
        ) : null}
      </div>
    </div>
  )
}
