import * as React from "react"
import { ArrowUp, GitFork, LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useSteps } from "@/hooks/use-console"
import { api, why } from "@/lib/api"
import { counted, useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import { prepended } from "@/lib/outline"
import { planOf, type Task } from "@/lib/plan"
import { canAct } from "@/lib/role"
import type { Run, Step, Ticket } from "@/lib/types"

import { EmptyState } from "./empty-state"
import { PlanList, Pulse, SessionLog } from "./session-log"
import { when } from "./ticket-bits"

/* A ticket's journal, as its page reads it: every run of the ticket, and what
 * can be done from one of their steps.
 *
 * Apart from `session-log.tsx`, which the board's cards carry into the first
 * load (`CardLive`): only an opened ticket draws this, and its page is fetched
 * when it is (tests/test_release.py holds the first load to a budget). The
 * lines themselves are `SessionLog`'s; what ends a step's line here — starting
 * a new session from it, the runs that did (`forks.py`) — is this file's.
 */

const ForkDialog = React.lazy(() => import("./fork-dialog").then((module) => ({ default: module.ForkDialog })))

/* What a journal offers on its steps: starting a new session from one of them
 * (`ask`, absent where nobody can — a run still going, a reader's console),
 * and the runs that did start from one, by the number the list gives them. */
export interface Forks {
  ask?: (step: Step) => void
  branches: Map<number, number[]>
}

/* At the end of a step's line: the runs started again from it, and the button
 * that starts one more — shown when the line is pointed at, or reached by the
 * keyboard, so that a journal of a thousand steps is not a thousand buttons. */
export function StepForks({ step, forks }: { step: Step; forks?: Forks }) {
  const t = useT()
  if (!forks || step.position === undefined) return null
  const branches = forks.branches.get(step.position) ?? []
  const ask = forks.ask && step.forkable ? forks.ask : undefined
  if (!branches.length && !ask) return null
  return (
    <span className="ml-auto flex shrink-0 items-center gap-1 pl-1">
      {branches.length ? (
        <span
          data-slot="step-branches"
          className="text-tr-violet inline-flex items-center gap-0.5 font-mono text-[0.7rem]"
          title={t("Started again from here")}
        >
          <GitFork aria-hidden="true" className="size-3" />
          {branches.map((number) => `#${number}`).join(" ")}
        </span>
      ) : null}
      {ask ? (
        <button
          type="button"
          data-slot="step-fork"
          aria-label={t("Start again from here")}
          title={t("Start again from here")}
          onClick={(event) => {
            // Inside a `summary`: the click starts a session, it does not unfold the line.
            event.preventDefault()
            event.stopPropagation()
            ask(step)
          }}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 rounded p-0.5 outline-none focus-visible:ring-2 sm:opacity-0 sm:group-hover/step:opacity-100 sm:focus-visible:opacity-100"
        >
          <GitFork className="size-3.5" />
        </button>
      ) : null}
    </span>
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

  const id = run?.id
  React.useEffect(() => {
    if (id === undefined) return
    let alive = true
    held.current = { run: id, last: 0, loaded: false }
    setRead({ steps: [], count: 0, more: false, loading: true })
    api
      .runSteps(id)
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
  }, [id])

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

/** One run in the list of a ticket's runs: when, how it ended, what it cost — and the
 * run it started again from, `#2 ↳ 12` for its step 12. */
function runLabel(run: Run, number: number, t: (text: string) => string, parent?: number): string {
  const parts = [`#${number}`, when(run.started_at), outcomeOf(run, t)]
  if (parent !== undefined) parts.splice(1, 0, `↳ #${parent}·${run.parent_position ?? "?"}`)
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
 * choice away. Only the newest can be live, and only while it has no end.
 *
 * A run started again from a step of another (`forks.py`) is a branch: it says
 * which run and step it came from, a click away, and that run marks the step
 * with the numbers of the runs that branched there. The newest run is the
 * current branch, the one the ticket goes on from — said in the list. */
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
  const [forking, setForking] = React.useState<Step | null>(null)
  const run = runs.find((candidate) => candidate.id === chosen) ?? runs[0]
  const writing = live && run.id === runs[0].id && !run.ended_at
  const read = useRunSteps(run, writing ? signal : 0)
  const numbers = React.useMemo(
    () => new Map(runs.map((candidate, index) => [candidate.id, runs.length - index])),
    [runs]
  )
  const branched = runs.some((candidate) => candidate.parent != null)
  const forks = React.useMemo<Forks>(() => {
    const branches = new Map<number, number[]>()
    for (const candidate of runs) {
      const number = numbers.get(candidate.id)
      if (candidate.parent !== run.id || candidate.parent_position == null || number === undefined) continue
      branches.set(candidate.parent_position, [...(branches.get(candidate.parent_position) ?? []), number])
    }
    // Not under a session still going: it is the one to stop first.
    return { ask: canAct() && !live && run.ended_at ? setForking : undefined, branches }
  }, [runs, numbers, run.id, run.ended_at, live])
  const aside = React.useCallback((step: Step) => <StepForks step={step} forks={forks} />, [forks])
  const parent = run.parent != null ? numbers.get(run.parent) : undefined

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
                  {runLabel(
                    candidate,
                    runs.length - index,
                    t,
                    candidate.parent != null ? numbers.get(candidate.parent) : undefined
                  )}
                  {branched && index === 0 ? ` · ${t("current branch")}` : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </div>
      {run.parent != null ? (
        <p data-slot="run-parent" className="text-muted-foreground flex items-center gap-1.5 text-xs">
          <GitFork aria-hidden="true" className="size-3 shrink-0" />
          {parent !== undefined ? (
            <button
              type="button"
              className="hover:text-foreground underline-offset-2 hover:underline"
              onClick={() => setChosen(run.parent ?? null)}
            >
              {t("Started again from step {{step}} of session #{{run}}", {
                step: run.parent_position ?? "?",
                run: parent,
              })}
            </button>
          ) : (
            t("Started again from step {{step}} of an earlier session", { step: run.parent_position ?? "?" })
          )}
        </p>
      ) : null}
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
          <SessionLog key={run.id} steps={read.steps} live={writing} cut={read.more} aside={aside} />
        </>
      )}
      {forking ? (
        <React.Suspense fallback={null}>
          <ForkDialog run={run} step={forking} onClose={() => setForking(null)} />
        </React.Suspense>
      ) : null}
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
