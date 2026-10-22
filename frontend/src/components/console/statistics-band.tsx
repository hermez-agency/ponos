import * as React from "react"
import { format, subDays } from "date-fns"
import { ArrowDown, ArrowRight, ArrowUp, ChevronDown, ChevronRight, ChevronUp } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, why } from "@/lib/api"
import { currentBoard } from "@/lib/board-store"
import { currentLanguage, useT } from "@/lib/i18n"
import { byProject, bySubtype, regression, stacks, trend } from "@/lib/made"
import { money, number } from "@/lib/numbers"
import type { BlockFamily, Made, Statistics, StatisticsDay } from "@/lib/types"
import { cn } from "@/lib/utils"

import { Eyebrow, Panel } from "./frame"
import { ActivityChart } from "./activity-chart"
import { Robot } from "./robot"
import {
  FAMILY_ICON,
  blockSaid,
  capital,
  columnTitle,
  familyColor,
  lasted,
  subtypeColor,
  SubtypeDot,
  subtypeOf,
} from "./ticket-bits"

/* What the runner got through, over a period — at the top of the dashboard.
 *
 * It was a page of its own, and a page nobody opened: the figures are read
 * with the board under them or not at all. So they came to the board as a band
 * that keeps to a glance — four numbers, the activity, the projects — and
 * folds away into one line for whoever came for the cards. The figures are the
 * server's (`web/statistics.py`, which also says how a closing is dated); this
 * band asks for a period and draws.
 *
 * The same band is a project's page's, asked for that project alone
 * (`project`): the cards and the charts are the ones above over its
 * tickets, and the third panel — "by project" says nothing about one project —
 * is where its tickets stand, by column. It is the one split that is already
 * in the figures and that a project's page answers at a glance: how much of
 * the work is waiting, running, in review or done. Its own folded state and
 * its own period, so a project's page does not move the dashboard's.
 *
 * "Open" on a card is the last point of its curve — the evening of the last
 * day — so a period that ends today says what the board says, not a sum over
 * the week nobody could check against it.
 *
 * Beside the activity, what the tickets created were: features or bugs, a
 * project moving on or mending what it broke (`lib/made.ts`). Filtered by type
 * and by project on the spot — the cells came with the figures.
 */

type Range = "24h" | "7d" | "30d" | "all" | "custom"

const RANGES: { key: Range; label: string }[] = [
  { key: "24h", label: "24 h" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "all", label: "All" },
  { key: "custom", label: "Custom" },
]

const ISO = "yyyy-MM-dd"

// What `web/statistics.py` still draws: a period of 731 days or more is refused.
const LONGEST = 730

/* The days before today a range reaches back. The server counts in days, not
 * hours, so the last 24 hours are yesterday and today: a ticket closed last
 * night is in them, which today alone would have left out. */
const BACK: Record<Exclude<Range, "all" | "custom">, number> = { "24h": 1, "7d": 6, "30d": 29 }

/** The day the oldest ticket on the board was created, as far back as the server goes. */
function oldest(today: Date): Date {
  const limit = subDays(today, LONGEST)
  const created = (currentBoard()?.tickets ?? [])
    .map((ticket) => new Date(ticket.created).getTime())
    .filter((time) => !Number.isNaN(time))
  const first = created.length ? new Date(Math.min(...created)) : limit
  return first < limit ? limit : first
}

/** The first and last day of a range that ends today. */
function span(range: Exclude<Range, "custom">, today: Date): { from: string; to: string } {
  const first = range === "all" ? oldest(today) : subDays(today, BACK[range])
  return { from: format(first, ISO), to: format(today, ISO) }
}

/* The period picked, outside the band: a trip to a ticket and back should not
 * put the dashboard back on its week. */
const kept = new Map<string, { range: Range; from: string; to: string }>()

/* The figures last read, by scope and period, for a minute: a project's band is
 * drawn in the panel beside the list and on the page alone, and going from one
 * to the other — or back to a project picked a moment ago — draws them at once
 * rather than asking the same question twice. */
const FRESH = 60_000
const answered = new Map<string, { at: number; figures: Statistics }>()
const question = (scope: string, from: string, to: string) => `${scope}|${from}|${to}`

/* Whether the band is folded, as the last person at this browser left it. Open
 * by default: the figures are why the dashboard is more than the board. */
const FOLDED_KEY = "ponos-dashboard-statistics"
const PROJECT_FOLDED_KEY = "ponos-project-statistics"

function useFolded(key: string) {
  const [folded, setFolded] = React.useState(() => {
    try {
      return localStorage.getItem(key) === "folded"
    } catch {
      return false
    }
  })
  const change = React.useCallback(
    (next: boolean) => {
      setFolded(next)
      try {
        localStorage.setItem(key, next ? "folded" : "open")
      } catch {
        // Storage off: the choice lasts as long as the tab, which is still one.
      }
    },
    [key]
  )
  return [folded, change] as const
}

/* Whether the blocks panel is shown, one answer for the dashboard and the
 * projects' pages: it is a lot of room for something read now and then, so it
 * stays folded until somebody asks, and the answer is kept. */
const BLOCKS_KEY = "ponos-statistics-blocks"

function useBlocksShown() {
  const [shown, setShown] = React.useState(() => {
    try {
      return localStorage.getItem(BLOCKS_KEY) === "shown"
    } catch {
      return false
    }
  })
  const change = React.useCallback((next: boolean) => {
    setShown(next)
    try {
      localStorage.setItem(BLOCKS_KEY, next ? "shown" : "hidden")
    } catch {
      // Storage off: the choice lasts as long as the tab.
    }
  }, [])
  return [shown, change] as const
}

/* Whether the per-project table under the "created" chart is open. Folded by
 * default: six rows make that card far taller than the ones beside it. */
const PROJECTS_KEY = "ponos-statistics-made-projects"

function useProjectsShown() {
  const [shown, setShown] = React.useState(() => {
    try {
      return localStorage.getItem(PROJECTS_KEY) === "shown"
    } catch {
      return false
    }
  })
  const change = React.useCallback((next: boolean) => {
    setShown(next)
    try {
      localStorage.setItem(PROJECTS_KEY, next ? "shown" : "hidden")
    } catch {
      // Storage off: the choice lasts as long as the tab.
    }
  }, [])
  return [shown, change] as const
}

const locale = () => (currentLanguage() === "fr" ? "fr-FR" : "en-GB")
const date = (day: string) => new Date(`${day}T00:00:00`)
const short = (point: StatisticsDay) =>
  date(point.day).toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" })
const long = (point: StatisticsDay) =>
  date(point.day).toLocaleDateString(locale(), { weekday: "short", day: "numeric", month: "long" })
const dollars = (value: number) => money(value, value >= 100 ? 0 : 2)

// The charts' height: a glance over the board, not a page of their own.
const CHART = 120

/** `project`: the name of the project the figures are limited to; none for the whole board. */
export function StatisticsBand({ project }: { project?: string }) {
  const t = useT()
  const scope = project === undefined ? "" : `project:${project}`
  const [folded, setFolded] = useFolded(project === undefined ? FOLDED_KEY : PROJECT_FOLDED_KEY)
  const [period, setPeriod] = React.useState(
    () => kept.get(scope) ?? { range: "7d" as Range, ...span("7d", new Date()) }
  )
  const [figures, setFigures] = React.useState<Statistics | null>(
    () => answered.get(question(scope, period.from, period.to))?.figures ?? null
  )
  const [problem, setProblem] = React.useState("")
  const asked = React.useRef(0)

  const valid = Boolean(period.from && period.to && period.from <= period.to)

  React.useEffect(() => {
    kept.set(scope, period)
    if (!valid) return
    // Only the answer to the last question asked is drawn: clicking through
    // three ranges must not end on the first one's figures.
    const mine = ++asked.current
    const key = question(scope, period.from, period.to)
    const known = answered.get(key)
    if (known && Date.now() - known.at < FRESH) {
      setFigures(known.figures)
      setProblem("")
      return
    }
    api
      .statistics(period.from, period.to, project)
      .then((fresh) => {
        answered.set(key, { at: Date.now(), figures: fresh })
        if (mine !== asked.current) return
        setFigures(fresh)
        setProblem("")
      })
      .catch((error) => {
        if (mine === asked.current) setProblem(why(error))
      })
  }, [period, valid, scope, project])

  const choose = (range: Range) =>
    setPeriod((known) =>
      range === "custom" ? { ...known, range } : { range, ...span(range, new Date()) }
    )

  const today = format(new Date(), ISO)

  return (
    <Collapsible
      open={!folded}
      onOpenChange={(open) => setFolded(!open)}
      className={cn("flex min-w-0 flex-col gap-3", project === undefined ? "mb-4" : "mt-6")}
      aria-label={t("Statistics")}
      data-slot="statistics-band"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <CollapsibleTrigger className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 flex min-w-0 items-center gap-1.5 rounded-md outline-none focus-visible:ring-2">
          <ChevronRight
            className={cn("size-3.5 shrink-0 transition-transform", !folded && "rotate-90")}
            aria-hidden
          />
          <Eyebrow className="text-inherit">{t("Statistics")}</Eyebrow>
          {folded && figures ? (
            <span className="truncate font-mono text-[0.7rem] tabular-nums">
              ·{" "}
              {t("{{open}} open · {{closed}} closed · {{created}} created · {{cost}} spent", {
                open: number(figures.totals.open),
                closed: number(figures.totals.closed),
                created: number(figures.totals.created),
                cost: dollars(figures.totals.cost),
              })}
            </span>
          ) : null}
        </CollapsibleTrigger>
        <div className="flex flex-wrap items-center gap-2">
          {period.range === "custom" ? (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Input
                type="date"
                aria-label={t("From")}
                className="h-8 w-auto"
                value={period.from}
                max={period.to || today}
                onChange={(event) => setPeriod((known) => ({ ...known, from: event.target.value }))}
              />
              <span className="text-muted-foreground">→</span>
              <Input
                type="date"
                aria-label={t("To")}
                className="h-8 w-auto"
                value={period.to}
                min={period.from}
                max={today}
                onChange={(event) => setPeriod((known) => ({ ...known, to: event.target.value }))}
              />
            </div>
          ) : null}
          <Tabs value={period.range} onValueChange={(value) => choose(value as Range)}>
            <TabsList className="h-8">
              {RANGES.map((range) => (
                <TabsTrigger key={range.key} value={range.key} className="text-xs">
                  {t(range.label)}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>
      </div>

      <CollapsibleContent className="flex min-w-0 flex-col gap-3">
        {problem ? (
          <p className="text-tr-amber border-tr-amber/30 bg-tr-amber/10 rounded-xl border px-4 py-2.5 text-sm">
            {problem}
          </p>
        ) : null}

        {!figures ? (
          problem ? null : (
            <p className="text-muted-foreground flex items-center gap-3 text-sm">
              <Robot state="thinking" size={32} />
              {t("Counting the tickets…")}
            </p>
          )
        ) : (
          <Figures figures={figures} project={project} />
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}

function Figures({ figures, project }: { figures: Statistics; project?: string }) {
  const t = useT()
  const { totals, days } = figures
  const cards = [
    { label: "Open", value: number(totals.open), note: t("on the evening of the last day") },
    {
      label: "Closed",
      value: number(totals.closed),
      note: t("moved to done or validated in the period"),
      // How the closings were dated, for whoever wonders: the page said it at
      // its foot, the band says it under the pointer rather than in a line more.
      more: t(
        "A closing is dated by the runner's history when the runner closed the ticket ({{history}}), by the page's last edit in Notion otherwise ({{edited}}).",
        { history: String(figures.dated.history), edited: String(figures.dated.edited) }
      ),
    },
    { label: "Created", value: number(totals.created), note: t("added to the board in the period") },
    {
      label: "Spent",
      value: dollars(totals.cost),
      // On a project, what a closed ticket cost it on average is worth the
      // line more: it is the figure its page is read for.
      note:
        project !== undefined && figures.average !== null
          ? t("{{cost}} per closed ticket", { cost: dollars(figures.average) })
          : t("by the runner's sessions in the period"),
      more:
        project !== undefined
          ? t("Spent by the runner's sessions in the period; the average is over the tickets closed in it, all their sessions counted.")
          : undefined,
    },
  ]
  const rows =
    project === undefined
      ? figures.projects
          .slice(0, 5)
          .map((item) => ({ label: item.name || t("No project"), count: item.count }))
      : figures.statuses.map((item) => ({
          label: capital(
            columnTitle(item.key, currentBoard()?.columns.find((column) => column.key === item.key)?.name)
          ),
          count: item.count,
        }))
  const widest = Math.max(1, ...rows.map((row) => row.count))
  const [shown, setShown] = useBlocksShown()
  const nothing = !totals.created && !totals.closed && !totals.open

  return (
    <>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        {cards.map((card) => (
          <section
            key={card.label}
            className="bg-card min-w-0 rounded-xl border px-3.5 py-2.5"
            title={card.more ?? card.note}
          >
            <Eyebrow>{t(card.label)}</Eyebrow>
            <p className="mt-1 text-2xl leading-none font-bold tracking-[-0.03em] tabular-nums">
              {card.value}
            </p>
            <p className="text-muted-foreground mt-1 truncate text-[0.7rem]">{card.note}</p>
          </section>
        ))}
      </div>

      {nothing ? (
        <p className="text-muted-foreground text-sm">
          {project === undefined
            ? t("No ticket on the board over this period.")
            : t("No ticket of this project over this period.")}
        </p>
      ) : (
        <div className="grid min-w-0 gap-2 md:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,16rem)]">
          <Panel eyebrow={t("Activity")} className="min-w-0" bodyClassName="pb-3">
            <ActivityChart
              points={days}
              labels={{ created: t("Created"), closed: t("Closed"), open: t("Open"), spent: t("Spent per day") }}
              label={t("Tickets created and closed per day, still open each evening, and the spending per day")}
              day={short}
              longDay={long}
              height={CHART * 2}
            />
          </Panel>

          {figures.made ? (
            <Panel eyebrow={t("Created, by type and sub-type")} className="min-w-0" bodyClassName="pb-3">
              <MadeChart made={figures.made} project={project} />
            </Panel>
          ) : null}

          <Panel
            eyebrow={project === undefined ? t("Created, by project") : t("Created, by status")}
            className="min-w-0 md:col-span-2 xl:col-span-1"
            bodyClassName="pb-3"
          >
            <Bars rows={rows} most={widest} />
          </Panel>

          {figures.blocks || figures.subtypes ? (
            <div className="flex justify-center md:col-span-2 xl:col-span-3">
              <Button
                variant="ghost"
                size="xs"
                className="text-muted-foreground"
                aria-expanded={shown}
                onClick={() => setShown(!shown)}
              >
                {shown ? t("Show less") : t("Show more")}
                <ChevronDown className={cn("transition-transform", shown && "rotate-180")} aria-hidden />
              </Button>
            </div>
          ) : null}

          {figures.blocks && shown ? (
            <Panel
              eyebrow={t("Blocks, by cause and week")}
              className="min-w-0 md:col-span-2 xl:col-span-3"
              bodyClassName="pb-3"
            >
              <BlocksChart blocks={figures.blocks} />
            </Panel>
          ) : null}

          {figures.subtypes && shown ? (
            <Panel
              eyebrow={t("Done, by sub-type and week")}
              className="min-w-0 md:col-span-2 xl:col-span-3"
              bodyClassName="pb-3"
            >
              <SubtypesChart subtypes={figures.subtypes} />
            </Panel>
          ) : null}
        </div>
      )}
    </>
  )
}

/* The types of ticket a chart of the tickets created is filtered by, as the
 * board names them (`kinds.KINDS`): Code first, the one sub-types are for.
 * The chart still opens on all of them, and a ticket with no type has its own
 * entry: the tickets drawn are then the ones the Created card counts. */
const KINDS = [
  { key: "code", label: "Code" },
  { key: "writing", label: "Writing" },
  { key: "external", label: "External action" },
  { key: "publication", label: "Publication" },
]

// Radix's select takes no empty value: these stand for "every one" and "none".
const EVERY = "*"
const NONE = "-"

const percent = (rate: number) => `${Math.round(rate * 100)} %`

/* The tickets created, day by day or week by week, stacked by sub-type — and
 * beside them the regression rate: the bugs over the bugs and the work that
 * moves a project on, against the period before (`lib/made.ts`).
 *
 * The sub-types are written as the board writes them in English, never
 * translated: they are the words of the commits and the CHANGELOG. A ticket
 * with none is its own part, Unclassified, rather than left out of the bar. On
 * the dashboard the projects can be taken one at a time; all of them at once,
 * a small table says which one breaks the most, and a click on its row shows
 * it alone. */
function MadeChart({ made, project }: { made: Made; project?: string }) {
  const t = useT()
  const [kind, setKind] = React.useState<string>(EVERY)
  const [chosen, setChosen] = React.useState<string | null>(null)
  const scope = { kind: kind === EVERY ? null : kind === NONE ? "" : kind, project: project ?? chosen }

  const known = currentBoard()?.subtypes ?? []
  const order = [...known.map((one) => one.key), ""]
  const nameOf = (key: string) => {
    const one = subtypeOf(key)
    return one ? one.label : t("Unclassified")
  }

  const bars = stacks(made, scope)
  const now = bySubtype(made.cells, scope)
  const present = order.filter((key) => now[key])
  const rate = regression(now)
  const before = regression(bySubtype(made.before, scope))
  const going = trend(rate, before)
  const most = Math.max(1, ...bars.map((one) => one.total))
  // A date under one bar in every few: they stay readable on a third of a screen.
  const every = Math.max(1, Math.ceil(bars.length / 6))
  const projects = [...new Set([...made.cells, ...made.before].map((cell) => cell.project))].sort((a, b) =>
    a.localeCompare(b)
  )
  const rows = project === undefined && chosen === null ? byProject(made, scope.kind) : []
  const [shown, setShown] = useProjectsShown()
  const said = (bucket: string) =>
    made.unit === "week"
      ? t("week of {{day}}", { day: date(bucket).toLocaleDateString(locale(), { day: "numeric", month: "short" }) })
      : date(bucket).toLocaleDateString(locale(), { weekday: "short", day: "numeric", month: "long" })

  return (
    <div className="flex min-w-0 flex-col gap-2.5" data-slot="made-chart">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger size="sm" className="h-7 text-xs" aria-label={t("Type")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={EVERY}>{t("All types")}</SelectItem>
            {KINDS.map((one) => (
              <SelectItem key={one.key} value={one.key}>
                {t(one.label)}
              </SelectItem>
            ))}
            <SelectItem value={NONE}>{t("No type")}</SelectItem>
          </SelectContent>
        </Select>
        {project === undefined ? (
          <Select
            value={chosen === null ? EVERY : chosen || NONE}
            onValueChange={(value) => setChosen(value === EVERY ? null : value === NONE ? "" : value)}
          >
            <SelectTrigger size="sm" className="h-7 max-w-48 text-xs" aria-label={t("Project")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={EVERY}>{t("All projects")}</SelectItem>
              {projects.map((name) => (
                <SelectItem key={name || NONE} value={name || NONE}>
                  {name || t("No project")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
        <p
          className="ml-auto flex items-baseline gap-1.5 text-xs"
          title={t(
            "Bugs over bugs, features and improvements created in the period; the arrow compares it with the period of the same length before."
          )}
          data-slot="regression-rate"
        >
          <span className="text-muted-foreground">{t("Regression rate")}</span>
          <span className="text-base leading-none font-bold tabular-nums">{rate === null ? "—" : percent(rate)}</span>
          {going ? (
            <span
              className={cn(
                "inline-flex items-center gap-0.5 font-mono tabular-nums",
                going === "up" ? "text-tr-red" : going === "down" ? "text-tr-green" : "text-muted-foreground"
              )}
              data-trend={going}
            >
              {going === "up" ? (
                <ArrowUp className="size-3" aria-hidden />
              ) : going === "down" ? (
                <ArrowDown className="size-3" aria-hidden />
              ) : (
                <ArrowRight className="size-3" aria-hidden />
              )}
              {t("{{rate}} before", { rate: percent(before ?? 0) })}
            </span>
          ) : null}
        </p>
      </div>

      {!present.length ? (
        <p className="text-muted-foreground text-sm">
          {kind === EVERY
            ? t("No ticket created in the period.")
            : kind === NONE
              ? t("No ticket without a type created in the period.")
              : t("No {{kind}} ticket created in the period.", {
                  kind: t(KINDS.find((one) => one.key === kind)?.label ?? kind),
                })}
        </p>
      ) : (
        <figure className="flex min-w-0 flex-col gap-2" aria-label={t("Created, by type and sub-type")}>
          <ul className="text-muted-foreground flex flex-wrap gap-x-3 gap-y-1 text-xs">
            {present.map((key) => (
              <li key={key || NONE} className="flex items-center gap-1.5" data-subtype={key || NONE}>
                <SubtypeDot subtype={key} className="size-2.5" />
                {nameOf(key)}
                <span className="font-mono tabular-nums">{number(now[key])}</span>
              </li>
            ))}
          </ul>
          <div className="flex items-end gap-[2px]" style={{ height: CHART }}>
            {bars.map((one) => (
              <div
                key={one.bucket}
                className="hover:bg-muted/60 flex h-full min-w-0 flex-1 flex-col justify-end rounded-sm"
                title={[
                  `${said(one.bucket)} — ${number(one.total)}`,
                  ...present
                    .filter((key) => one.counts[key])
                    .map((key) => `${nameOf(key)} — ${number(one.counts[key])}`),
                ].join("\n")}
                data-slot="made-bucket"
              >
                <div className="flex flex-col-reverse gap-[2px]" style={{ height: `${(one.total / most) * 100}%` }}>
                  {present
                    .filter((key) => one.counts[key])
                    .map((key, index, parts) => (
                      <span
                        key={key || NONE}
                        className={cn("block min-h-[2px] w-full", index === parts.length - 1 && "rounded-t")}
                        style={{ flexGrow: one.counts[key], background: subtypeColor(key) }}
                        data-subtype={key || NONE}
                      />
                    ))}
                </div>
              </div>
            ))}
          </div>
          <div className="text-muted-foreground flex gap-[2px] font-mono text-[0.65rem]">
            {bars.map((one, index) => (
              <span key={one.bucket} className="min-w-0 flex-1 overflow-visible text-center whitespace-nowrap">
                {index % every === 0
                  ? date(one.bucket).toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" })
                  : ""}
              </span>
            ))}
          </div>
        </figure>
      )}

      {rows.length > 1 ? (
        <button
          type="button"
          onClick={() => setShown(!shown)}
          aria-expanded={shown}
          aria-controls="made-projects"
          className="text-muted-foreground hover:text-foreground flex items-center gap-0.5 self-start rounded-sm text-xs underline-offset-2 hover:underline"
          data-slot="made-projects-toggle"
        >
          {shown ? t("Hide") : t("See by project ({{count}})", { count: Math.min(rows.length, 6) })}
          {shown ? <ChevronUp className="size-3" aria-hidden /> : <ChevronDown className="size-3" aria-hidden />}
        </button>
      ) : null}

      {rows.length > 1 && shown ? (
        <table id="made-projects" className="w-full min-w-0 table-fixed text-sm" data-slot="made-projects">
          <thead>
            <tr className="text-muted-foreground text-xs">
              <th scope="col" className="pb-1 text-left font-medium">
                {t("Project")}
              </th>
              <th scope="col" className="w-24 truncate pb-1 pl-3 text-right font-medium">
                <SubtypeDot subtype="feature" className="me-1.5" />
                {nameOf("feature")}
              </th>
              <th scope="col" className="w-24 truncate pb-1 pl-3 text-right font-medium">
                <SubtypeDot subtype="bug" className="me-1.5" />
                {nameOf("bug")}
              </th>
              <th scope="col" className="w-24 truncate pb-1 pl-3 text-right font-medium" title={t("Regression rate")}>
                {t("Regression")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 6).map((row) => {
              const going = trend(row.rate, row.before)
              return (
                <tr
                  key={row.project || NONE}
                  className="hover:bg-muted/60 cursor-pointer border-t"
                  onClick={() => setChosen(row.project)}
                  data-project={row.project}
                >
                  <th scope="row" className="truncate py-1 text-left font-normal">
                    {row.project || t("No project")}
                  </th>
                  <td className="py-1 text-right font-mono text-xs tabular-nums">{number(row.ahead)}</td>
                  <td className="py-1 text-right font-mono text-xs tabular-nums">{number(row.broken)}</td>
                  <td className="py-1 text-right font-mono text-xs font-semibold tabular-nums">
                    {row.rate === null ? "—" : percent(row.rate)}
                    {going === "up" ? <span className="text-tr-red"> ↑</span> : null}
                    {going === "down" ? <span className="text-tr-green"> ↓</span> : null}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : null}
    </div>
  )
}

/* The families, in the order the legend and the stack list them — the order
 * of `blocks.FAMILIES`, which their colours are assigned in. */
const FAMILIES: BlockFamily[] = ["merge", "session", "infrastructure", "question", "access"]

const FAMILY_NAME: Record<BlockFamily, string> = {
  merge: "Merge",
  session: "Session",
  infrastructure: "Infrastructure",
  question: "Question",
  access: "Access",
}

// The bars' height: the curves' own, so that the panels read as one band.
const BLOCK_CHART = CHART + 24

/* Why tickets stopped, week after week (`blocks` in `web/statistics.py`).
 *
 * One bar a week, stacked by family — five colours read apart, where twenty
 * causes would be a rainbow nobody decodes — and every cause, by name, in the
 * list beside it: that list is the chart's table, the counts a person reads,
 * and the colours there only point back to a family. The pointer over a bar
 * says its week cause by cause. */
function BlocksChart({ blocks }: { blocks: NonNullable<Statistics["blocks"]> }) {
  const t = useT()
  if (!blocks.total)
    return <p className="text-muted-foreground text-sm">{t("No ticket stopped in the period.")}</p>
  const familyOf = new Map(blocks.causes.map((cause) => [cause.code, cause.family]))
  const labelOf = new Map(blocks.causes.map((cause) => [cause.code, blockSaid(cause.label)]))
  const present = FAMILIES.filter((family) => blocks.causes.some((cause) => cause.family === family))
  const weeks = blocks.weeks.map((week) => {
    const stack = present.map((family) => ({
      family,
      count: Object.entries(week.counts)
        .filter(([code]) => familyOf.get(code) === family)
        .reduce((sum, [, count]) => sum + count, 0),
    }))
    const total = stack.reduce((sum, part) => sum + part.count, 0)
    const said = Object.entries(week.counts)
      .sort((a, b) => b[1] - a[1])
      .map(([code, count]) => `${labelOf.get(code) ?? code} — ${number(count)}`)
    return { week: week.week, stack, total, said }
  })
  const most = Math.max(1, ...weeks.map((week) => week.total))
  // A label under every bar while they fit, one in every few beyond.
  const every = Math.max(1, Math.ceil(weeks.length / 12))
  const widest = Math.max(1, ...blocks.causes.map((cause) => cause.count))
  const weekOf = (week: string) =>
    t("week of {{day}}", {
      day: date(week).toLocaleDateString(locale(), { day: "numeric", month: "short" }),
    })

  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <figure className="flex min-w-0 flex-col gap-2" aria-label={t("Blocks, by cause and week")}>
        <ul className="text-muted-foreground flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {present.map((family) => {
            const Icon = FAMILY_ICON[family]
            return (
              <li key={family} className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-sm" style={{ background: familyColor(family) }} />
                <Icon className="size-3" />
                {t(FAMILY_NAME[family])}
              </li>
            )
          })}
        </ul>
        <div className="flex items-end gap-[2px]" style={{ height: BLOCK_CHART }}>
          {weeks.map((week) => (
            <div
              key={week.week}
              className="hover:bg-muted/60 flex h-full min-w-0 flex-1 flex-col justify-end rounded-sm"
              title={[`${weekOf(week.week)} — ${number(week.total)}`, ...week.said].join("\n")}
              data-slot="blocks-week"
            >
              {/* Drawn from the top down, so the first family sits on the axis. */}
              <div className="flex flex-col-reverse gap-[2px]" style={{ height: `${(week.total / most) * 100}%` }}>
                {week.stack
                  .filter((part) => part.count)
                  .map((part, index, parts) => (
                    <span
                      key={part.family}
                      className={cn("block min-h-[2px] w-full", index === parts.length - 1 && "rounded-t")}
                      style={{ flexGrow: part.count, background: familyColor(part.family) }}
                    />
                  ))}
              </div>
            </div>
          ))}
        </div>
        <div className="text-muted-foreground flex gap-[2px] font-mono text-[0.65rem]">
          {weeks.map((week, index) => (
            <span key={week.week} className="min-w-0 flex-1 truncate text-center">
              {index % every === 0
                ? date(week.week).toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" })
                : ""}
            </span>
          ))}
        </div>
      </figure>

      <ul className="flex max-h-56 min-w-0 flex-col gap-1.5 overflow-y-auto" data-slot="blocks-causes">
        {blocks.causes.map((cause) => {
          const Icon = FAMILY_ICON[cause.family]
          return (
            <li
              key={cause.code}
              className="grid grid-cols-[minmax(0,11rem)_1fr_auto] items-center gap-3 text-sm"
              title={`${cause.code} — ${blockSaid(cause.help)}`}
            >
              <span className="flex min-w-0 items-center gap-1.5">
                <Icon className="size-3.5 shrink-0" style={{ color: familyColor(cause.family) }} />
                <span className="truncate">{blockSaid(cause.label)}</span>
              </span>
              <span className="bg-muted h-2 overflow-hidden rounded-full">
                <span
                  className="block h-full rounded-full"
                  style={{ width: `${(cause.count / widest) * 100}%`, background: familyColor(cause.family) }}
                />
              </span>
              <span className="font-mono text-xs font-semibold tabular-nums">{number(cause.count)}</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/* The code tickets closed, week after week, stacked by sub-type
 * (`subtypes` in `web/statistics.py`) — eight colours at most, the same in
 * the legend and in the bars — and beside it the table a person reads: how many of
 * each, and what one of them cost and lasted on average. */
function SubtypesChart({ subtypes }: { subtypes: NonNullable<Statistics["subtypes"]> }) {
  const t = useT()
  if (!subtypes.total)
    return <p className="text-muted-foreground text-sm">{t("No code ticket with a sub-type closed in the period.")}</p>
  const labelOf = new Map(subtypes.subtypes.map((one) => [one.key, one.label]))
  const weeks = subtypes.weeks.map((week) => {
    const stack = subtypes.subtypes.map((one) => ({ key: one.key, count: week.counts[one.key] ?? 0 }))
    const total = stack.reduce((sum, part) => sum + part.count, 0)
    const said = stack
      .filter((part) => part.count)
      .map((part) => `${labelOf.get(part.key) ?? part.key} — ${number(part.count)}`)
    return { week: week.week, stack, total, said }
  })
  const most = Math.max(1, ...weeks.map((week) => week.total))
  const every = Math.max(1, Math.ceil(weeks.length / 12))
  const weekOf = (week: string) =>
    t("week of {{day}}", {
      day: date(week).toLocaleDateString(locale(), { day: "numeric", month: "short" }),
    })

  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <figure className="flex min-w-0 flex-col gap-2" aria-label={t("Done, by sub-type and week")}>
        <ul className="text-muted-foreground flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {subtypes.subtypes.map((one) => (
            <li key={one.key} className="flex items-center gap-1.5">
              <SubtypeDot subtype={one.key} className="size-2.5" />
              {labelOf.get(one.key)}
            </li>
          ))}
        </ul>
        <div className="flex items-end gap-[2px]" style={{ height: BLOCK_CHART }}>
          {weeks.map((week) => (
            <div
              key={week.week}
              className="hover:bg-muted/60 flex h-full min-w-0 flex-1 flex-col justify-end rounded-sm"
              title={[`${weekOf(week.week)} — ${number(week.total)}`, ...week.said].join("\n")}
              data-slot="subtypes-week"
            >
              <div className="flex flex-col-reverse gap-[2px]" style={{ height: `${(week.total / most) * 100}%` }}>
                {week.stack
                  .filter((part) => part.count)
                  .map((part, index, parts) => (
                    <span
                      key={part.key}
                      className={cn("block min-h-[2px] w-full", index === parts.length - 1 && "rounded-t")}
                      style={{ flexGrow: part.count, background: subtypeColor(part.key) }}
                    />
                  ))}
              </div>
            </div>
          ))}
        </div>
        <div className="text-muted-foreground flex gap-[2px] font-mono text-[0.65rem]">
          {weeks.map((week, index) => (
            <span key={week.week} className="min-w-0 flex-1 truncate text-center">
              {index % every === 0
                ? date(week.week).toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" })
                : ""}
            </span>
          ))}
        </div>
      </figure>

      <table className="w-full min-w-0 self-start text-sm" data-slot="subtypes-table">
        <thead>
          <tr className="text-muted-foreground text-xs">
            <th scope="col" className="pb-1.5 text-left font-medium">
              {t("Sub-type")}
            </th>
            <th scope="col" className="pb-1.5 text-right font-medium">
              {t("Done")}
            </th>
            <th scope="col" className="pb-1.5 text-right font-medium">
              {t("Average cost")}
            </th>
            <th scope="col" className="pb-1.5 text-right font-medium">
              {t("Average duration")}
            </th>
          </tr>
        </thead>
        <tbody>
          {subtypes.subtypes.map((one) => (
            <tr key={one.key} className="border-t" data-subtype={one.key}>
              <th scope="row" className="flex items-center gap-1.5 py-1.5 text-left font-normal">
                <SubtypeDot subtype={one.key} />
                {labelOf.get(one.key)}
              </th>
              <td className="py-1.5 text-right font-mono text-xs font-semibold tabular-nums">{number(one.count)}</td>
              <td className="py-1.5 text-right font-mono text-xs tabular-nums">
                {one.cost === null ? "—" : dollars(one.cost)}
              </td>
              <td className="py-1.5 text-right font-mono text-xs tabular-nums">
                {one.duration === null ? "—" : lasted(one.duration)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** A count per name, as bars of one colour: how many, not which. */
function Bars({ rows, most }: { rows: { label: string; count: number }[]; most: number }) {
  const t = useT()
  if (!rows.length)
    return <p className="text-muted-foreground text-sm">{t("No ticket created in the period.")}</p>
  return (
    <ul className="flex flex-col gap-1.5">
      {rows.map((row) => (
        <li key={row.label} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate" title={row.label}>
            {row.label}
          </span>
          <span className="bg-muted h-2 overflow-hidden rounded-full">
            <span
              className="block h-full rounded-full"
              style={{ width: `${(row.count / most) * 100}%`, background: "var(--series-1)" }}
            />
          </span>
          <span className="font-mono text-xs font-semibold tabular-nums">{number(row.count)}</span>
        </li>
      ))}
    </ul>
  )
}
