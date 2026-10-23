import * as React from "react"
import {
  Link,
  ListCalendar,
  ListTable,
  type ListComponentPropsInterface,
  type RowComponentPropsInterface,
  type RowInterface,
} from "react-resource-view"

import { useOpensOverTheList } from "@/components/console/record-window"
import { t } from "@/lib/i18n"
import { ideasHref } from "@/resources/ideas"
import {
  ActiveSwitch,
  DeleteButton,
  LaunchButton,
  Moment,
  NextOf,
  ProjectOf,
  ScheduleName,
  ruleSaid,
  scheduleHref,
  schedules,
  useSchedules,
  type ScheduleItem,
} from "@/resources/schedules"

/* Two of the schedules' layouts, read when one is first drawn rather than with
 * the page — the list opens beside its panel, and its first load has a weight
 * it answers for: see `resources/schedules.tsx`. */

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

export function ScheduleRows({ rows = [] }: ListComponentPropsInterface<ScheduleItem>) {
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
          <DeleteButton id={schedule.id} name={schedule.name} />
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

export interface Launch {
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
  /** The search for ideas, which is drawn here to be seen and not to be changed. */
  ideas?: boolean
}

export const ScheduleCalendar = ({ rows }: ListComponentPropsInterface<ScheduleItem>) => {
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
    const pass = drawn?.ideas_pass
    const own = walk.entries(found, Date.now(), walk.zoneOf(zone))
    // The scheduled search for ideas: the server walks its rule (a cron line has no
    // cadence to walk here) and the page draws the passes it is given, read only.
    const searching = pass && (pass.active || pass.last) ? walk.listed(pass.active ? pass.upcoming : [], pass.last) : []
    const ideas = searching.map((entry): RowInterface<Launch> => {
      const name = t("Ponos finds ideas")
      const several = entry.times.length > 1
      return {
        data: {
          id: entry.key,
          "@id": entry.key,
          title: several ? t("{{count}} launches · {{name}}", { name, count: String(entry.times.length) }) : name,
          when: new Date(entry.start).toISOString(),
          color: entry.kind === "past" ? PAST_COLOR : undefined,
          kind: entry.kind,
          schedule: entry.schedule,
          times: entry.times,
          cadence: "",
          at: "",
          day: "",
          ideas: true,
        },
      }
    })
    const calendar = own.map((entry): RowInterface<Launch> => {
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
    return [...calendar, ...ideas]
  }, [rows, zone, walk, drawn?.ideas_pass])
  return <ListCalendar rows={launches} />
}

const hour = (instant: number) =>
  new Date(instant).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })

/** What the window over a launch says: whether it has happened, when, and the way to the schedule. */
export const LaunchPreview = ({ row }: RowComponentPropsInterface<Launch>) => {
  const launch = row?.data
  const { drawn } = useSchedules()
  const open = useOpensOverTheList(schedules, "update", launch?.schedule ?? "")
  if (!launch) return null
  if (launch.ideas)
    return (
      <div className="flex w-full flex-col gap-2 text-sm" data-slot="ideas-pass-launch">
        <p className="text-muted-foreground text-xs">
          {launch.kind === "past" ? t("Last pass: it has happened.") : t("Due: Ponos looks for ideas then.")}
        </p>
        {launch.times.length > 1 ? (
          <p className="font-mono text-xs leading-relaxed">{launch.times.map(hour).join(" · ")}</p>
        ) : null}
        <Link to={ideasHref()} className="text-primary underline-offset-2 hover:underline">
          {t("Change it in the Ideas page's Settings")}
        </Link>
      </div>
    )
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
      <span className="flex">
        <DeleteButton id={launch.schedule} name={drawn?.schedules.find((schedule) => schedule.id === launch.schedule)?.name ?? ""} className="w-auto px-2" />
      </span>
    </div>
  )
}
