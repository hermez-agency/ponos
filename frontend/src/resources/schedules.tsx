import * as React from "react"
import { CalendarCheck, CalendarClock, CalendarOff, ExternalLink, Loader2, Play, SearchX, X } from "lucide-react"
import { toast } from "sonner"
import {
  ActionList,
  SelectInputController,
  useFormContext,
  type FormInterface,
  type InputControllerComponentInterface,
} from "react-data-form"
import {
  createResourceCollection,
  createViewResource,
  generateLinkByResource,
  Link,
  ListCalendar,
  ListTable,
  layout,
  useCurrentViewResourceContext,
  useListViewContext,
  useNavigate,
  type ListComponentPropsInterface,
  type RowComponentPropsInterface,
  type RowInterface,
} from "react-resource-view"

import { EmptyState } from "@/components/console/empty-state"
import { ModelInputController } from "@/components/console/model-input"
import { MarkdownInputController } from "@/components/console/markdown-editor"
import { choiceWord } from "@/components/console/ticket-bits"
import {
  DayInputController,
  RecurrenceFields,
  RecurrenceFoot,
  SegmentsInputController,
  TimeInputController,
} from "@/components/console/recurrence-dialog-lazy"
import { PillsInputController } from "@/components/console/new-ticket-lazy"
import { PriorityInputController } from "@/components/console/priority"
import { recordWindow, useOpensOverTheList } from "@/components/console/record-window"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { ApiError, api, why } from "@/lib/api"
import { t } from "@/lib/i18n"
import { readScore } from "@/lib/priority"
import { locale, ruleOf } from "@/lib/recurrence"
import { layoutOf, useLayoutInTheAddress } from "@/lib/resource-view"
import { useRoute } from "@/lib/router"
import { setRunnerZone } from "@/lib/runner-zone"
import { STATES, filtering, keeps } from "@/lib/schedule-search"
import type { Schedule, Schedules } from "@/lib/types"
import { projectsOnce, projectsRead, useProjects } from "@/resources/projects"
import { ticketHref } from "@/resources/tickets"

/* What comes back on its own, declared once for react-resource-view.
 *
 * It used to be a pane of its own: cards drawn here, a form written here, a
 * date formatted here into "in 6 days". Every one of those already exists in
 * the package the board and the projects are drawn with — so a schedule is a
 * resource like them, and what draws it is the package's table, its calendar,
 * its form and its empty page. Nothing on this screen is styled twice.
 *
 * Two layouts, and the pair is the point. **A table** to compare them, and to
 * turn one off: `Active` is the one cell that is not read-only, so unticking a
 * row in the list is the whole gesture — which is the gesture this feature was
 * designed around, since it stops everything without deleting a single row.
 * On a phone the table is a card per schedule, the same switch on each.
 * **A calendar** because the only question a schedule really answers is when
 * the next one lands, and `Next` is a date: the package lays the rows out by
 * day, week or month, and a row with no date is a row nothing is due from.
 *
 * What neither form offers is the three columns a *pass* writes back — `Next`,
 * `Last` and the ticket the last occurrence made. They are how the runner knows
 * an occurrence has been taken, and a console that let you edit them would let
 * you make an occurrence happen twice, or never. The table shows the first two,
 * read-only.
 *
 * The rows are asked for when the page is opened rather than watched like the
 * board: a schedule moves four times a day at the very most, and a tab left
 * open here has no business polling that database.
 */

export const SCHEDULES = "schedules"

/** A schedule as the views hold it: the row, its body once it is opened, and an IRI to address it by. */
export type ScheduleItem = Schedule & {
  body?: string
  "@id": string
  "@type": string
}

/** What the console writes about a schedule: the columns a row is written in, and its body. */
export interface ScheduleWrite {
  id?: string
  name?: string
  cadence?: string
  at?: string
  day?: string
  active?: boolean
  model?: string
  /** A score from 0 to 100, as typed: empty is 50. */
  priority?: string | number | null
  type?: string
  subtype?: string
  body?: string
}

const item = (schedule: Schedule & { body?: string }): ScheduleItem => ({
  ...schedule,
  "@id": `/api/schedules/${schedule.id}`,
  "@type": SCHEDULES,
})

/* -- what the list last read ---------------------------------------------- */

/* The payload says three things a row does not: whether the workspace has the
 * database at all, what that page is called, and whether `runner.schedule` is
 * on. All three are read outside the rows that came with them — the foot of the
 * page, the empty page, the button that writes a new row — so what the server
 * last said is kept here, the way the projects keep theirs.
 *
 * The refusal is kept with it rather than swallowed: "something went wrong" is
 * all a view component is handed, and a token that expired and a workspace
 * without that database are two different afternoons.
 */
interface LastRead {
  drawn: Schedules | null
  problem: string
}

let read: LastRead = { drawn: null, problem: "" }
const listeners = new Set<() => void>()

function publish(fresh: LastRead) {
  read = fresh
  if (fresh.drawn) setRunnerZone(fresh.drawn.timezone)
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** What the list last read, redrawn with it. */
function useSchedules(): LastRead {
  return React.useSyncExternalStore(subscribe, () => read)
}

/** The rows, and the three facts that travel with them. */
async function load(): Promise<Schedules> {
  try {
    const fresh = await api.schedules()
    publish({ drawn: fresh, problem: "" })
    return fresh
  } catch (error) {
    publish({ drawn: null, problem: why(error) })
    throw error
  }
}

/* -- running one now -------------------------------------------------------- */

/* The schedules being launched, held outside the buttons: the row's and the
 * window's are two buttons for one schedule, and a second click on either —
 * or on the other — is the double click that must not make a second ticket.
 * The server refuses it too; this is what lets the button say so first. */
const launching = new Set<string>()
const launchListeners = new Set<() => void>()
let launchingNow: ReadonlySet<string> = new Set()

function setLaunching(id: string, on: boolean) {
  if (on) launching.add(id)
  else launching.delete(id)
  launchingNow = new Set(launching)
  launchListeners.forEach((listener) => listener())
}

function useLaunching(id: string) {
  const all = React.useSyncExternalStore(
    (listener) => {
      launchListeners.add(listener)
      return () => {
        launchListeners.delete(listener)
      }
    },
    () => launchingNow
  )
  return all.has(id)
}

/** The play button: the schedule's occurrence made now, `Next` left where it was. */
function LaunchButton({ id, className }: { id: string; className?: string }) {
  const busy = useLaunching(id)
  const navigate = useNavigate()
  const label = t("Run now")
  const launch = async (event: React.MouseEvent) => {
    event.stopPropagation()
    if (launching.has(id)) return
    setLaunching(id, true)
    try {
      const made = await api.launchSchedule(id)
      toast.success(t("Ticket created"), {
        description: made.title,
        action: { label: t("Open the ticket"), onClick: () => void navigate({ to: ticketHref(made.ticket) }) },
      })
      // Only `Last` moved: the list is read again so that it says so.
      const fresh = await load().catch(() => null)
      const found = fresh?.schedules.find((schedule) => schedule.id === id)
      if (found) schedules.onChange.publish({ data: item(found), action: ActionList.update })
    } catch (error) {
      toast.error(t("The schedule could not be run"), { description: why(error) })
    } finally {
      setLaunching(id, false)
    }
  }
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      className={className}
      disabled={busy}
      onClick={launch}
      title={label}
      aria-label={label}
      data-launch
    >
      {busy ? <Loader2 className="animate-spin" /> : <Play />}
    </Button>
  )
}

/* The row's own: the cell is handed the row it belongs to, as the name's is. */
const RunNow: InputControllerComponentInterface = () => {
  const { form } = useFormContext()
  const id = String((form?.data as { id?: string } | undefined)?.id ?? "")
  return id ? <LaunchButton id={id} /> : null
}

/* On the schedule's own page the button is the top of the form; in the window
 * it is in the header instead, so it is not drawn twice. */
function LaunchOnThePage() {
  const context = useCurrentViewResourceContext()
  const { params } = useRoute()
  const id = String(context.id ?? "")
  const here = params.resourceAction === ActionList.update && String(params.id ?? "") === id
  return id && here ? (
    <div className="mb-4 flex justify-end">
      <LaunchButton id={id} />
    </div>
  ) : null
}

/* -- the forms ------------------------------------------------------------- */

/* What a cadence may say: the same four `schedules.py` knows, and no free
 * text — each said as the sentence a button can carry. */
const CADENCES = (
  [
    ["Hourly", "Every hour"],
    ["Daily", "Every day"],
    ["Weekly", "Every week"],
    ["Monthly", "Every month"],
  ] as const
).map(([value, words]) => ({
  value,
  // Read from the dictionary as the button is drawn: the language can change after.
  get label() {
    return t(words)
  },
}))
/* The type and the sub-type its tickets are born with, as the server offers
 * them: only where the Schedules database has the column (`ponos init` adds
 * it), and in the board's words. Empty is an answer: the runner then guesses
 * each ticket's, as it does for one written by hand — and a long brief is
 * what a classifier reads as writing, which is why a schedule can say. */
const choicesOf = (key: "type" | "subtype") => read.drawn?.choices?.[key] ?? []

/* The seven fields a schedule is written in, drawn by `RecurrenceFields` in
 * the window the list opens (see `recurrence-dialog.tsx`).
 *
 * A label is translated by the package as it draws it; the sentence under a
 * field and the greyed example in it are not — they are used as they are
 * given. Those are read from the dictionary as the field is drawn, which is
 * what the getters are for: the declaration is built once, and the language
 * can change after it.
 */
const fields: FormInterface["inputs"] = {
  name: {
    label: "Ticket title",
    required: true,
    get placeholder() {
      return t("Weekly dependency review")
    },
    validator: (value: unknown) => {
      if (!String(value ?? "").trim()) throw new Error(t("A schedule needs a name"))
      return value
    },
  },
  cadence: {
    label: "Cadence",
    // Required, so a press on the chosen one does not let it go: a schedule
    // without a cadence is one the runner cannot read.
    required: true,
    controller: SegmentsInputController,
    valueOptions: CADENCES,
    // "When?" over it says what it is: the label is for the screen reader.
    className: "[&_[data-slot=field-label]]:sr-only",
  },
  // Drawn only for a weekly or a monthly one, in the shape that cadence gives it.
  day: { label: "Day", controller: DayInputController },
  at: { label: "Time", controller: TimeInputController },
  // The chat's own picker: none chosen is an answer, the ticket then takes the
  // runner's model. A slug written here is the board's word for it, untranslated.
  model: {
    label: "Model",
    controller: ModelInputController,
    get placeholder() {
      return t("the runner's model")
    },
  },
  priority: {
    label: "Priority",
    controller: PriorityInputController,
    validator: (value: unknown) => {
      if (readScore(value) === undefined) throw new Error(t("A priority is a number from 0 to 100."))
      return value
    },
  },
  type: {
    label: "Type",
    controller: SegmentsInputController,
    getValueOptions: async () =>
      choicesOf("type").map((choice) => ({ ...choice, label: choiceWord(choice.label) })),
    hidden: () => !choicesOf("type").length,
    get description() {
      return t("The road every ticket takes. Empty, the runner deduces it.")
    },
  },
  subtype: {
    label: "Sub-type",
    controller: PillsInputController,
    getValueOptions: async () => choicesOf("subtype"),
    // Drawn only beside an empty type or code (see `RecurrenceFields`): it is
    // ignored on a ticket of another type, as on the board.
    hidden: () => !choicesOf("subtype").length,
  },
  // The page body, and the part of a schedule that says what to do: every
  // occurrence is born with it copied under its first line.
  body: {
    label: "What Ponos must do every time",
    get description() {
      return t("Copied into every ticket created.")
    },
    get placeholder() {
      return t(
        "Run npm outdated in the repository, update what can be, and open a pull request. Done when the CI is green."
      )
    },
    controller: MarkdownInputController,
  },
  // Said by the box at the foot of the window: see `RecurrenceFoot`.
  active: { hidden: () => true },
}

/* A new row starts weekly, on Monday at nine — the example the summary under
 * the cadence then reads back — and unticked: the server writes it so
 * whatever the form says, and `createItem` ticks it straight after when the
 * box at the foot asked for it. */
const createForm: FormInterface = {
  components: { formInputs: RecurrenceFields, formSubmitAction: RecurrenceFoot },
  inputs: {
    ...fields,
    cadence: { ...fields.cadence, defaultValue: "Weekly" },
    day: { ...fields.day, defaultValue: "Monday" },
    at: { ...fields.at, defaultValue: "09:00" },
    active: { ...fields.active, defaultValue: false },
  },
}

const editForm: FormInterface = {
  components: { formInputs: RecurrenceFields, formSubmitAction: RecurrenceFoot },
  inputs: fields,
}

/* The name, as the way into the schedule: the window over the list, as a
 * ticket's title opens its own over the board — and the page it is written on,
 * where its history is (the comments, the edits, what Notion draws that a form
 * does not), one icon further. The table's cell and the phone's card draw the
 * same one. */
function ScheduleName({ id, name, url }: { id: string; name: string; url: string }) {
  const open = useOpensOverTheList(schedules, "update", id)
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      {id ? (
        <Link to={scheduleHref(id)} onClick={open} className="underline-offset-2 hover:underline">
          {name}
        </Link>
      ) : (
        name
      )}
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noreferrer noopener"
          className="text-muted-foreground hover:text-foreground shrink-0"
          title={t("Open the schedule's page on the board")}
          aria-label={t("Open the schedule's page on the board")}
        >
          <ExternalLink className="size-3.5" />
        </a>
      ) : null}
    </span>
  )
}

/* The package's own way of drawing a cell is a controller, handed its own
 * field and nothing else: the row it belongs to is the form it was built from. */
const rowOf = (form: { data?: unknown } | undefined) => (form?.data ?? {}) as Partial<ScheduleItem>

const PageLink: InputControllerComponentInterface = ({ formInput }) => {
  const { form } = useFormContext()
  const data = rowOf(form)
  return <ScheduleName id={String(data.id ?? "")} name={String(formInput.value ?? "")} url={String(data.url ?? "")} />
}

/* The rule, in one sentence: "Every Monday at 09:00". It replaced three
 * columns — the cadence, the hour, the day — that said an hourly schedule ran
 * "at 00:00" on no day at all. A cadence the runner does not know has no
 * sentence: it is drawn as the board says it. */
const ruleSaid = (schedule: Partial<Schedule>) => {
  const cadence = String(schedule.cadence ?? "")
  const rule = ruleOf({ cadence, at: String(schedule.at ?? ""), day: String(schedule.day ?? "") })
  return rule || (cadence ? t(cadence) : "")
}

const RuleCell: InputControllerComponentInterface = () => {
  const { form } = useFormContext()
  return <>{ruleSaid(rowOf(form))}</>
}

/* A date as the package's table says one, on one line: the package's own breaks
 * between the year's digits on a narrow screen. Nothing at all where there is
 * no date — "never yet" is an empty cell, not a dash in a badge. */
function Moment({ value }: { value: string }) {
  const date = value ? new Date(value) : null
  if (!date || Number.isNaN(date.getTime())) return null
  const day = new Intl.DateTimeFormat(locale()).format(date)
  const hour = date.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" })
  return (
    <Badge variant="secondary" className="whitespace-nowrap">
      {`${day} - ${hour}`}
    </Badge>
  )
}

/* When the next ticket is born. The server sends nothing for a schedule that is
 * off, since nothing will be; said here in a word rather than left blank, so an
 * empty cell is not read as a date that failed to load. */
function NextOf({ schedule }: { schedule: Partial<Schedule> }) {
  if (schedule.active !== true) return <span className="text-muted-foreground">{t("paused")}</span>
  return <Moment value={String(schedule.next ?? "")} />
}

const NextMoment: InputControllerComponentInterface = () => {
  const { form } = useFormContext()
  return <NextOf schedule={rowOf(form)} />
}

const LastMoment: InputControllerComponentInterface = ({ formInput }) => <Moment value={String(formInput.value ?? "")} />

/* The project a schedule points at, by name.
 *
 * The rows do not wait for the list of projects: the server writes the name
 * when it already knows it, and the page it points at always. A row whose name
 * is not known yet is drawn with a skeleton in its place, filled in once the
 * list the projects page reads has arrived — asked once, whatever the number
 * of rows. */
function ProjectOf({ said, page }: { said: string; page: string }) {
  const known = useProjects()
  const wanted = !said && Boolean(page)
  const [unread, setUnread] = React.useState(false)
  React.useEffect(() => {
    // A list that cannot be read leaves the cell empty, as a project with no
    // name would; the schedule itself is still there.
    if (wanted) void projectsOnce().catch(() => setUnread(true))
  }, [wanted])
  if (!wanted) return <>{said}</>
  if (!known) return unread ? null : <Skeleton className="h-3 w-20" />
  return <>{known.projects.find((project) => project.id === page)?.name ?? ""}</>
}

const ProjectName: InputControllerComponentInterface = ({ formInput }) => {
  const { form } = useFormContext()
  return <ProjectOf said={String(formInput.value ?? "")} page={String(rowOf(form).project_id ?? "")} />
}

/* The switch that turns a schedule on or off, and nothing else.
 *
 * Written as the one column it is, rather than left to the package: a cell it
 * is given a controller for is saved with the row's other cells — and only
 * those, so the hour and the day the rule column says in a sentence, and the
 * model a row does not show, would be written back empty. It moves as it is
 * pressed, and back if the board refuses. */
function ActiveSwitch({ id, on, name }: { id: string; on: boolean; name: string }) {
  const [pressed, setPressed] = React.useState<boolean | null>(null)
  const flip = async (wanted: boolean) => {
    setPressed(wanted)
    try {
      await api.saveSchedule(id, { active: wanted })
      const fresh = await load().catch(() => null)
      const found = fresh?.schedules.find((schedule) => schedule.id === id)
      if (found) schedules.onChange.publish({ data: item(found), action: ActionList.update })
    } catch (error) {
      toast.error(t("The schedule could not be saved"), { description: why(error) })
    } finally {
      setPressed(null)
    }
  }
  return (
    <Switch
      checked={pressed ?? on}
      disabled={pressed !== null}
      onCheckedChange={(wanted) => void flip(wanted)}
      aria-label={t("{{name}} on", { name })}
    />
  )
}

const ActiveCell: InputControllerComponentInterface = ({ formInput }) => {
  const { form } = useFormContext()
  const data = rowOf(form)
  const id = String(data.id ?? "")
  return id ? <ActiveSwitch id={id} on={formInput.value === true} name={String(data.name ?? "")} /> : null
}

/* The columns of the table, and the fields the calendar's preview lists.
 *
 * Read-only, every one: the switch writes its own column (`ActiveSwitch`).
 * `Next` and `Last` are dates; `Problem` is empty on every row that is fine,
 * which is what makes it worth a column of its own.
 *
 * Model and priority are not here: they are what the ticket inherits, they are
 * in the form that writes them, and two more columns would push the dates off
 * the edge of a pane that shares its screen with the console.
 *
 * On a phone there is no table: each schedule is a card (`ScheduleCards`).
 */
const rowForm: FormInterface = {
  inputs: {
    name: { label: "Schedule", readonly: true, controller: PageLink },
    rule: { label: "Rule", readonly: true, controller: RuleCell },
    active: { label: "On", readonly: true, controller: ActiveCell },
    next: { label: "Next", readonly: true, controller: NextMoment },
    last: { label: "Last", readonly: true, controller: LastMoment },
    project: { label: "Project", readonly: true, controller: ProjectName },
    problem: { label: "Problem", readonly: true },
    // Last, after the dates and the problem: an action at the right of the row.
    launch: { label: "", readonly: true, controller: RunNow },
  },
}

/* -- the list, at both widths --------------------------------------------- */

/* The package's table where it fits, and a card per schedule where it does
 * not: nine columns do not fit 390px, and folding them away left the dates
 * broken over two lines and the project and the problem nowhere. A card says
 * all of it, the switch and the run button in reach of a thumb. One or the
 * other, never both hidden by turns: a name drawn twice is a link found twice. */
const NARROW = "(max-width: 39.99rem)"

/** Whether the screen is too narrow for the table: a phone's. */
function useNarrow(): boolean {
  return React.useSyncExternalStore(
    (listener) => {
      const query = window.matchMedia(NARROW)
      query.addEventListener("change", listener)
      return () => query.removeEventListener("change", listener)
    },
    () => window.matchMedia(NARROW).matches
  )
}

function ScheduleRows({ rows = [] }: ListComponentPropsInterface<ScheduleItem>) {
  const narrow = useNarrow()
  if (!narrow) return <ListTable rows={rows} />
  return (
    <ul className="flex w-full flex-col gap-2">
      {rows.map((row) => (row.data ? <ScheduleCard key={row.data.id} schedule={row.data} /> : null))}
    </ul>
  )
}

function ScheduleCard({ schedule }: { schedule: ScheduleItem }) {
  const said = ruleSaid(schedule)
  return (
    <li data-schedule-card className="bg-card flex flex-col gap-2 rounded-xl border p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <span className="min-w-0 font-medium break-words">
          <ScheduleName id={schedule.id} name={schedule.name} url={schedule.url} />
        </span>
        <span className="flex shrink-0 items-center gap-1">
          <LaunchButton id={schedule.id} />
          <ActiveSwitch id={schedule.id} on={schedule.active} name={schedule.name} />
        </span>
      </div>
      {said ? <p className="text-muted-foreground">{said}</p> : null}
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted-foreground">{t("Next")}</dt>
        <dd>
          <NextOf schedule={schedule} />
        </dd>
        {schedule.last ? (
          <>
            <dt className="text-muted-foreground">{t("Last")}</dt>
            <dd>
              <Moment value={schedule.last} />
            </dd>
          </>
        ) : null}
        {schedule.project || schedule.project_id ? (
          <>
            <dt className="text-muted-foreground">{t("Project")}</dt>
            <dd className="min-w-0 break-words">
              <ProjectOf said={schedule.project} page={schedule.project_id} />
            </dd>
          </>
        ) : null}
      </dl>
      {schedule.problem ? <p className="text-destructive text-xs">{schedule.problem}</p> : null}
    </li>
  )
}

/* -- what sits around the list -------------------------------------------- */

/** How many of them are on, said where the list opens — and why nothing was read, where nothing was. */
function SchedulesTop() {
  const { drawn, problem } = useSchedules()
  useLayoutInTheAddress(SCHEDULES)
  return <SchedulesCount drawn={drawn} problem={problem} />
}

/* The window a schedule is written in, new or opened from the list: the one a
 * ticket opens in over the board, narrower — a form of a few rows, not a page
 * to read. The same window both ways, its title saying which: a new one, or
 * the one whose name is over the title, with the way to run it now beside the
 * way to its page. The schedule inside is the `update` view, as on its page. */
const SCHEDULE_WINDOW = "overflow-hidden sm:max-w-[620px] sm:rounded-2xl"
const SUBTITLE = "Ponos creates this ticket automatically, at the cadence you choose."

const newScheduleWindow = recordWindow({
  type: "schedule-new",
  fallbackTitle: "New recurring ticket",
  className: SCHEDULE_WINDOW,
  useHead: () => ({ title: t("New recurring ticket"), description: t(SUBTITLE) }),
})

const scheduleWindow = recordWindow({
  type: "schedule-window",
  fallbackTitle: "Edit the schedule",
  className: SCHEDULE_WINDOW,
  useHead: function useScheduleHead(id) {
    const { drawn } = useSchedules()
    return {
      eyebrow: drawn?.schedules.find((schedule) => schedule.id === id)?.name ?? "",
      title: t("Edit the schedule"),
      description: t(SUBTITLE),
      actions: id ? <LaunchButton id={id} /> : null,
    }
  },
})

function SchedulesCount({ drawn, problem }: LastRead) {
  if (problem)
    return (
      <Alert variant="destructive" className="mb-2">
        <AlertDescription>{problem}</AlertDescription>
      </Alert>
    )
  if (!drawn) return null
  const rows = drawn.schedules
  const active = rows.filter((schedule) => schedule.active && !schedule.problem).length
  return (
    <p className="text-muted-foreground mb-2 inline-flex items-center gap-1.5 font-mono text-[0.7rem]">
      <CalendarClock className="size-3.5" />
      {rows.length
        ? t("{{count}} of {{total}} on", {
            count: String(active),
            total: String(rows.length),
          })
        : t("nothing yet")}
    </p>
  )
}

/** One switch turns the whole calendar off, and a page of ticked rows that never fire is what it would otherwise read as. */
function SchedulesFoot() {
  const { drawn } = useSchedules()
  if (!drawn?.database || drawn.enabled) return null
  return (
    <Alert className="mt-4">
      {/* One paragraph, because the description lays its children out in a
          grid: two of them are two lines, and the sentence would start on the
          one after the key it is about. */}
      <AlertDescription>
        <p>
          <span className="font-mono">runner.schedule = false</span> —{" "}
          {t("none of this runs.")}
        </p>
      </AlertDescription>
    </Alert>
  )
}

/* Two ways this page has nothing to show, and they are two different things to
 * do about it: the workspace has no such database, or the database is there and
 * empty. The create button under the sentence is the package's, and it is gone
 * in the first case — `canCreate` answers for a board that has nowhere to write
 * a row to. */
function NoSchedule() {
  const { drawn } = useSchedules()
  const { filterContext } = useListViewContext()
  if (filtering(filterContext.filter))
    return (
      <EmptyState
        icon={SearchX}
        title={t("No schedule matches")}
        action={
          <Button variant="outline" size="sm" onClick={() => filterContext.resetFilter({})}>
            <X />
            {t("Clear the search")}
          </Button>
        }
      >
        {t("Other words, another project or another state, and they will be back.")}
      </EmptyState>
    )
  // Named rather than left blank: an empty parameter is not substituted, so the
  // sentence would show the placeholder itself. See `react-mini-i18n`.
  const page = drawn?.page || "Schedules"
  // A Markdown board has no database to write a row in: a schedule there is
  // a file, and the sentence that said "database" was Notion's.
  const markdown = drawn?.storage === "markdown"
  return drawn && !drawn.database ? (
    <EmptyState icon={CalendarOff} title={t("Nothing repeats here")}>
      {t("This workspace has no “{{page}}” page.", { page })}{" "}
      <code className="font-mono text-xs">ponos init &lt;page-url&gt;</code>{" "}
      {t("builds it.")}
    </EmptyState>
  ) : (
    <EmptyState robot="sleep" title={t("Nothing repeats here yet")}>
      {markdown
        ? t("A schedule written here is a ticket that comes back on its own.")
        : t("A row in the “{{page}}” database is a ticket that comes back.", { page })}
    </EmptyState>
  )
}

/* -- the calendar ---------------------------------------------------------- */

/* What the calendar lays out is not the rows. A row says one date — `Next` — and
 * a schedule that fires every day is on the calendar every day, so the rows are
 * unfolded into their launches first (`lib/occurrences.ts`, the runner's own
 * rule walked forward from the very `Next` the list shows): the ones to come,
 * and `Last` as the one that has happened, drawn greyed. A schedule that is
 * off has no launch to come, whatever date it was left with.
 *
 * An hourly one is twenty-four a day, which no cell holds: a day with four
 * launches or more of the same schedule is one event, "24 launches", and its
 * hours are in the window it opens.
 */
const PAST_COLOR = "#94a3b8"

interface Launch {
  id: string
  "@id": string
  title: string
  when: string
  color?: string
  kind: "past" | "upcoming"
  schedule: string
  times: number[]
  cadence: string
  at: string
  day: string
}

const ScheduleCalendar = ({ rows }: ListComponentPropsInterface<ScheduleItem>) => {
  const { drawn } = useSchedules()
  const zone = drawn?.timezone
  // Read when the calendar is first drawn, not with the page: the table is
  // what the list opens on, and its first load has a weight it answers for.
  const [walk, setWalk] = React.useState<typeof import("@/lib/occurrences") | null>(null)
  React.useEffect(() => {
    void import("@/lib/occurrences").then(setWalk)
  }, [])
  const launches = React.useMemo(() => {
    if (!walk) return []
    const found = rows.map((row) => row.data)
    const byId = new Map(found.map((schedule) => [schedule.id, schedule]))
    return walk.entries(found, Date.now(), walk.zoneOf(zone)).map((entry): RowInterface<Launch> => {
      const schedule = byId.get(entry.schedule)!
      const folded = entry.times.length > 1
      return {
        data: {
          id: entry.key,
          "@id": entry.key,
          title: folded
            ? t("{{count}} launches · {{name}}", { name: schedule.name, count: String(entry.times.length) })
            : schedule.name,
          when: new Date(entry.start).toISOString(),
          color: entry.kind === "past" ? PAST_COLOR : undefined,
          kind: entry.kind,
          schedule: schedule.id,
          times: entry.times,
          cadence: schedule.cadence,
          at: schedule.at,
          day: schedule.day,
        },
      }
    })
  }, [rows, zone, walk])
  return <ListCalendar rows={launches} />
}

const hour = (instant: number) =>
  new Date(instant).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })

/** What the window over a launch says: whether it has happened, when, and the way to the schedule. */
const LaunchPreview = ({ row }: RowComponentPropsInterface<Launch>) => {
  const launch = row?.data
  const open = useOpensOverTheList(schedules, "update", launch?.schedule ?? "")
  if (!launch) return null
  return (
    <div className="flex w-full flex-col gap-2 text-sm">
      <p className="text-muted-foreground text-xs">
        {launch.kind === "past" ? t("Last launch: it has happened.") : t("Due: not born yet.")}
        {launch.cadence ? ` ${t(launch.cadence)}` : ""}
      </p>
      {launch.times.length > 1 ? (
        <p className="font-mono text-xs leading-relaxed">{launch.times.map(hour).join(" · ")}</p>
      ) : null}
      <Link
        to={scheduleHref(launch.schedule)}
        onClick={open}
        className="text-primary underline-offset-2 hover:underline"
      >
        {t("Open the schedule")}
      </Link>
    </div>
  )
}

/* -- the search ------------------------------------------------------------ */

/* What the list last read, once it has: the projects the search offers are the
 * ones a schedule points at, and they come with the rows. */
function firstRead(): Promise<Schedules> {
  if (read.drawn) return Promise.resolve(read.drawn)
  return new Promise((resolve) => {
    const off = subscribe(() => {
      if (!read.drawn) return
      off()
      resolve(read.drawn)
    })
  })
}

/** A schedule's project by name: the server's when it knew it, the projects page's when that was read. */
const projectNameOf = (schedule: Schedule) =>
  schedule.project ||
  (projectsRead()?.projects.find((project) => project.id === schedule.project_id)?.name ?? "")

/* The search over the list, as the projects have theirs: the words of a name,
 * a project or a rule, one of the projects the schedules point at, and on or
 * paused. The labels are for a screen reader; the boxes say what they are. */
// Positioned, so the label kept for a screen reader stays inside the bar
// that scrolls on a phone: three fields are wider than 390px, and a label
// placed past the bar's edge widened the whole page.
const FILTER = "relative [&_[data-slot=field-label]]:sr-only"

const formFilter: FormInterface = {
  inputs: {
    q: {
      label: "Search",
      className: FILTER,
      get placeholder() {
        return t("Search a schedule")
      },
    },
    project: {
      label: "Project",
      className: FILTER,
      get placeholder() {
        return t("All projects")
      },
      controller: SelectInputController,
      getValueOptions: async () => {
        const drawn = await firstRead()
        // Their names may need the projects page: asked once, and a list that
        // cannot be read leaves the names the server wrote.
        if (drawn.schedules.some((schedule) => schedule.project_id && !schedule.project))
          await projectsOnce().catch(() => undefined)
        const pages = new Map<string, string>()
        for (const schedule of drawn.schedules)
          if (schedule.project_id) pages.set(schedule.project_id, projectNameOf(schedule) || schedule.project_id)
        return [
          { value: "", label: t("All projects") },
          ...[...pages]
            .sort(([, one], [, other]) => one.localeCompare(other))
            .map(([value, label]) => ({ value, label })),
        ]
      },
    },
    state: {
      label: "State",
      className: FILTER,
      get placeholder() {
        return t("On or paused")
      },
      controller: SelectInputController,
      getValueOptions: async () => [
        { value: "", label: t("On or paused") },
        ...STATES.map((state) => ({ value: state, label: state === "on" ? t("on") : t("paused") })),
      ],
    },
  },
}

/* -- the declaration ------------------------------------------------------ */

export const schedules = createViewResource<ScheduleItem, ScheduleWrite>(SCHEDULES, {
  name: "Schedules",
  path: "/api/schedules",
  icon: CalendarClock,
  // A row is opened in its form, and never deleted — unticking it stops it. A
  // new one is offered where the board has a database to write it to.
  permissions: {
    read: false,
    create: () => Boolean(read.drawn?.database),
    delete: false,
    export: false,
  },
  repository: {
    getCollection: async (filter) => {
      const fresh = await load()
      return {
        data: createResourceCollection({
          id: "/api/schedules",
          items: fresh.schedules
            .filter((schedule) =>
              keeps({ ...schedule, project: projectNameOf(schedule), rule: ruleSaid(schedule) }, filter)
            )
            .map(item),
        }),
      } as never
    },
    // Asked of the server every time, even for a row the list holds: the list
    // carries no body — twenty rows would be twenty pages read — and the form
    // this feeds is the one that writes it.
    getItem: async ({ id }) => {
      try {
        return { data: item(await api.schedule(String(id))) }
      } catch (error) {
        if (error instanceof ApiError && error.status === 404)
          throw new Error(t("This schedule is no longer on the board."))
        throw error
      }
    },
    updateItem: async (patch) => {
      const id = String(patch.id ?? "")
      // Written field by field rather than as the row arrived: a row carries the
      // three columns a pass writes back, and the project it points at as a name
      // rather than as the page the column holds. The body only when the row
      // came with one — the switch in the list saves a row read without it, and
      // an absent body is not an empty page.
      await api.saveSchedule(id, {
        name: patch.name ?? "",
        cadence: patch.cadence ?? "",
        at: patch.at ?? "",
        day: patch.day ?? "",
        active: patch.active === true,
        model: patch.model ?? "",
        priority: readScore(patch.priority) ?? "",
        type: patch.type ?? "",
        subtype: patch.subtype ?? "",
        ...(patch.body === undefined ? {} : { body: patch.body }),
      })
      const fresh = await load()
      const found = fresh.schedules.find((schedule) => schedule.id === id)
      return {
        data: found ? item({ ...found, body: patch.body }) : (patch as unknown as ScheduleItem),
      }
    },
    createItem: async (fresh) => {
      const made = await api.createSchedule({
        name: fresh.name ?? "",
        cadence: fresh.cadence ?? "",
        at: fresh.at ?? "",
        day: fresh.day ?? "",
        model: fresh.model ?? "",
        priority: readScore(fresh.priority) ?? "",
        type: fresh.type ?? "",
        subtype: fresh.subtype ?? "",
        ...(fresh.body ? { body: fresh.body } : {}),
      })
      // The server writes a new row unticked, whatever it is sent; "Turn on
      // right away" is the switch of the list, pressed for you once it exists.
      if (fresh.active === true) await api.saveSchedule(made.id, { active: true })
      const after = await load()
      const found = after.schedules.find((schedule) => schedule.id === made.id)
      return { data: found ? item(found) : ({ ...fresh, ...made } as unknown as ScheduleItem) }
    },
    removeItem: async () => {
      throw new Error("a schedule is not deleted from the console; unticking it stops it")
    },
  },
  views: {
    list: {
      // The table's columns, on the list alone: a form declared at the root is
      // merged into every action's, and the create form would have grown them.
      form: rowForm,
      components: {
        // Declared on the list rather than on the view every action inherits: a
        // `top` posted there is drawn over the create form too, and the count
        // of what is on belongs to the page, not to the form over it.
        top: SchedulesTop,
        bottom: SchedulesFoot,
        empty: NoSchedule,
      },
      // What a schedule is, without naming where it is kept: the same console
      // draws a Notion workspace and a directory of Markdown files.
      description: "A row says what to make and how often; when the moment comes the runner writes the ticket into the ready column and steps back.",
      // The switch in the row is one gesture, the name opening the form in a
      // window is the other: no button of the package's beside them.
      rowActions: [],
      // The search is the package's own: it lives in the address (`q`,
      // `project`, `state`), and the rows are kept by `keeps`, as the list is read.
      filters: formFilter,
      /* The two layouts. Their labels go through the dictionary as the tabs
       * are drawn, and their address is their type: `table`, `calendar`, in
       * every language. At the width of the page, as the board and the
       * projects are. */
      layouts: [
        layout.table({ label: "table", fullWidth: true, components: { list: ScheduleRows } }),
        // Typed against the launches `ScheduleCalendar` hands the package, not
        // against the rows — hence the cast into the rows' list of layouts.
        layout.calendar<Launch>({
          label: "calendar",
          fullWidth: true,
          dateField: "when",
          titleField: "title",
          colorField: "color",
          // The month, because that is the span a cadence is read in — the day
          // and the week are a tab away, on the package's own switch. The whole
          // day in those two: a launch at 03:00 is not one to leave off the grid.
          mode: "month",
          hourStart: 0,
          hourEnd: 23,
          getIcon: (row: RowInterface<Record<string, unknown>>) =>
            row.data?.kind === "past" ? CalendarCheck : CalendarClock,
          components: { list: ScheduleCalendar as never, row: LaunchPreview as never },
        }) as never,
      ],
    },
    create: {
      title: "New recurring ticket",
      form: createForm,
      // Over the list rather than instead of it — the list behind is what says
      // whether the row is a duplicate of one that already fires — and in the
      // middle of it, in the window an opened schedule is edited in.
      open: newScheduleWindow,
      buttonLabel: "New schedule",
    },
    update: {
      title: "Edit the schedule",
      form: editForm,
      // Over the list, in the window a ticket opens in over the board; its
      // address alone is the schedule's page.
      open: scheduleWindow,
      components: { top: LaunchOnThePage },
    },
  },
})

/** Where the schedules are, in the layout they were last worked in. */
export const schedulesHref = () =>
  generateLinkByResource({
    resource: schedules,
    resourceAction: ActionList.list,
    viewVariantId: layoutOf(SCHEDULES),
  })

/** A schedule's own page: its form, as the window over the list draws it. */
const scheduleHref = (id: string) =>
  generateLinkByResource({ resource: schedules, resourceAction: ActionList.update, id })
