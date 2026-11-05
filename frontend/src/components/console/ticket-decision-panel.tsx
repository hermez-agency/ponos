import * as React from "react"
import {
  CircleCheck,
  CircleDashed,
  CircleMinus,
  CircleX,
  ExternalLink,
  GitPullRequest,
  LoaderCircle,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { ModelChoice } from "@/components/console/model-input"
import { PreviewPairs } from "@/components/console/preview-pairs"
import { api, why } from "@/lib/api"
import { titleOf, useBoard } from "@/lib/board-store"
import {
  CHECKS,
  FILES_SHOWN,
  JOBS,
  PROMPTS,
  arranged,
  away,
  immediate,
  jobState,
  keyOf,
  labelOf,
  linesOf,
  prefilled,
  promptOf,
  sendable,
  titlesIn,
  tone,
} from "@/lib/decision"
import { useT } from "@/lib/i18n"
import type { Decision, Solution, Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"
import { canAct } from "@/lib/role"

/* The Decide tab of a ticket, and the panel the series draws for each of its
 * tickets: why it waits, and the choices — see `ticket-decision.tsx`, whose
 * buttons on the board's cards lead here. Apart from them, and fetched with the
 * ticket's page or the series: the board is the first page, and its first load
 * has a budget. */

/* The question a blocked ticket stopped on, as its discussion draws it: with
 * the discussion, which the first load does without. */
const Asked = React.lazy(() =>
  import("@/components/console/ticket-talk").then((module) => ({ default: module.Asked }))
)

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
      {/* What was brought back is for everybody to read; the choice, for whoever may make it. */}
      {canAct() ? <Choices decision={decision} ticket={ticket} onDone={onDone} /> : null}
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
      <Jobs decision={decision} />
      <Files decision={decision} />
      <PreviewPairs ticket={decision.id} shots={decision.previews} />
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

const JOB = {
  passed: { icon: CircleCheck, color: "text-tr-green" },
  failed: { icon: CircleX, color: "text-destructive" },
  skipped: { icon: CircleMinus, color: "text-muted-foreground" },
  pending: { icon: LoaderCircle, color: "text-tr-amber animate-spin" },
} as const

/* Each job of the pull request's CI, as GitHub said it when the panel opened:
 * which one is red, without the trip to GitHub on a phone. */
function Jobs({ decision }: { decision: Decision }) {
  const t = useT()
  const jobs = decision.checks?.listed ?? []
  if (!jobs.length) return null
  return (
    <section data-slot="decision-checks">
      <Heading>{t("Checks")}</Heading>
      <ul className="space-y-1 text-sm">
        {jobs.map((job, index) => {
          const state = jobState(job.bucket)
          const { icon: Icon, color } = JOB[state]
          const name = <span className="min-w-0 break-words">{job.name || "?"}</span>
          return (
            <li key={`${job.name}-${index}`} data-state={state} className="flex items-center gap-2">
              <Icon className={cn("size-4 shrink-0", color)} aria-label={t(JOBS[state])} />
              {job.link ? (
                <a href={job.link} target="_blank" rel="noreferrer" className="min-w-0 hover:underline">
                  {name}
                </a>
              ) : (
                name
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/* What the pull request touches, file by file with its lines, in place of the
 * diff, which is GitHub's to show and unreadable on a phone: enough to tell a
 * two-line fix from a rewrite. The first ones only, and how many more. */
function Files({ decision }: { decision: Decision }) {
  const t = useT()
  const files = decision.files ?? []
  if (!files.length) return null
  const { additions, deletions } = linesOf(files)
  const more = files.length - FILES_SHOWN
  return (
    <section data-slot="decision-files">
      <Heading>
        {t("Files changed")}{" "}
        <span className="text-muted-foreground font-mono text-sm font-normal tabular-nums">
          {files.length} · <span className="text-tr-green">+{additions}</span>{" "}
          <span className="text-destructive">−{deletions}</span>
        </span>
      </Heading>
      <ul className="space-y-1 font-mono text-xs">
        {files.slice(0, FILES_SHOWN).map((file) => (
          <li key={file.path} className="flex items-baseline gap-2">
            <span className="min-w-0 flex-1 break-all">{file.path}</span>
            <span className="text-tr-green shrink-0 tabular-nums">+{file.additions}</span>
            <span className="text-destructive shrink-0 tabular-nums">−{file.deletions}</span>
          </li>
        ))}
      </ul>
      {more > 0 ? (
        <p className="text-muted-foreground mt-1 text-xs">
          {decision.pull_request ? (
            <a href={`${decision.pull_request}/files`} target="_blank" rel="noreferrer" className="hover:underline">
              {t("and {{count}} more", { count: String(more) })}
            </a>
          ) : (
            t("and {{count}} more", { count: String(more) })
          )}
        </p>
      ) : null}
    </section>
  )
}

/* The choices, one button each, numbered, and the ways out apart under a rule.
 * One that needs words opens its field under it — Abandon and Reject too, a
 * note and a Confirm between the click and the move. */
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
  const { forward, out } = arranged(decision.solutions)

  // One choice, at its place in the order they are numbered in.
  const choice = (solution: Solution, place: number) => (
    <li key={`${solution.key}-${solution.number}`}>
      <Button
        variant={tone(solution, same(solution, chosen))}
        disabled={busy}
        data-solution={solution.key}
        data-number={solution.number}
        data-key={keyOf(place) || undefined}
        aria-keyshortcuts={keyOf(place) || undefined}
        aria-expanded={immediate(solution) ? undefined : same(solution, chosen)}
        className={cn(
          "h-auto min-h-11 w-full justify-start py-2 text-left text-base whitespace-normal",
          away(solution) && !same(solution, chosen) && "text-destructive hover:text-destructive"
        )}
        onClick={() => (same(solution, chosen) ? setChosen(null) : pick(solution))}
      >
        {/* Said by aria-keyshortcuts instead: the button keeps its name. */}
        <span aria-hidden="true" className="text-xs tabular-nums opacity-70">
          {place}.
        </span>
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
            <ModelChoice
              value={model}
              onChange={setModel}
              extra={models.map((one) => one.value)}
              empty={t(PROMPTS.model)}
              label={t(PROMPTS.model)}
              className="h-9 w-full"
            />
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
  )

  return (
    <section data-slot="decision-choices">
      <Heading>{t("Your decision")}</Heading>
      <ul className="space-y-2">{forward.map((solution, index) => choice(solution, index + 1))}</ul>
      {out.length ? (
        <ul data-slot="decision-away" className="mt-4 space-y-2 border-t pt-4">
          {out.map((solution, index) => choice(solution, forward.length + index + 1))}
        </ul>
      ) : null}
    </section>
  )
}
