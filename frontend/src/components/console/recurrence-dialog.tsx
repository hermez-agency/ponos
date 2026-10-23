import * as React from "react"
import { CalendarClock } from "lucide-react"
import {
  InputControllerProvider,
  getFormInputsFromForm,
  useFormContext,
  type InputControllerComponentInterface,
} from "react-data-form"
import { useChildViewRoute } from "react-resource-view"

import { WithProjects } from "@/components/console/new-ticket-lazy"
import { useCloseWindow } from "@/components/console/record-window"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { t } from "@/lib/i18n"
import { nextAfter, zoneOf } from "@/lib/occurrences"
import { WEEKDAYS, clockOf, dayName, locale, ruleOf, weekdayOf } from "@/lib/recurrence"
import { runnerZone } from "@/lib/runner-zone"
import { cn } from "@/lib/utils"

/* The schedule's form, as a question asked in a few clicks rather than seven
 * fields to fill in.
 *
 * It used to be the package's column of fields: a select for the cadence, the
 * hour typed as "09:00", the day as free text ("Monday, or 1 to 31") shown
 * whatever the cadence, and nothing saying when the first ticket would come.
 * The fields are still react-data-form's, declared in `resources/schedules`
 * and written back the way they always were — the same words in the same
 * columns: only how each one is drawn changed. The cadence and the model are
 * buttons all in view, the priority a score beside its badge, the day takes
 * the shape the cadence gives it (pills for a week, a number for a month,
 * nothing for a day or an hour),
 * and a line under them says it back in a sentence, with the date the next
 * ticket is born — worked out by the runner's own rule (`lib/occurrences`).
 */

/* -- the controllers ------------------------------------------------------ */

/* A choice among a handful, all in view. A press on the one already chosen
 * lets it go where empty is an answer — the model, which a ticket otherwise
 * takes from the runner — and keeps it where it is not. The labels are drawn
 * as they are given: the model is the board's word, said in no other language. */
export const SegmentsInputController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const value = String(formInput.value ?? "")
  const optional = !formInput.required
  return (
    <div
      role="group"
      aria-label={t(String(formInput.label ?? ""))}
      data-slot="segmented"
      className="bg-field flex gap-0.5 rounded-lg border p-0.5"
    >
      {(formInput.valueOptions ?? []).map((option) => {
        const key = String(option.value ?? "")
        const chosen = key === value
        return (
          <button
            key={key}
            type="button"
            aria-pressed={chosen}
            onClick={() =>
              onChange({ ...formInput, value: chosen && optional ? "" : key, violations: [] })
            }
            className={cn(
              "text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring/50 min-h-9 min-w-0 flex-1 rounded-md px-2 py-1 text-sm font-medium transition-colors outline-none focus-visible:ring-[3px]",
              chosen && "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground"
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

/* The day, in the shape the cadence gives it: a week's seven pills, a month's
 * number, and nothing at all for a cadence no day changes. */
export const DayInputController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const { form } = useFormContext()
  const cadence = String(form.data?.cadence ?? "")
  const value = String(formInput.value ?? "")
  const set = (day: string) => onChange({ ...formInput, value: day, violations: [] })

  if (cadence === "Weekly") {
    const chosen = weekdayOf(value)
    return (
      <div role="group" aria-label={t("Day")} className="flex flex-wrap gap-1.5">
        {WEEKDAYS.map((day, index) => (
          <button
            key={day}
            type="button"
            aria-pressed={index === chosen}
            aria-label={dayName(index, "long")}
            title={dayName(index, "long")}
            onClick={() => set(day)}
            className={cn(
              "bg-field text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 inline-flex size-11 items-center justify-center rounded-full border text-sm font-semibold transition-colors outline-none focus-visible:ring-[3px]",
              index === chosen && "border-primary bg-primary text-primary-foreground hover:text-primary-foreground"
            )}
          >
            {dayName(index, "narrow").toUpperCase()}
          </button>
        ))}
      </div>
    )
  }
  if (cadence === "Monthly") {
    const id = formInput.id ?? "field-day"
    return (
      <label htmlFor={id} className="flex items-center gap-2 text-sm">
        <span>{t("On the")}</span>
        <Input
          id={id}
          type="number"
          inputMode="numeric"
          min={1}
          max={31}
          value={value}
          placeholder="1"
          onChange={(event) => set(event.target.value)}
          className="h-9 w-20 text-center"
        />
        <span>{t("of the month")}</span>
      </label>
    )
  }
  return null
}

/** The hour, in the browser's own field for one. */
export const TimeInputController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const id = formInput.id ?? "field-at"
  return (
    <Input
      id={id}
      type="time"
      value={clockOf(String(formInput.value ?? ""))}
      onChange={(event) => onChange({ ...formInput, value: event.target.value, violations: [] })}
      className="h-9 w-32"
    />
  )
}

/* -- the summary ------------------------------------------------------------ */

/** Now, once a minute: the next ticket moves when the hour it was due at goes by. */
function useNow() {
  const [now, setNow] = React.useState(() => Date.now())
  React.useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

/* The rule said back in a sentence, and when it next makes a ticket.
 *
 * The rule's hours are the runner's — 09:00 is nine on the machine that runs
 * it — and the date is said in the reader's own zone, the one their clock
 * shows. A new schedule's first ticket is the rule's next moment after now:
 * that is what the runner writes on the first pass that reads it. One already
 * running keeps the date the server said, whatever the form changes: the
 * runner moves its bookmark only once that ticket is made. */
function Summary({ data, original }: { data: Record<string, unknown>; original?: Record<string, unknown> }) {
  const now = useNow()
  const cadence = String(data.cadence ?? "")
  const at = String(data.at ?? "")
  const day = String(data.day ?? "")
  const active = data.active === true
  const rule = ruleOf({ cadence, at, day })

  const said = original?.active === true ? String(original.next ?? "") : ""
  const kept = active && said ? Date.parse(said) : NaN
  const next = Number.isNaN(kept) ? nextAfter({ cadence, at, day }, now, zoneOf(runnerZone())) : kept
  // Due already — the server says so with the moment it was asked — is born on
  // the very next pass, not at an hour of its own.
  const due = !Number.isNaN(kept) && kept <= now + 60_000
  const when =
    next === null
      ? ""
      : due
        ? t("at the next pass")
        : t("{{date}} at {{time}}", {
          date: new Intl.DateTimeFormat(locale(), { weekday: "short", day: "numeric", month: "short" }).format(next),
          time: new Intl.DateTimeFormat(locale(), { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(next),
        })

  return (
    <p
      data-slot="recurrence-summary"
      aria-live="polite"
      className="flex items-start gap-2 rounded-xl border border-primary/30 bg-primary/10 px-3 py-2.5 text-sm text-foreground [&>svg]:mt-0.5 [&>svg]:size-4 [&>svg]:shrink-0"
    >
      <CalendarClock />
      <span>
        {!rule || !when
          ? t("Choose a cadence and an hour to see when the next ticket is created.")
          : `${rule}. ${
              active
                ? t("Next ticket: {{when}}.", { when })
                : t("Next ticket, once it is turned on: {{when}}.", { when })
            }`}
      </span>
    </p>
  )
}

/* -- the form's body ------------------------------------------------------- */

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="flex flex-col gap-3">
    <h3 className="text-sm font-semibold">{title}</h3>
    {children}
  </section>
)

export function RecurrenceFields() {
  const context = useFormContext()
  const { form } = context
  const latest = React.useRef(context)
  latest.current = context

  const inputs = getFormInputsFromForm(form)
  const data = (form.data ?? {}) as Record<string, unknown>
  const cadence = String(data.cadence ?? "")
  const day = String(data.day ?? "")
  const type = String(data.type ?? "")
  // The list it was opened over, narrowed to one project: the schedule is for that one.
  const narrowed = String(useChildViewRoute()?.parentParams.filter?.project ?? "")

  const field = (name: string) => {
    const input = inputs.find((candidate) => candidate.name === name)
    return input ? (
      <InputControllerProvider key={`${input.id}${input.name}${form.version}`} formInput={input} />
    ) : null
  }

  // A day the cadence cannot read is put back to one it can: "Monday" means
  // nothing to a month, "12" nothing to a week. A day that already fits is
  // left as it is, so a row opened is a row unchanged.
  React.useEffect(() => {
    let fixed: string | null = null
    if (cadence === "Weekly" && day.trim() && weekdayOf(day) < 0) fixed = "Monday"
    if (cadence === "Monthly" && day.trim() && !/^([1-9]|[12]\d|3[01])$/.test(day.trim())) fixed = "1"
    if (fixed === null) return
    const input = getFormInputsFromForm(latest.current.form).find((candidate) => candidate.name === "day")
    if (input) latest.current.onChange({ ...input, value: fixed })
  }, [cadence, day])

  // A new schedule written from a list showing one project's is that project's,
  // as a ticket made under a project's page is — said once, and let go of as
  // any other choice. One opened already keeps the project it has.
  React.useEffect(() => {
    const { form: now } = latest.current
    if (!narrowed || (now.originalData as { id?: string } | undefined)?.id || now.data?.project_id) return
    const input = getFormInputsFromForm(now).find((candidate) => candidate.name === "project_id")
    if (input) latest.current.onChange({ ...input, value: narrowed })
  }, [narrowed])

  return (
    <div
      data-recurrence-form
      className="flex flex-col gap-5 [&_[data-slot=field]]:my-0 [&_[data-slot=field-label]]:text-muted-foreground [&_[data-slot=field-label]]:text-xs"
    >
      {field("name")}
      <Section title={t("When?")}>
        {field("cadence")}
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          {cadence === "Weekly" || cadence === "Monthly" ? field("day") : null}
          {field("at")}
          {/* An hourly one has no hour: only the minutes of the field are read,
              which a box reading "00:00" under "Time" did not say. */}
          {cadence === "Hourly" ? (
            <p className="text-muted-foreground pb-2 text-xs">{t("Every hour: only the minutes are read.")}</p>
          ) : null}
        </div>
        <Summary data={data} original={form.originalData as Record<string, unknown> | undefined} />
      </Section>
      <WithProjects>{field("project_id")}</WithProjects>
      <div className="grid gap-4 sm:grid-cols-2">
        {field("model")}
        {field("priority")}
      </div>
      {field("type")}
      {type === "" || type === "code" ? field("subtype") : null}
      {field("body")}
    </div>
  )
}

/* -- the foot ---------------------------------------------------------------- */

/* The box that turns it on, on the left, and the two ways out on the right.
 * The box only says in the form what the switch used to: a new schedule is
 * still written unticked by the server, and ticked straight after when the
 * box asked for it (see `createItem`). */
export function RecurrenceFoot() {
  const context = useFormContext()
  const close = useCloseWindow()
  const editing = Boolean((context.form.originalData as { id?: string } | undefined)?.id)
  const active = context.form.data?.active === true
  const busy = Boolean(context.form.loading)
  const id = "recurrence-active"

  const turn = (on: boolean) => {
    const input = getFormInputsFromForm(context.form).find((candidate) => candidate.name === "active")
    if (input) context.onChange({ ...input, value: on })
  }

  return (
    <div className="bg-background sticky -bottom-4 z-10 -mx-5 -mb-4 mt-5 flex flex-col gap-3 border-t px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
      <label htmlFor={id} className="flex cursor-pointer items-center gap-2 text-sm">
        <Checkbox id={id} checked={active} onCheckedChange={(checked) => turn(checked === true)} />
        {editing ? t("Turned on") : t("Turn on right away")}
      </label>
      <div className="flex shrink-0 justify-end gap-2 [&>button]:h-12 [&>button]:flex-1 [&>button]:px-5 sm:[&>button]:flex-none">
        {close ? (
          <Button type="button" variant="secondary" onClick={close}>
            {t("Cancel")}
          </Button>
        ) : null}
        <Button type="button" disabled={busy} onClick={() => void context.onSubmit()}>
          {editing ? t("Save") : t("Create the schedule")}
        </Button>
      </div>
    </div>
  )
}
