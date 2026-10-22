import * as React from "react"
import {
  CircleCheck,
  CircleDashed,
  CircleX,
  ExternalLink,
  GitPullRequest,
  ListChecks,
  MessageCircleQuestion,
  Scale,
  type LucideIcon,
} from "lucide-react"
import { useLocation } from "@tanstack/react-router"
import { useNavigate } from "react-resource-view"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useOpensOverTheList } from "@/components/console/record-window"
import { api, why } from "@/lib/api"
import { titleOf, useBoard } from "@/lib/board-store"
import {
  CHECKS,
  PROMPTS,
  type DecisionTab,
  actionOf,
  away,
  decisionTabOf,
  immediate,
  labelOf,
  prefilled,
  promptOf,
  sendable,
  titlesIn,
  tone,
} from "@/lib/decision"
import { useT } from "@/lib/i18n"
import { SERIES_FROM, type SeriesColumn, withSeries } from "@/lib/series"
import type { Decision, Solution, Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"
import { tickets } from "@/resources/tickets"

/* What a card waiting on you is for: why it waits, and what to do about it.
 * A blocked card used to offer "make ready" and nothing else, and one in review
 * three gestures that said nothing of what they were deciding on: the reason was
 * in the last report, on the page. This reads that report for you — the server
 * does, see `decisions.py` — and lays out the few choices that fit, each a click,
 * or a click and a sentence.
 *
 * In review, it is a tab of the ticket — Decide — beside its brief, its
 * discussion and its session. A blocked ticket had one too, Unblock, and it
 * said the question twice and offered two fields to answer it in, beside the
 * discussion that was already a conversation: its question is answered there
 * now, in the bubble Ponos asked it in and the quick replies under it — see
 * `ticket-talk.tsx`. The button on a card opens the window on the tab, or on
 * the discussion; the same button on the ticket itself, in its window or on
 * its page, only switches to it.
 *
 * The series that goes through a column's tickets one after another
 * (`ticket-series.tsx`) draws this panel for each, a blocked one too: its
 * question as the discussion says it, and under it every way out the server
 * offers, the session's own options numbered — the keys 1 to 9 there.
 */

/* The question a blocked ticket stopped on, as its discussion draws it: with
 * the discussion, which the first load does without. */
const Asked = React.lazy(() =>
  import("@/components/console/ticket-talk").then((module) => ({ default: module.Asked }))
)

/** How a ticket shown on screen goes to one of its tabs: none around a card, which opens the window instead. */
/* The tab of a ticket opened in the window over a list, in the address. Not
 * `tab`, which is the page's under the window: a project names its own tabs
 * with it, and has a "brief" too. */
export const WINDOW_TAB = "ticket-tab"

export const TicketTabContext = React.createContext<{
  goTo: (tab: DecisionTab) => void
  /** The tab on show, which the button has no use to offer a second time. */
  shown?: string
} | null>(null)

/** The call to action of a card waiting on you: Unblock, or Decide. Nothing on any other card. */
export function DecideButton({
  ticket,
  className,
  title,
  icon,
}: {
  ticket: Ticket
  className?: string
  /** The tooltip: on a blocked card, the cause's label and its line of help, which the card no longer shows. */
  title?: string
  /** The mark of the cause on a blocked card, in place of the generic question mark. */
  icon?: LucideIcon
}) {
  const t = useT()
  const tabs = React.useContext(TicketTabContext)
  const action = actionOf(ticket.column)
  const tab = decisionTabOf(ticket.column)
  // Off the ticket's page, the window over the list, on that tab.
  const openOnTheTab = useOpensOverTheList(tickets, "read", ticket.id, tab ? `${WINDOW_TAB}=${tab}` : "")
  if (!action || !tab) return null
  // Already on that tab: the button would only point at where you are.
  if (tabs?.shown === tab) return null
  const blocked = ticket.column === "blocked"
  const Icon = blocked ? (icon ?? MessageCircleQuestion) : Scale
  return (
    <Button
      size="sm"
      variant="outline"
      data-decide={ticket.id}
      title={title}
      className={cn(
        blocked ? "text-tr-amber hover:text-tr-amber" : "text-tr-pink hover:text-tr-pink",
        className
      )}
      onClick={(event) => (tabs ? tabs.goTo(tab) : openOnTheTab(event))}
    >
      <Icon />
      {t(action)}
    </Button>
  )
}

/** Opens the series of a column's tickets over the page you are on: the address says it, so Back closes it. */
export function useOpenSeries() {
  const navigate = useNavigate()
  const { pathname, searchStr } = useLocation()
  return React.useCallback(
    (column: SeriesColumn) => void navigate({ to: `${pathname}${withSeries(searchStr, column)}` }),
    [navigate, pathname, searchStr]
  )
}

/* The way through a whole column at once, in its heading: Unblock (3), Decide
 * (2) — from two cards on, one being a card you would open anyway. Counted on
 * the board, whatever the search keeps. */
export function SeriesButton({ column }: { column: SeriesColumn }) {
  const t = useT()
  const board = useBoard()
  const open = useOpenSeries()
  const count = board.tickets.filter((ticket) => ticket.column === column).length
  if (count < SERIES_FROM) return null
  const blocked = column === "blocked"
  const Icon = blocked ? ListChecks : Scale
  return (
    <Button
      size="xs"
      variant="outline"
      data-series={column}
      className={cn("shrink-0", blocked ? "text-tr-amber hover:text-tr-amber" : "text-tr-pink hover:text-tr-pink")}
      onClick={(event) => {
        event.stopPropagation()
        open(column)
      }}
    >
      <Icon />
      {blocked ? t("Unblock ({{count}})", { count: String(count) }) : t("Decide ({{count}})", { count: String(count) })}
    </Button>
  )
}

/** The tab itself: why the ticket waits, and the choices. `onDone` is told which, once one is sent. */
export function TicketDecision({ ticket, onDone }: { ticket: Ticket; onDone: (solution: Solution) => void }) {
  return <Panel key={ticket.id} id={ticket.id} ticket={ticket} onDone={onDone} />
}

function Panel({ id, ticket, onDone }: { id: string; ticket?: Ticket; onDone: (solution: Solution) => void }) {
  const t = useT()
  const [decision, setDecision] = React.useState<Decision | null>(null)
  const [problem, setProblem] = React.useState("")

  React.useEffect(() => {
    let current = true
    api
      .decision(id)
      .then((found) => current && setDecision(found))
      .catch((error) => current && setProblem(why(error)))
    return () => {
      current = false
    }
  }, [id])

  if (problem)
    return (
      <p className="text-destructive text-sm" role="alert">
        {t("This ticket could not be read: {{why}}", { why: problem })}
      </p>
    )
  if (!decision)
    return (
      <div className="space-y-2" aria-busy="true">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
      </div>
    )
  return (
    <div data-slot="ticket-decision" className="max-w-[75ch] space-y-8 text-base leading-relaxed">
      {decision.column === "review" ? (
        <Delivered decision={decision} />
      ) : (
        <React.Suspense fallback={<Skeleton className="h-16 w-2/3" />}>
          <Asked decision={decision} when="" />
        </React.Suspense>
      )}
      <Choices decision={decision} ticket={ticket} onDone={onDone} />
    </div>
  )
}

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-foreground mb-2 text-lg font-semibold">{children}</h3>
  )
}

/* What a ticket in review brought back: its sentence, its pull request, its checks, its caveats. */
function Delivered({ decision }: { decision: Decision }) {
  const t = useT()
  const checks = decision.checks
  const state = checks?.state ?? "none"
  const Mark = state === "passed" ? CircleCheck : state === "failed" ? CircleX : CircleDashed
  const caveats = decision.caveats ?? []
  return (
    <>
      <section data-slot="decision-delivered" className="space-y-2">
        <Heading>{t("What it delivered")}</Heading>
        <p className="leading-snug font-medium break-words">{decision.summary || t("The run said nothing more.")}</p>
        {decision.facts ? <p className="text-muted-foreground text-xs">{decision.facts}</p> : null}
        <div className="flex flex-wrap items-center gap-1.5">
          {decision.pull_request ? (
            <Button asChild variant="outline" size="sm">
              <a href={decision.pull_request} target="_blank" rel="noreferrer">
                <GitPullRequest />
                {t("Pull request")}
                <ExternalLink className="opacity-60" />
              </a>
            </Button>
          ) : null}
          {checks?.link ? (
            <Button asChild variant="outline" size="sm">
              <a href={checks.link} target="_blank" rel="noreferrer">
                {t("CI")}
                <ExternalLink className="opacity-60" />
              </a>
            </Button>
          ) : null}
          <Badge
            variant="outline"
            data-checks={state}
            className={cn(
              state === "passed" && "text-tr-green",
              state === "failed" && "text-destructive",
              state === "pending" && "text-tr-amber"
            )}
          >
            <Mark />
            {t(CHECKS[state] ?? CHECKS.unknown)}
          </Badge>
        </div>
      </section>
      <section data-slot="decision-caveats">
        <Heading>{t("Points to check")}</Heading>
        {caveats.length ? (
          <ul className="list-disc space-y-1 pl-4 text-xs leading-relaxed break-words">
            {caveats.map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground text-xs">{t("The agent flagged nothing.")}</p>
        )}
      </section>
    </>
  )
}

/* The choices, one button each. One that needs words opens its field under it. */
function Choices({
  decision,
  ticket,
  onDone,
}: {
  decision: Decision
  ticket?: Ticket
  onDone: (solution: Solution) => void
}) {
  const t = useT()
  const board = useBoard()
  const [chosen, setChosen] = React.useState<Solution | null>(null)
  const [text, setText] = React.useState("")
  const [model, setModel] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const models = (board.choices?.model ?? []).filter((one) => one.value && one.value !== decision.model)
  const named = (column: string) => board.columns.find((item) => item.key === column)?.name || column

  async function apply(solution: Solution, words: string, picked: string) {
    setBusy(true)
    try {
      await api.decide(decision.id, {
        key: solution.key,
        number: solution.number,
        text: solution.needs === "titles" ? "" : words,
        model: picked,
        titles: solution.needs === "titles" ? titlesIn(words) : undefined,
      })
      toast.success(
        t("“{{title}}” moved to {{column}}", {
          title: ticket ? titleOf(ticket) : t("Ticket"),
          column: named(solution.column),
        }),
        { description: t(labelOf(solution)) }
      )
      onDone(solution)
    } catch (error) {
      toast.error(t("The decision was not sent"), { description: why(error) })
    } finally {
      setBusy(false)
    }
  }

  function pick(solution: Solution) {
    if (immediate(solution)) {
      void apply(solution, "", "")
      return
    }
    setChosen(solution)
    setText(prefilled(solution))
    setModel("")
  }

  const same = (one: Solution, other: Solution | null) =>
    other !== null && one.key === other.key && one.number === other.number
  const buttons = decision.solutions

  return (
    <section data-slot="decision-choices">
      <Heading>{t("Your decision")}</Heading>
      <ul className="space-y-2">
        {buttons.map((solution, index) => (
          <li key={`${solution.key}-${solution.number}`}>
            <Button
              variant={same(solution, chosen) ? "secondary" : tone(solution, index)}
              disabled={busy}
              data-solution={solution.key}
              data-number={solution.number}
              aria-expanded={immediate(solution) ? undefined : same(solution, chosen)}
              className={cn(
                "h-auto min-h-11 w-full justify-start py-2 text-left text-base whitespace-normal",
                away(solution) && "text-destructive hover:text-destructive"
              )}
              onClick={() => (same(solution, chosen) ? setChosen(null) : pick(solution))}
            >
              {solution.key === "option" ? (
                <span className="text-xs opacity-70">{solution.number}.</span>
              ) : null}
              <span className="min-w-0 break-words">
                {t(labelOf(solution))}
                {/* Which point, for the ones sent back on a point of their own. */}
                {solution.key === "caveat" && decision.caveats?.[solution.number - 1] ? (
                  <span className="text-muted-foreground block text-sm">
                    {decision.caveats[solution.number - 1]}
                  </span>
                ) : null}
              </span>
            </Button>
            {same(solution, chosen) ? (
              <form
                className="mt-1.5 space-y-1.5"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (sendable(solution, text, model)) void apply(solution, text, model)
                }}
              >
                {solution.needs === "model" ? (
                  <Select value={model} onValueChange={setModel}>
                    <SelectTrigger className="w-full" aria-label={t(PROMPTS.model)}>
                      <SelectValue placeholder={t(PROMPTS.model)} />
                    </SelectTrigger>
                    <SelectContent>
                      {models.map((one) => (
                        <SelectItem key={one.value} value={one.value}>
                          {one.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : null}
                <Textarea
                  autoFocus
                  value={text}
                  rows={solution.needs === "titles" ? 4 : 3}
                  aria-label={t(promptOf(solution))}
                  placeholder={t(promptOf(solution))}
                  onChange={(event) => setText(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                      event.preventDefault()
                      event.currentTarget.form?.requestSubmit()
                    }
                  }}
                  className="text-base md:text-base"
                />
                <div className="flex justify-end gap-2">
                  <Button type="button" variant="ghost" onClick={() => setChosen(null)}>
                    {t("Cancel")}
                  </Button>
                  <Button
                    type="submit"
                    variant={away(solution) ? "destructive" : "default"}
                    disabled={busy || !sendable(solution, text, model)}
                  >
                    {solution.column === "ready" ? t("Send and run again") : t("Confirm")}
                  </Button>
                </div>
              </form>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}
