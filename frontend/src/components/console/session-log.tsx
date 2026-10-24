import * as React from "react"
import { ArrowDown, ArrowUp, ChevronRight, ChevronsDownUp, ChevronsUpDown, Circle, CircleCheck, LoaderCircle, TriangleAlert } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useSteps } from "@/hooks/use-console"
import { api, why } from "@/lib/api"
import { counted, useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import { clock } from "@/lib/composer"
import { FOLDED, everythingOpen, isOpen, outline, prepended, toggled, type Line, type Unfolded } from "@/lib/outline"
import { reading } from "@/lib/phase"
import { advance, planOf, readPlan, type Task } from "@/lib/plan"
import { doing } from "@/lib/thinking"
import type { Run, Step, Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"
import { brief } from "@/lib/worktime"

import { EmptyState } from "./empty-state"
import { Markdown } from "./markdown"
import { Robot } from "./robot"
import { when } from "./ticket-bits"

/* A ticket's session, read from the ticket.
 *
 * Its steps come from the local journal (`journal.py`): every run of the
 * ticket, each read a page at a time from its end, the newest followed while
 * it goes on. A ticket that last ran before there was a journal is read from
 * its last log, as it used to be.
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

/** What a card says a running ticket is doing: what the agent last said, or else the last tool. */
export function lastWord(steps: Step[]): Step | undefined {
  return steps.findLast((step) => step.said) ?? steps[steps.length - 1]
}

/** How close to the bottom still counts as following it. */
const NEAR = 24

/** One tool call, folded to a line; a click unfolds it. */
function ToolLine({ step }: { step: Step }) {
  const plan = step.label === "Plan" ? advance(readPlan(step.detail)) : null
  // The list is drawn by the plan itself; its line only says how far it is.
  const detail = plan ? `${plan.done}/${plan.total}` : shorten(step.detail)
  const failed = step.label === "Error"
  return (
    <details className="group">
      <summary
        className={cn(
          "hover:bg-muted/60 flex cursor-pointer list-none items-start gap-1.5 rounded px-1 py-0.5 font-mono text-xs [&::-webkit-details-marker]:hidden",
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
}: {
  line: Line<Step>
  lead: string
  open: boolean
  onToggle: () => void
  current: boolean
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
      {line.said ? (
        <Markdown text={shorten(line.said.label)} />
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
                <ToolLine key={step.position ?? index} step={step} />
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
 * so the steps before the first thing said are not its beginning. */
export function SessionLog({
  steps,
  live,
  offset = 0,
  cut = false,
  className,
}: {
  steps: Step[]
  live: boolean
  offset?: number
  cut?: boolean
  className?: string
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

/* The journal of a ticket whose runs predate the local journal, read back
 * from its last log — asked again whenever the ticket moves, which is when a
 * run ends. */
function useFinalLog(ticket: Ticket, wanted: boolean) {
  const [read, setRead] = React.useState<{ steps: Step[]; loading: boolean }>({
    steps: [],
    loading: wanted,
  })
  React.useEffect(() => {
    if (!wanted) return
    let alive = true
    setRead((was) => ({ ...was, loading: true }))
    api
      .logs(ticket.short)
      .then(({ logs }) => (logs[0] ? api.log(logs[0].name) : { steps: [] as Step[] }))
      .then((payload) => alive && setRead({ steps: payload.steps, loading: false }))
      .catch(() => alive && setRead({ steps: [], loading: false }))
    return () => {
      alive = false
    }
  }, [ticket.short, ticket.column, wanted])
  return read
}

/* Every run of a ticket the local journal holds, newest first — asked again
 * when the ticket moves or a session starts or ends, which is when one is
 * added or closed. `null` until the first answer. */
function useRuns(ticket: Ticket, live: boolean) {
  const [runs, setRuns] = React.useState<Run[] | null>(null)
  React.useEffect(() => {
    let alive = true
    api
      .runs(ticket.id)
      .then((payload) => alive && setRuns(payload.runs))
      .catch(() => alive && setRuns([]))
    return () => {
      alive = false
    }
  }, [ticket.id, ticket.column, live])
  return runs
}

interface Read {
  steps: Step[]
  count: number
  more: boolean
  loading: boolean
}

/* One run's steps, read from the journal a page at a time: its end first,
 * then — on request — what came before. While the run goes on, every step the
 * stream announces (`signal`, the count it has seen) is a reason to ask the
 * journal for what follows the last step held: the stream says *that* the run
 * moved, the journal says *what* it did, numbered, so nothing is shown twice. */
function useRunSteps(run: Run | undefined, signal: number) {
  const [read, setRead] = React.useState<Read>({ steps: [], count: 0, more: false, loading: true })
  const held = React.useRef<{ run?: number; last: number; loaded: boolean }>({ last: 0, loaded: false })

  React.useEffect(() => {
    if (!run) return
    let alive = true
    held.current = { run: run.id, last: 0, loaded: false }
    setRead({ steps: [], count: 0, more: false, loading: true })
    api
      .runSteps(run.id)
      .then((page) => {
        if (!alive) return
        held.current.last = page.steps[page.steps.length - 1]?.position ?? 0
        held.current.loaded = true
        setRead({ steps: page.steps, count: page.count, more: page.more, loading: false })
      })
      .catch(() => alive && setRead({ steps: [], count: 0, more: false, loading: false }))
    return () => {
      alive = false
    }
  }, [run?.id])

  const ended = run?.ended_at
  React.useEffect(() => {
    if (!run || held.current.run !== run.id || !held.current.loaded) return
    const timer = window.setTimeout(() => {
      const asked = run.id
      api
        .runSteps(asked, { after: held.current.last })
        .then((page) => {
          if (held.current.run !== asked || !page.steps.length) return
          const fresh = page.steps.filter((step) => (step.position ?? 0) > held.current.last)
          if (!fresh.length) return
          held.current.last = fresh[fresh.length - 1].position ?? held.current.last
          setRead((was) => ({ ...was, steps: [...was.steps, ...fresh], count: page.count }))
        })
        .catch(() => undefined)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [run, signal, ended])

  // One page of older steps at a time: a second click while the first is read
  // would ask for the same page, and add it twice.
  const t = useT()
  const [busy, setBusy] = React.useState(false)
  const asking = React.useRef(false)
  const earlier = React.useCallback(() => {
    const first = read.steps[0]?.position
    if (!run || !first || asking.current) return
    const asked = run.id
    asking.current = true
    setBusy(true)
    api
      .runSteps(asked, { before: first })
      .then((page) => {
        if (held.current.run !== asked) return
        setRead((was) => ({ ...was, steps: prepended(page.steps, was.steps), more: page.more }))
      })
      .catch((error: unknown) => {
        if (held.current.run !== asked) return
        toast.error(t("The earlier steps could not be read"), { description: why(error) })
      })
      .finally(() => {
        asking.current = false
        setBusy(false)
      })
  }, [run, read.steps, t])

  return { ...read, earlier, busy }
}

/** How a run ended, in a word: the column a ticket goes to, or "still going". */
function outcomeOf(run: Run, t: (text: string) => string): string {
  if (!run.ended_at) return t("going on")
  return (
    {
      done: t("done"),
      blocked: t("blocked"),
      failed: t("failed"),
      waiting: t("waiting for credit"),
      validated: t("validated"),
    }[run.status ?? ""] ??
    run.status ??
    ""
  )
}

/** One run in the list of a ticket's runs: when, how it ended, what it cost. */
function runLabel(run: Run, number: number, t: (text: string) => string): string {
  const parts = [`#${number}`, when(run.started_at), outcomeOf(run, t)]
  if (run.model_label) parts.push(run.model_label)
  if (typeof run.cost_usd === "number" && run.cost_usd) parts.push(money(run.cost_usd))
  return parts.filter(Boolean).join(" · ")
}

/** A ticket's session: live while it runs, read-only once it has ended. */
export function TicketLive({ ticket }: { ticket: Ticket }) {
  const { sessions } = useSteps()
  const session = sessions.find((candidate) => candidate.source === ticket.short)
  const live = Boolean(session) || ticket.column === "running"
  const runs = useRuns(ticket, live)

  if (runs === null)
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </div>
    )
  // A ticket whose runs all came before the journal: its last log, as it
  // always was read.
  if (!runs.length) return <LogLive ticket={ticket} live={live} />
  return <JournalLive runs={runs} live={live} signal={session?.count ?? 0} plan={session?.plan ?? []} />
}

/* The runs of a ticket, from the journal: the newest open, the others a
 * choice away. Only the newest can be live, and only while it has no end. */
function JournalLive({
  runs,
  live,
  signal,
  plan,
}: {
  runs: Run[]
  live: boolean
  signal: number
  plan: Task[]
}) {
  const t = useT()
  const [chosen, setChosen] = React.useState<number | null>(null)
  const run = runs.find((candidate) => candidate.id === chosen) ?? runs[0]
  const writing = live && run.id === runs[0].id && !run.ended_at
  const read = useRunSteps(run, writing ? signal : 0)

  return (
    <div className="flex flex-col gap-2">
      <div className="text-muted-foreground flex flex-wrap items-center gap-2 font-mono text-[0.7rem]">
        {writing ? <Pulse /> : null}
        {writing
          ? t("writing now")
          : run.id === runs[0].id
            ? t("the last session, read-only")
            : t("an earlier session, read-only")}
        <span>·</span>
        {counted(read.count, "{{count}} step", "{{count}} steps")}
        {runs.length > 1 ? (
          <Select value={String(run.id)} onValueChange={(value) => setChosen(Number(value))}>
            <SelectTrigger size="sm" className="ml-auto h-7 font-sans text-xs" aria-label={t("Run")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {runs.map((candidate, index) => (
                <SelectItem key={candidate.id} value={String(candidate.id)}>
                  {runLabel(candidate, runs.length - index, t)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </div>
      {run.ended_at && run.reason ? (
        <p className="text-muted-foreground truncate text-xs" title={run.reason}>
          {outcomeOf(run, t)} · {run.reason}
        </p>
      ) : null}
      {read.loading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-full" />
        </div>
      ) : !read.steps.length ? (
        <EmptyState robot={writing ? "working" : "sleep"}>
          {writing
            ? t("The session has not written anything yet. Its first step appears here as it happens.")
            : t("This run wrote no step.")}
        </EmptyState>
      ) : (
        <>
          {read.more ? (
            <Button
              size="sm"
              variant="ghost"
              className="self-center"
              onClick={read.earlier}
              disabled={read.busy}
              aria-busy={read.busy || undefined}
            >
              {read.busy ? <LoaderCircle className="animate-spin" /> : <ArrowUp />}
              {t("Earlier steps")}
            </Button>
          ) : null}
          <PlanList tasks={writing && plan.length ? plan : planOf(read.steps)} />
          <SessionLog key={run.id} steps={read.steps} live={writing} cut={read.more} />
        </>
      )}
    </div>
  )
}

/* The journal as it was read before there was one: the stream while a run
 * goes on, the last log once it is over. */
function LogLive({ ticket, live }: { ticket: Ticket; live: boolean }) {
  const t = useT()
  const { sessions, ticketSteps } = useSteps()
  const session = sessions.find((candidate) => candidate.source === ticket.short)
  const final = useFinalLog(ticket, !live)

  const steps = session?.steps.length ? session.steps : live ? ticketSteps : final.steps
  // The stream keeps the last steps of a session, and counts the ones it let go.
  const offset = live ? Math.max(0, (session?.count ?? steps.length) - steps.length) : 0

  if (!live && final.loading)
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </div>
    )

  if (!steps.length)
    return (
      <EmptyState robot={live ? "working" : "sleep"}>
        {live
          ? t("The session has not written anything yet. Its first step appears here as it happens.")
          : t("No journal is left for this ticket: its session log is gone, or it never ran.")}
      </EmptyState>
    )

  return (
    <div className="flex flex-col gap-2">
      <p className="text-muted-foreground flex items-center gap-2 font-mono text-[0.7rem]">
        {live ? <Pulse /> : null}
        {live ? t("writing now") : t("the last session, read-only")}
        <span>·</span>
        {counted(session?.count || steps.length, "{{count}} step", "{{count}} steps")}
      </p>
      <PlanList tasks={session?.plan.length ? session.plan : planOf(steps)} />
      <SessionLog steps={steps} live={live} offset={offset} cut={offset > 0} />
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
      <span className="bg-tr-green absolute inset-0 animate-ping rounded-full opacity-60" />
      <span className="bg-tr-green relative inline-flex size-2 rounded-full" />
    </span>
  )
}

/* What a running card says, redrawn with every step: the dot, what the agent
 * is on, and how many steps it has taken. A card whose session this console
 * has not heard from yet says what the board last said, as it always did.
 * Between two sessions — a rebase, the CI here or on GitHub — it says that
 * phase and how long it has lasted instead: the steps of the session before
 * it are over (see `phase.ts`). « starting… » lasts as long as a start does. */
export function CardLive({ ticket }: { ticket: Ticket }) {
  const t = useT()
  const { sessions } = useSteps()
  const now = useMinute(Boolean(ticket.phase))
  const phase = reading(ticket.phase, now)
  const quiet = Boolean(phase?.quiet)
  const session = quiet ? undefined : sessions.find((candidate) => candidate.source === ticket.short)
  const last = session ? lastWord(session.steps.filter((step) => step.label !== "Plan")) : undefined
  const advanced = advance(session?.plan ?? [])
  // A session that has just started has nothing to say yet, and what the
  // board says is the session before it.
  const fresh = Boolean(phase && phase.young && !phase.said)
  const line = advanced?.current
    ? advanced.current
    : last
    ? last.said
      ? shorten(last.label).replace(/[*_`#>]+/g, "").replace(/\s+/g, " ")
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
  const shown = line || fallback

  // Without a step yet there is no counter to put on its own line: the dot
  // goes in front of what the card says instead of standing alone above it.
  const counter = session?.count ? (
    <span className="tabular-nums">
      {counted(session.count, "{{count}} step", "{{count}} steps")}
    </span>
  ) : null
  const dot = (
    <>
      <Pulse />
      <span className="sr-only">{t("writing now")}</span>
    </>
  )

  return (
    <div className="flex flex-col gap-1 text-xs" data-slot="card-live">
      {/* Said first, and on every running card: a ticket just unblocked shows it
          as soon as it runs again, and a reloaded board shows it still. */}
      <div role="status" className="flex items-center gap-1.5 font-medium" data-slot="card-working">
        <Robot state="thinking" size={28} className="shrink-0" />
        {t("Ponos is working…")}
      </div>
      {counter ? (
        <div className="text-muted-foreground flex items-center gap-1.5 font-mono text-[0.7rem] whitespace-nowrap">
          {dot}
          {counter}
        </div>
      ) : null}
      {phase?.said ? (
        <p
          className="text-muted-foreground flex items-center gap-1.5"
          data-slot="card-phase"
          title={ticket.phase?.detail || undefined}
        >
          {counter ? null : dot}
          <span className="min-w-0 truncate">
            {t(phase.said.key, phase.said.params)} · {lasted}
          </span>
        </p>
      ) : null}
      {/* A plan gives a figure; without one the bar only moves, it never guesses. */}
      {quiet ? null : (
        <div data-slot="card-plan" className="flex flex-col gap-1">
          <Progress value={advanced?.percent} />
          {advanced ? (
            <span className="text-muted-foreground font-mono text-[0.7rem] tabular-nums">
              {advanced.done} / {advanced.total} · {advanced.percent} %
            </span>
          ) : null}
        </div>
      )}
      {shown ? (
        <p className="text-muted-foreground flex items-center gap-1.5" title={line || undefined}>
          {counter || phase?.said ? null : dot}
          <span className="min-w-0 truncate">{shown}</span>
        </p>
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
