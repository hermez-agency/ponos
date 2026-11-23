import * as React from "react"
import { ArrowDown, ChevronRight, ChevronsDownUp, ChevronsUpDown, Circle, CircleCheck, LoaderCircle, TriangleAlert } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { useSteps } from "@/hooks/use-console"
import { counted, useT } from "@/lib/i18n"
import { clock } from "@/lib/composer"
import { FOLDED, everythingOpen, isOpen, outline, toggled, type Line, type Unfolded } from "@/lib/outline"
import { reading } from "@/lib/phase"
import { advance, readPlan, type Task } from "@/lib/plan"
import { doing } from "@/lib/thinking"
import type { Step, Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"
import { brief } from "@/lib/worktime"

import { Markdown } from "./markdown"
import { Robot } from "./robot"

/* A ticket's session, read from the ticket.
 *
 * Its steps come from the local journal (`journal.py`): every run of the
 * ticket, each read a page at a time from its end, the newest followed while
 * it goes on — `ticket-live.tsx`, which only an opened ticket loads. A ticket
 * that last ran before there was a journal is read from its last log, as it
 * used to be. What is here is what the board's cards draw too.
 *
 * There used to be a page of its own for this, listing the sessions by the id
 * their log is named after — and nothing on it said which ticket `24f9704c`
 * was. The session is the ticket's: it is read where the ticket is, on its
 * page and on its card, from the same stream the page used to read.
 *
 * A session is two kinds of line, and they are not read the same way. What the
 * agent *said* is why somebody opens the journal: it is drawn whole, as the
 * prose it is, and it is all that is drawn at first. What it *did* — forty
 * `Read`s, a `Bash` — is how it got there: folded under the sentence it
 * followed (see `outline`), the toggle saying how many, how long and how many
 * failed, and once open, one line each, the tool and the start of what it was
 * pointed at, open in turn for whoever wants the rest.
 */

/* The worktree a session runs in, as the session sees it: `.`.
 *
 * Every path a session touches starts with the same sixty characters —
 * `/home/…/ponos/worktrees/<project>-<id>/` — and a line that spends
 * its width on them has none left for the file it is about. */
const WORKTREE = /(?:\/[^\s/"'`]+)*?\/worktrees\/[^\s/"'`]+(\/)?/g

export function shorten(text: string): string {
  return String(text ?? "").replace(WORKTREE, (_, slash?: string) => (slash ? "./" : "."))
}

/* The lines the runner reads at the end of a session — `RESULT: ok — …`,
 * `QUESTION: …` — are for it, not for the person: the question is in the
 * discussion and the status band already. Dropped from what is drawn, the
 * session's own words left whole. */
const PROTOCOL = /^[ \t]*(?:DONE|WHY|CATEGORY|QUESTION|MODE|OPTION|CODE|COMMAND|RESULT):.*(?:\r?\n|$)/gm

export function withoutProtocol(text: string): string {
  return String(text ?? "").replace(PROTOCOL, "").replace(/\n{3,}/g, "\n\n").trim()
}

/** What a card says a running ticket is doing: what the agent last said, or else the last tool. */
export function lastWord(steps: Step[]): Step | undefined {
  return steps.findLast((step) => step.said) ?? steps[steps.length - 1]
}

/** How close to the bottom still counts as following it. */
const NEAR = 24

/* What a step's line ends on, besides the step: nothing on a card, the
 * gestures of a step in a ticket's journal. Its line is `group/step`, so what
 * it draws can wait to be pointed at. */
export type Aside = (step: Step) => React.ReactNode

/** One tool call, folded to a line; a click unfolds it. */
function ToolLine({ step, aside }: { step: Step; aside?: Aside }) {
  const plan = step.label === "Plan" ? advance(readPlan(step.detail)) : null
  // The list is drawn by the plan itself; its line only says how far it is.
  const detail = plan ? `${plan.done}/${plan.total}` : shorten(step.detail)
  const failed = step.label === "Error"
  return (
    <details className="group">
      <summary
        className={cn(
          "group/step hover:bg-muted/60 flex cursor-pointer list-none items-start gap-1.5 rounded px-1 py-0.5 font-mono text-xs [&::-webkit-details-marker]:hidden",
          !detail && "cursor-default"
        )}
      >
        <ChevronRight
          className={cn(
            "text-muted-foreground mt-0.5 size-3 shrink-0 transition-transform group-open:rotate-90",
            !detail && "invisible"
          )}
        />
        <span className={cn("shrink-0 font-medium", failed ? "text-destructive" : "text-tr-violet")}>
          {step.label}
        </span>
        {detail ? (
          <span className="text-muted-foreground min-w-0 truncate group-open:break-all group-open:whitespace-pre-wrap">
            {detail}
          </span>
        ) : null}
        {aside?.(step)}
      </summary>
    </details>
  )
}

/* One broad line: what the agent said, and under it, folded, what it did
 * next. Its toggle says what is behind it — how many steps, how long, and how
 * many went wrong, in red, so a line that fought its way through can be told
 * from one that did not without opening it. The line still being written says
 * what the agent is on, in a few words, without opening anything either. */
function OutlineLine({
  line,
  lead,
  open,
  onToggle,
  current,
  aside,
}: {
  line: Line<Step>
  lead: string
  open: boolean
  onToggle: () => void
  current: boolean
  aside?: Aside
}) {
  const t = useT()
  const body = React.useId()
  const summary = [
    line.steps.length ? counted(line.steps.length, "{{count}} step", "{{count}} steps") : "",
    line.seconds !== undefined ? clock(line.seconds) : "",
  ].filter(Boolean)
  const now = current ? doing(line.steps) : undefined
  return (
    <div
      data-slot="session-line"
      data-open={open || undefined}
      className={cn(
        "bg-card my-1.5 rounded-lg border-l-2 px-3 py-2",
        line.said ? "border-tr-violet/40" : "border-border"
      )}
    >
      {line.said && withoutProtocol(line.said.label) ? (
        <div className="group/step flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <Markdown text={shorten(withoutProtocol(line.said.label))} />
          </div>
          {aside?.(line.said)}
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">{lead}</p>
      )}
      {now ? (
        <p className="text-muted-foreground mt-1 flex min-w-0 items-center gap-1.5 font-mono text-[0.7rem]" role="status">
          <Pulse />
          <span className="shrink-0">{t("writing now")}</span>
          <span>·</span>
          <span className="truncate">{t(now.key, now.params)}</span>
        </p>
      ) : null}
      {line.steps.length ? (
        <>
          <button
            type="button"
            data-slot="session-line-toggle"
            aria-expanded={open}
            aria-controls={body}
            onClick={onToggle}
            className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 mt-1 flex max-w-full items-center gap-1.5 rounded-md font-mono text-[0.7rem] outline-none focus-visible:ring-2"
          >
            <ChevronRight className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")} />
            <span className="truncate">
              {[open ? t("Hide the steps") : t("Show the steps"), ...summary].join(" · ")}
            </span>
            {line.errors ? (
              <span
                data-slot="session-line-errors"
                className="text-tr-red ml-0.5 inline-flex shrink-0 items-center gap-1"
                title={counted(line.errors, "{{count}} step went wrong", "{{count}} steps went wrong")}
              >
                <TriangleAlert aria-hidden="true" className="size-3" />
                <span className="sr-only">
                  {counted(line.errors, "{{count}} step went wrong", "{{count}} steps went wrong")}
                </span>
                <span aria-hidden="true">{line.errors}</span>
              </span>
            ) : null}
          </button>
          {open ? (
            <div id={body} className="mt-1 border-t pt-1">
              {line.steps.map((step, index) => (
                <ToolLine key={step.position ?? index} step={step} aside={aside} />
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

/* The journal, in its broad lines (see `outline`), scrolled to its end while
 * it grows — and left alone the moment somebody scrolls up to read something:
 * a page that pulls you back down every second is a page you cannot read. A
 * button brings the following back.
 *
 * What is open is held here, by the key of each line, and not by the lines:
 * a step arriving draws them all again, and must not fold the one being read.
 * Whoever draws this for another run gives it another `key`.
 *
 * `offset` is where the first step stands in the run when the steps do not
 * say it themselves; `cut`, that the run goes further back than these steps,
 * so the steps before the first thing said are not its beginning; `aside`,
 * what is drawn at the end of a step's line — a ticket's journal puts there
 * what can be done from that step (`ticket-live.tsx`). */
export function SessionLog({
  steps,
  live,
  offset = 0,
  cut = false,
  className,
  aside,
}: {
  steps: Step[]
  live: boolean
  offset?: number
  cut?: boolean
  className?: string
  aside?: Aside
}) {
  const t = useT()
  const box = React.useRef<HTMLDivElement>(null)
  const [following, setFollowing] = React.useState(true)
  const [unfolded, setUnfolded] = React.useState<Unfolded>(FOLDED)
  const lines = React.useMemo(() => outline(steps, offset), [steps, offset])
  const foldable = lines.some((line) => line.steps.length)
  const everything = everythingOpen(unfolded)

  const onScroll = () => {
    const element = box.current
    if (!element) return
    const bottom = element.scrollHeight - element.scrollTop - element.clientHeight < NEAR
    setFollowing((was) => (was === bottom ? was : bottom))
  }

  const toEnd = React.useCallback(() => {
    const element = box.current
    if (element) element.scrollTop = element.scrollHeight
  }, [])

  React.useLayoutEffect(() => {
    if (following) toEnd()
  }, [steps, following, toEnd])

  return (
    <div className="flex flex-col gap-1.5">
      {foldable ? (
        <Button
          size="sm"
          variant="ghost"
          data-slot="session-unfold-all"
          className="text-muted-foreground h-7 self-end text-xs"
          onClick={() => setUnfolded(everything ? FOLDED : { all: true, flipped: [] })}
        >
          {everything ? <ChevronsDownUp /> : <ChevronsUpDown />}
          {everything ? t("Fold everything") : t("Unfold everything")}
        </Button>
      ) : null}
      <div className="relative">
        <div
          ref={box}
          onScroll={onScroll}
          role="log"
          aria-live={live ? "polite" : "off"}
          className={cn(
            "scroll-thin bg-muted/30 max-h-[65vh] overflow-y-auto rounded-xl border px-2 py-2",
            className
          )}
        >
          {lines.map((line, index) => (
            <OutlineLine
              key={line.key}
              line={line}
              lead={cut ? t("Before these lines") : t("Getting ready")}
              open={isOpen(unfolded, line.key)}
              onToggle={() => setUnfolded((was) => toggled(was, line.key))}
              current={live && index === lines.length - 1}
              aside={aside}
            />
          ))}
        </div>
        {live && !following ? (
          <Button
            size="sm"
            variant="secondary"
            className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full shadow-md"
            onClick={() => {
              setFollowing(true)
              toEnd()
            }}
          >
            <ArrowDown />
            {t("Follow the session")}
          </Button>
        ) : null}
      </div>
    </div>
  )
}

/* The agent's plan, task by task: ticked once done, the one under way marked. */
export function PlanList({ tasks }: { tasks: Task[] }) {
  const t = useT()
  const progress = advance(tasks)
  if (!progress) return null
  return (
    <section data-slot="plan" aria-label={t("Plan")} className="bg-card rounded-lg border px-3 py-2">
      <div className="flex items-center justify-between gap-2 text-xs font-medium">
        <span>{t("Plan")}</span>
        <span className="text-muted-foreground font-mono tabular-nums">
          {progress.done} / {progress.total} · {progress.percent} %
        </span>
      </div>
      <Progress value={progress.percent} className="my-2" />
      <ul className="flex flex-col gap-1 text-sm">
        {tasks.map((task, index) => (
          <li
            key={index}
            data-status={task.status}
            className={cn(
              "flex items-start gap-1.5",
              task.status === "completed" && "text-muted-foreground line-through",
              task.status === "pending" && "text-muted-foreground"
            )}
          >
            {task.status === "completed" ? (
              <CircleCheck className="text-tr-green mt-0.5 size-3.5 shrink-0" />
            ) : task.status === "in_progress" ? (
              <LoaderCircle className="text-tr-violet mt-0.5 size-3.5 shrink-0 motion-safe:animate-spin" />
            ) : (
              <Circle className="mt-0.5 size-3.5 shrink-0" />
            )}
            <span className="min-w-0 break-words">{task.content}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** The dot that says a session is writing. */
export function Pulse({ className }: { className?: string }) {
  return (
    <span className={cn("relative inline-flex size-2 shrink-0", className)} aria-hidden>
      <span className="bg-tr-green relative inline-flex size-2 rounded-full motion-safe:animate-pulse" />
    </span>
  )
}

/* What a running card says, redrawn with every step: one line, the robot at
 * work and what the agent is on — « Ponos travaille… · Editing src/… ». A card
 * whose session this console has not heard from yet says what the board last
 * said, as it always did. Between two sessions — a rebase, the CI here or on
 * GitHub — it says that phase and how long it has lasted instead: the steps
 * of the session before it are over (see `phase.ts`). « starting… » lasts as
 * long as a start does.
 *
 * The bar under it is drawn only when it measures something it can name: the
 * agent's plan, its tooltip saying how many of its steps are done. A bar that
 * only moved, for a session without a plan, said nothing it could be asked
 * about, and the steps counted one by one are the session's page to say. */
export function CardLive({ ticket }: { ticket: Ticket }) {
  const t = useT()
  const { sessions } = useSteps()
  const now = useMinute(Boolean(ticket.phase))
  const phase = reading(ticket.phase, now)
  const quiet = Boolean(phase?.quiet)
  const session = quiet ? undefined : sessions.find((candidate) => candidate.source === ticket.short)
  const last = session ? lastWord(session.steps.filter((step) => step.label !== "Plan")) : undefined
  const advanced = quiet ? null : advance(session?.plan ?? [])
  // A session that has just started has nothing to say yet, and what the
  // board says is the session before it.
  const fresh = Boolean(phase && phase.young && !phase.said)
  const line = advanced?.current
    ? advanced.current
    : last
    ? last.said
      ? shorten(withoutProtocol(last.label)).replace(/[*_`#>]+/g, "").replace(/\s+/g, " ")
      : `${last.label}${last.detail ? ` · ${shorten(last.detail)}` : ""}`
    : quiet || fresh
      ? ""
      : ticket.progress
  const span = phase ? brief(phase.seconds) : null
  const lasted = span ? t("for {{span}}", { span: t(span.key, span.params) }) : ""
  const fallback = !phase
    ? t("starting…")
    : phase.said
      ? ""
      : phase.young
        ? t("starting…")
        : `${t("no step from the session yet")} · ${lasted}`
  const said = phase?.said ? `${t(phase.said.key, phase.said.params)} · ${lasted}` : ""
  const shown = said || line || fallback
  const steps = advanced
    ? t("{{done}} of the plan's {{total}} steps done", { done: String(advanced.done), total: String(advanced.total) })
    : ""

  return (
    <div className="flex min-w-0 flex-col gap-1.5 text-xs" data-slot="card-live">
      {/* Said first, and on every running card: a ticket just unblocked shows it
          as soon as it runs again, and a reloaded board shows it still. */}
      <p
        role="status"
        className="flex min-w-0 items-center gap-1.5"
        data-slot="card-working"
        title={[said && ticket.phase?.detail, line, shown].find(Boolean) || undefined}
      >
        <Robot state="thinking" size={20} className="shrink-0" />
        <span className="shrink-0 font-medium">{t("Ponos is working…")}</span>
        {shown ? (
          <span
            className="text-muted-foreground min-w-0 truncate"
            data-slot={said ? "card-phase" : "card-doing"}
          >
            · {shown}
          </span>
        ) : null}
      </p>
      {advanced ? (
        <div data-slot="card-plan" title={steps} className="flex items-center">
          <Progress value={advanced.percent} aria-label={steps} className="h-1" />
        </div>
      ) : null}
    </div>
  )
}

/** The time, again every half minute while `on`: a phase's length, and the end of « starting… ». */
function useMinute(on: boolean): number {
  const [now, setNow] = React.useState(() => Date.now())
  React.useEffect(() => {
    if (!on) return
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [on])
  return now
}
