import * as React from "react"
import { ArrowLeft, ExternalLink, GitPullRequest, Pencil } from "lucide-react"
import { ActionList } from "react-data-form"
import { Link, ViewResourceContextProvider } from "react-resource-view"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { money, number } from "@/lib/numbers"
import { locale } from "@/lib/recurrence"
import type { Schedule, ScheduleActivity, ScheduleRun, ScheduleTicket, StatisticsDay } from "@/lib/types"
import { cn } from "@/lib/utils"
import { projectHref, useWide } from "@/resources/projects"
import {
  ActiveSwitch,
  DeleteButton,
  LaunchButton,
  Moment,
  NextOf,
  ProjectOf,
  ruleSaid,
  scheduleHref,
  schedules,
  useLeaveSchedule,
  usePickedSchedule,
  useScheduleTab,
  useSchedules,
} from "@/resources/schedules"
import { ticketHref, tickets } from "@/resources/tickets"

import { ActivityChart } from "./activity-chart"
import { EmptyState } from "./empty-state"
import { Eyebrow, Panel, Tile } from "./frame"
import { useOpensOverTheList } from "./record-window"
import { Robot } from "./robot"
import { SEED, ago, columnTitle, lasted, reachable } from "./ticket-bits"

/* What sits beside the list of schedules: the one picked, as the projects have
 * theirs (see `project-panel.tsx`) — its header and its actions, its figures,
 * then its tabs under them: the tickets it made, its passes, and its settings.
 *
 * Which one is picked is said by the address (`&schedule=<id>`), so a link
 * opens on it and a reload keeps it. Wide, the panel is a column beside the
 * list, sticky and scrolled on its own (see `index.css`); narrower, it is the
 * whole screen over the list, with a way back to it.
 *
 * What a schedule made is asked of the server when it is picked, and again
 * when its `Last` moves — a launch, a pass: see `web/lineage.py`, which also
 * says how the tickets born before Ponos kept the link are found.
 */

export function ScheduleAside() {
  const t = useT()
  const id = usePickedSchedule()
  const wide = useWide()
  const { drawn } = useSchedules()
  const found = drawn?.schedules.find((schedule) => schedule.id === id)
  const leave = useLeaveSchedule()
  const aside = React.useRef<HTMLElement>(null)
  // The panel scrolls on its own: a schedule picked starts at its header.
  React.useEffect(() => {
    aside.current?.scrollTo({ top: 0 })
  }, [id])
  if (!wide)
    return found ? (
      <div data-schedule-screen className="bg-background fixed inset-0 z-40 overflow-y-auto px-3 pt-3 pb-24">
        <Button variant="ghost" size="sm" className="mb-2 -ml-1" onClick={leave} data-schedule-back>
          <ArrowLeft />
          {t("Schedules")}
        </Button>
        <SchedulePanel key={id} schedule={found} />
      </div>
    ) : null
  return (
    <aside ref={aside} data-schedules-aside className="flex min-w-0 flex-col gap-4">
      {found ? (
        <SchedulePanel key={id} schedule={found} />
      ) : (
        <div className="bg-card rounded-xl border">
          <EmptyState robot="idle" title={t("Pick a schedule")}>
            {t("Its tickets, what they cost, and every pass it made are shown here.")}
          </EmptyState>
        </div>
      )}
    </aside>
  )
}

/** What a schedule made, read when it is picked and again when its last pass moves. */
function useActivity(id: string, last: string) {
  const [read, setRead] = React.useState<{ activity?: ScheduleActivity; problem?: string } | null>(null)
  React.useEffect(() => {
    let current = true
    api
      .scheduleActivity(id)
      .then((activity) => current && setRead({ activity }))
      .catch((error) => current && setRead({ problem: why(error) }))
    return () => {
      current = false
    }
  }, [id, last])
  return read
}

export function SchedulePanel({ schedule }: { schedule: Schedule }) {
  const t = useT()
  const read = useActivity(schedule.id, schedule.last)
  const activity = read?.activity
  return (
    <section data-schedule-panel className="bg-card flex min-w-0 flex-col gap-5 rounded-xl border p-4">
      <ScheduleHead schedule={schedule} />
      {schedule.problem ? (
        <Alert variant="destructive">
          <AlertDescription>{schedule.problem}</AlertDescription>
        </Alert>
      ) : null}
      {read?.problem ? (
        <p className="text-tr-amber border-tr-amber/30 bg-tr-amber/10 rounded-xl border px-4 py-2.5 text-sm">
          {read.problem}
        </p>
      ) : null}
      {activity ? (
        <Figures schedule={schedule} activity={activity} />
      ) : read?.problem ? null : (
        <p className="text-muted-foreground flex items-center gap-3 text-sm">
          <Robot state="thinking" size={32} />
          {t("Counting the tickets…")}
        </p>
      )}
      <ScheduleTabs schedule={schedule} activity={activity} />
    </section>
  )
}

/* -- the header ------------------------------------------------------------- */

/* The name, and under it what it is: the rule in a sentence, the project it
 * works for — a link to its page — and the way to its page on the board. On the
 * right, what can be done to it: the switch that pauses it, run it now, edit
 * it in its window, delete it. */
function ScheduleHead({ schedule }: { schedule: Schedule }) {
  const t = useT()
  const open = useOpensOverTheList(schedules, "update", schedule.id, `schedule=${schedule.id}`)
  const rule = ruleSaid(schedule)
  return (
    <header data-slot="admin-header" className="w-full">
      <div className="border-border flex flex-wrap items-end gap-x-6 gap-y-3 border-b pb-4">
        <div className="min-w-0 flex-1">
          <Eyebrow>{t("Schedule")}</Eyebrow>
          <h2 className="text-xl font-semibold tracking-tight break-words">
            {schedule.name}
          </h2>
          <p className="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            {rule ? <span data-schedule-rule>{rule}</span> : null}
            {schedule.project_id ? (
              <Link
                to={projectHref(schedule.project_id)}
                data-schedule-project
                className="hover:text-foreground underline-offset-2 hover:underline"
              >
                <ProjectOf said={schedule.project} page={schedule.project_id} />
              </Link>
            ) : null}
            {reachable(schedule.url) ? (
              <a
                href={schedule.url}
                target="_blank"
                rel="noreferrer noopener"
                className="hover:text-foreground inline-flex items-center gap-1 text-xs underline-offset-2 hover:underline"
              >
                {t("Open the schedule's page on the board")}
                <ExternalLink className="size-3" />
              </a>
            ) : null}
          </p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 md:w-auto">
          <label className="mr-1 flex items-center gap-2 text-sm">
            <ActiveSwitch id={schedule.id} on={schedule.active} name={schedule.name} />
            <span className={cn(!schedule.active && "text-muted-foreground")}>
              {schedule.active ? t("Active") : t("Paused")}
            </span>
          </label>
          <LaunchButton id={schedule.id} labelled />
          <Link
            to={scheduleHref(schedule.id)}
            onClick={open}
            data-schedule-edit
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "bg-card")}
          >
            <Pencil />
            {t("Edit")}
          </Link>
          <DeleteButton id={schedule.id} name={schedule.name} labelled />
        </div>
      </div>
    </header>
  )
}

/* -- the figures ------------------------------------------------------------ */

const dollars = (value: number) => money(value, value >= 100 ? 0 : 2)
const percent = (rate: number) => `${Math.round(rate * 100)} %`

/* The columns a schedule's tickets are told by: the four the eye looks for,
 * and failed apart from cancelled — one went wrong, the other was let go. */
const STANDING: { key: string; label: string; columns: string[]; seed: string }[] = [
  { key: "done", label: "Done", columns: ["done"], seed: "bg-muted-foreground" },
  {
    key: "running",
    label: "In progress",
    columns: ["draft", "ready", "running", "review", "validated"],
    seed: SEED.running,
  },
  { key: "blocked", label: "Blocked", columns: ["blocked"], seed: SEED.blocked },
  { key: "failed", label: "Failed", columns: ["failed"], seed: SEED.failed },
  { key: "cancelled", label: "Cancelled", columns: ["cancelled"], seed: SEED.cancelled },
]

const shortDay = (point: StatisticsDay) =>
  new Date(`${point.day}T00:00:00`).toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" })

function Figures({ schedule, activity }: { schedule: Schedule; activity: ScheduleActivity }) {
  const t = useT()
  const { totals } = activity
  const counts = new Map(activity.statuses.map((status) => [status.key as string, status.count]))
  // The chart adds up what the weeks cost, as the dashboard's does its days.
  const points = React.useMemo(() => {
    let spent = 0
    return activity.weeks.map((week): StatisticsDay => {
      spent += week.cost
      return { day: week.week, created: week.tickets, closed: week.done, open: week.open, cost: spent }
    })
  }, [activity.weeks])
  return (
    <div data-schedule-figures className="flex min-w-0 flex-col gap-2">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Tile label={t("Tickets")} value={number(totals.tickets)} note={t("made by this schedule")}>
          <p data-schedule-statuses className="mt-1.5 flex flex-wrap gap-x-2.5 gap-y-0.5 text-[0.7rem] tabular-nums">
            {STANDING.map((standing) => {
              const count = standing.columns.reduce((sum, column) => sum + (counts.get(column) ?? 0), 0)
              return count ? (
                <span key={standing.key} className="inline-flex items-center gap-1" title={t(standing.label)}>
                  <span className={cn("size-1.5 rounded-full", standing.seed)} />
                  {/* The column's name, then the count: "Done 3" agrees in
                      every language, where "3 done" is "3 terminés" in one. */}
                  {t(standing.label)} {count}
                </span>
              ) : null
            })}
          </p>
        </Tile>
        <Tile
          label={t("Spent")}
          value={dollars(totals.cost)}
          note={
            totals.average_cost === null
              ? t("no session has cost anything yet")
              : t("{{cost}} per run on average", { cost: dollars(totals.average_cost) })
          }
          more={t("The Cost of every ticket it made, added up; the average is over the tickets that have one.")}
        />
        <Tile
          label={t("Average duration")}
          value={totals.average_duration === null ? "—" : lasted(totals.average_duration)}
          note={t("per ticket, all its sessions counted")}
        />
        <Tile
          label={t("Success")}
          value={totals.success === null ? "—" : percent(totals.success)}
          note={t("done, of the tickets that finished")}
          more={t("Done over done, failed and cancelled: a ticket still open has not said yet how it ends.")}
        />
        <Tile
          label={t("Last run")}
          value={<Moment value={schedule.last} />}
          note={schedule.last ? ago(schedule.last) : t("never yet")}
        />
        <Tile label={t("Next run")} value={<NextOf schedule={schedule} />} />
      </div>
      {points.length ? (
        <Panel eyebrow={t("Tickets and cost, by week")} className="min-w-0" bodyClassName="pb-3">
          <ActivityChart
            points={points}
            labels={{ created: t("Tickets"), closed: t("Done"), open: t("Still open"), spent: t("Spent per week") }}
            label={t("Tickets made each week, how many of them are done or still open, and what they cost")}
            day={shortDay}
            longDay={(point) => t("Week of {{day}}", { day: shortDay(point) })}
            height={180}
          />
        </Panel>
      ) : null}
    </div>
  )
}

/* -- the tabs ---------------------------------------------------------------- */

/* Under the figures, as on a project's page: the tickets it made first — what
 * it is opened for — then its passes, then its settings, written on the spot.
 * The tab is kept in the address with the schedule (`&tab=runs`). */
const TABS = ["tickets", "runs", "settings"] as const
type Tab = (typeof TABS)[number]

function ScheduleTabs({ schedule, activity }: { schedule: Schedule; activity?: ScheduleActivity }) {
  const t = useT()
  const [named, pick] = useScheduleTab()
  const tab: Tab = TABS.includes(named as Tab) ? (named as Tab) : "tickets"
  return (
    <Tabs value={tab} onValueChange={pick} className="gap-4">
      <TabsList className="w-full sm:w-fit">
        <TabsTrigger value="tickets" data-slot="schedule-tickets-tab">
          {t("Tickets")}
        </TabsTrigger>
        <TabsTrigger value="runs" data-slot="schedule-runs-tab">
          {t("Runs")}
        </TabsTrigger>
        <TabsTrigger value="settings" data-slot="schedule-settings-tab">
          {t("Settings")}
        </TabsTrigger>
      </TabsList>
      <TabsContent value="tickets">
        {activity ? <TicketList schedule={schedule} activity={activity} /> : <Waiting />}
      </TabsContent>
      <TabsContent value="runs">{activity ? <RunList schedule={schedule} activity={activity} /> : <Waiting />}</TabsContent>
      <TabsContent value="settings">
        {/* The window's own form, drawn in the tab rather than over the list:
            the same fields, the same save. */}
        <div data-schedule-settings>
          <ViewResourceContextProvider resource={schedules} resourceAction={ActionList.update} id={schedule.id} />
        </div>
      </TabsContent>
    </Tabs>
  )
}

const Waiting = () => (
  <div className="flex flex-col gap-2">
    <Skeleton className="h-10 w-full" />
    <Skeleton className="h-10 w-full" />
  </div>
)

const dated = (at: string) => {
  const date = at ? new Date(at) : null
  if (!date || Number.isNaN(date.getTime())) return ""
  return `${new Intl.DateTimeFormat(locale()).format(date)} - ${date.toLocaleTimeString(locale(), {
    hour: "2-digit",
    minute: "2-digit",
  })}`
}

/** A column, as its dot and its name. */
function Standing({ column }: { column: string }) {
  if (!column) return null
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span className={cn("size-1.5 rounded-full", SEED[column] ?? "bg-muted-foreground")} />
      {columnTitle(column)}
    </span>
  )
}

function TicketList({ schedule, activity }: { schedule: Schedule; activity: ScheduleActivity }) {
  const t = useT()
  if (!activity.tickets.length)
    return (
      <EmptyState robot="sleep" title={t("No ticket yet")}>
        {schedule.active
          ? t("The first one is born at the next run, or now with “Run now”.")
          : t("Turn it on, or try it once with “Run now”.")}
      </EmptyState>
    )
  return (
    <div className="flex flex-col gap-3">
      <ul data-schedule-tickets className="overflow-hidden rounded-md border">
        {activity.tickets.map((ticket) => (
          <TicketRow key={ticket.id} schedule={schedule.id} ticket={ticket} />
        ))}
      </ul>
      {activity.matched ? (
        <p className="text-muted-foreground text-xs">
          {t(
            activity.matched > 1
              ? "{{count}} of them were recognised by their title and their date: they were made before Ponos kept the link."
              : "{{count}} of them was recognised by its title and its date: it was made before Ponos kept the link.",
            { count: String(activity.matched) }
          )}
        </p>
      ) : null}
    </div>
  )
}

/* One ticket: its title, the way into its window over the list — the schedule
 * kept in the address, so the panel is still there behind it and when it
 * closes — and under it where it stands, when it was born, what it cost and
 * took, and its pull request. */
function TicketRow({ schedule, ticket }: { schedule: string; ticket: ScheduleTicket }) {
  const t = useT()
  const open = useOpensOverTheList(tickets, "read", ticket.id, `schedule=${schedule}`)
  return (
    <li data-schedule-ticket className="flex min-w-0 flex-col gap-1 border-b px-3 py-2.5 text-sm last:border-b-0">
      <Link to={ticketHref(ticket.id)} onClick={open} className="truncate font-medium hover:underline" title={ticket.title}>
        {ticket.title}
      </Link>
      <span className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs tabular-nums">
        <Standing column={ticket.column} />
        <span title={ticket.created}>{dated(ticket.created)}</span>
        {ticket.cost !== null ? <span>{dollars(ticket.cost)}</span> : null}
        {ticket.duration ? <span>{lasted(ticket.duration)}</span> : null}
        {reachable(ticket.pull_request) ? (
          <a
            href={ticket.pull_request}
            target="_blank"
            rel="noreferrer noopener"
            className="hover:text-foreground inline-flex items-center gap-1 underline-offset-2 hover:underline"
          >
            <GitPullRequest className="size-3.5" />
            {t("Pull request")}
          </a>
        ) : null}
      </span>
    </li>
  )
}

const OUTCOME: Record<ScheduleRun["outcome"], { label: string; variant: "secondary" | "outline" | "destructive" }> = {
  born: { label: "Ticket created", variant: "secondary" },
  launched: { label: "Run by hand", variant: "secondary" },
  skipped: { label: "Skipped", variant: "outline" },
  failed: { label: "Error", variant: "destructive" },
}

function RunList({ schedule, activity }: { schedule: Schedule; activity: ScheduleActivity }) {
  const t = useT()
  return (
    <div className="flex flex-col gap-3">
      {activity.runs.length ? (
        <ul data-schedule-runs className="overflow-hidden rounded-md border">
          {activity.runs.map((run, index) => (
            <RunRow key={`${run.at}-${index}`} schedule={schedule.id} run={run} />
          ))}
        </ul>
      ) : (
        <EmptyState robot="sleep" title={t("No run yet")}>
          {t("Every pass that makes a ticket, or makes none, is written here.")}
        </EmptyState>
      )}
      <p className="text-muted-foreground text-xs">
        {activity.since
          ? t("Passes that made no ticket are kept since {{date}}.", { date: dated(activity.since) })
          : t("Passes that made no ticket are kept from this version on: the ones before were never recorded.")}
      </p>
    </div>
  )
}

function RunRow({ schedule, run }: { schedule: string; run: ScheduleRun }) {
  const t = useT()
  const open = useOpensOverTheList(tickets, "read", run.ticket, `schedule=${schedule}`)
  const said = OUTCOME[run.outcome]
  return (
    <li
      data-schedule-run={run.outcome}
      className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-1 border-b px-3 py-2.5 text-sm last:border-b-0 sm:grid-cols-[9.5rem_auto_minmax(0,1fr)]"
    >
      <span className="text-muted-foreground text-xs tabular-nums sm:pt-0.5" title={run.at}>
        {dated(run.at)}
      </span>
      <span>
        <Badge variant={said.variant} className="whitespace-nowrap">
          {t(said.label)}
        </Badge>
      </span>
      <span className="col-span-2 flex min-w-0 flex-col gap-0.5 sm:col-span-1">
        {run.ticket ? (
          <>
            <Link to={ticketHref(run.ticket)} onClick={open} className="truncate hover:underline" title={run.title}>
              {run.title || run.ticket}
            </Link>
            <span className="text-muted-foreground flex flex-wrap items-center gap-x-3 text-xs">
              <Standing column={run.column} />
              {run.inferred ? <span>{t("said from the ticket")}</span> : null}
            </span>
          </>
        ) : (
          <span className="text-muted-foreground text-xs">
            {run.outcome === "skipped" ? t("The ticket of the previous run was still open.") : run.reason}
          </span>
        )}
      </span>
    </li>
  )
}
