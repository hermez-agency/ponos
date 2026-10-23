import * as React from "react"
import { useLocation } from "@tanstack/react-router"
import { ArrowLeft, ArrowRight, CircleCheck, ExternalLink, ServerCrash, XIcon } from "lucide-react"
import { useNavigate } from "react-resource-view"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Robot } from "@/components/console/robot"
import { ProjectThumb } from "@/components/console/project-picture"
import { FAMILY_ICON, blockSaid, familyColor } from "@/components/console/ticket-bits"
import { TicketDecision } from "@/components/console/ticket-decision"
import { api, why } from "@/lib/api"
import { patchTicket, titleOf, useBoard } from "@/lib/board-store"
import { isTyping } from "@/lib/hotkeys"
import { counted, useT } from "@/lib/i18n"
import {
  type Outcome,
  type SeriesColumn,
  nextOf,
  ordered,
  previousOf,
  seriesIn,
  tally,
  withSeries,
} from "@/lib/series"
import type { Solution, Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"
import { ticketHref } from "@/resources/tickets"

/* The tickets waiting on you, one after another.
 *
 * Five blocked cards were five round trips: open one, answer it, close it, look
 * for the next on the board, open it again. Here the column is one window over
 * the page: the ticket on screen, its decision panel as its Decide tab draws
 * it (`TicketDecision`), and once it is decided the next one, without a trip
 * back. The same window goes through the tickets in review, with the panel
 * that decides them — one component, told which column.
 *
 * The address holds it (`?series=blocked`, over whatever page is under it), so
 * Back closes it and a link opens it again. The order is `series.ts`'s: what
 * you can settle at once first. The board is the stream's, live: a ticket that
 * leaves the column elsewhere — its session, Notion, another tab — leaves the
 * series as it happens, and one that arrives joins it at the end. One you
 * decided stays in the list, ticked, so the count you started with still adds
 * up; and the last one decided can be taken back, which puts it back in its
 * column.
 */

/** How long a decided ticket stays on screen, ticked, before the next one comes. */
const SETTLE = 700

const WORDS: Record<SeriesColumn, { title: string; description: string; settled: string; empty: string }> = {
  blocked: {
    title: "Unblock",
    description: "The blocked tickets, one after another",
    settled: "Ticket unblocked",
    empty: "Nothing left to unblock.",
  },
  review: {
    title: "Decide",
    description: "The tickets in review, one after another",
    settled: "Ticket decided",
    empty: "Nothing left to decide.",
  },
}

/** The series the address names, if it names one: drawn over every page. */
export function TicketSeries() {
  const { pathname, searchStr } = useLocation()
  const navigate = useNavigate()
  const column = seriesIn(searchStr)
  if (!column) return null
  const close = () => void navigate({ to: `${pathname}${withSeries(searchStr, null)}` })
  return <Series key={column} column={column} onClose={close} />
}

function Series({ column, onClose }: { column: SeriesColumn; onClose: () => void }) {
  const t = useT()
  const board = useBoard()
  const words = WORDS[column]
  const loaded = board.columns.length > 0
  const live = React.useMemo(
    () => board.tickets.filter((ticket) => ticket.column === column),
    [board.tickets, column]
  )
  const liveIds = React.useMemo(() => new Set(live.map((ticket) => ticket.id)), [live])

  // The tickets as they were last seen: a decided one has left the column, and is still named in the list.
  const seen = React.useRef(new Map<string, Ticket>())
  for (const ticket of live) seen.current.set(ticket.id, ticket)

  const [queue, setQueue] = React.useState<string[] | null>(null)
  const [outcomes, setOutcomes] = React.useState<Record<string, Outcome>>({})
  const [current, setCurrent] = React.useState<string | null>(null)
  const [finished, setFinished] = React.useState(false)
  // The ticket on its way out — decided here, or gone elsewhere — before the next one comes.
  const [leaving, setLeaving] = React.useState<{ id: string; why: "done" | "gone" } | null>(null)
  // The last one decided, and the column it went to: it can still be taken back.
  const [undoable, setUndoable] = React.useState<{ id: string; to: string } | null>(null)

  // The order is taken once, when the board is there; a ticket that arrives later joins at the end.
  React.useEffect(() => {
    if (!loaded) return
    setQueue((was) => {
      if (!was) return ordered(live).map((ticket) => ticket.id)
      const fresh = ordered(live.filter((ticket) => !was.includes(ticket.id)))
      return fresh.length ? [...was, ...fresh.map((ticket) => ticket.id)] : was
    })
  }, [loaded, live])

  // What the list holds: the ones still in the column, the ones decided here, and the one on screen.
  const items = React.useMemo(
    () => (queue ?? []).filter((id) => liveIds.has(id) || outcomes[id] === "done" || id === current),
    [queue, liveIds, outcomes, current]
  )

  // The first one, once there is a list — and as soon as one comes, when the column was empty.
  React.useEffect(() => {
    if (queue && current === null && !finished) {
      const first = nextOf(items, outcomes, null)
      if (first) setCurrent(first)
    }
  }, [queue, current, finished, items, outcomes])

  const advance = React.useCallback(
    (from: string | null, settled: Record<string, Outcome>) => {
      const next = nextOf(items, settled, from)
      setLeaving(null)
      if (next) setCurrent(next)
      else {
        setCurrent(null)
        setFinished(true)
      }
    },
    [items]
  )

  // The one on screen left the column elsewhere: said, then the next one.
  React.useEffect(() => {
    if (current && queue && !liveIds.has(current) && outcomes[current] !== "done" && !leaving)
      setLeaving({ id: current, why: "gone" })
  }, [current, queue, liveIds, outcomes, leaving])

  React.useEffect(() => {
    if (!leaving) return
    const timer = window.setTimeout(() => advance(leaving.id, outcomes), SETTLE)
    return () => window.clearTimeout(timer)
  }, [leaving, outcomes, advance])

  // Told by the panel once its decision is sent — maybe after the stream said the ticket moved, and the series went on.
  const shown = React.useRef(current)
  shown.current = current
  const decided = (id: string, solution: Solution) => {
    setOutcomes((was) => ({ ...was, [id]: "done" }))
    setUndoable({ id, to: solution.column })
    if (shown.current === id) setLeaving({ id, why: "done" })
  }

  const skip = () => {
    if (!current || leaving) return
    const settled: Record<string, Outcome> = outcomes[current] ? outcomes : { ...outcomes, [current]: "skipped" }
    setOutcomes(settled)
    advance(current, settled)
  }

  const previous = previousOf(items, outcomes, current)
  const back = () => {
    if (!previous || leaving) return
    setFinished(false)
    setCurrent(previous)
  }

  const jump = (id: string) => {
    if (outcomes[id] === "done") return
    setLeaving(null)
    setFinished(false)
    setCurrent(id)
  }

  const undo = async () => {
    if (!undoable) return
    const { id, to } = undoable
    setUndoable(null)
    try {
      // Straight to the server, from where the decision sent it: the move may
      // still be queued, and the board not have heard of it yet.
      await api.setStatus(id, column, board.columns.find((one) => one.key === to)?.name)
      patchTicket(id, { column, sync: "pending", sync_error: "" })
    } catch (error) {
      toast.error(t("The ticket was not put back"), { description: why(error) })
      return
    }
    setOutcomes(({ [id]: _, ...rest }) => rest)
    setLeaving(null)
    setFinished(false)
    setCurrent(id)
  }

  const again = () => {
    const skipped = items.filter((id) => outcomes[id] === "skipped" && liveIds.has(id))
    setOutcomes(Object.fromEntries(Object.entries(outcomes).filter(([, outcome]) => outcome === "done")))
    setFinished(false)
    setCurrent(skipped[0] ?? null)
  }

  // The keys: → and J pass, ← and K go back, a digit picks the choice it numbers. Escape is the dialog's.
  const panel = React.useRef<HTMLDivElement>(null)
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.ctrlKey || event.metaKey || event.altKey || isTyping(event.target as HTMLElement)) return
    const key = event.key.toLowerCase()
    if (key === "arrowright" || key === "j") skip()
    else if (key === "arrowleft" || key === "k") back()
    else if (/^[1-9]$/.test(key)) {
      const choice = panel.current?.querySelector<HTMLButtonElement>(`[data-key="${key}"]:not(:disabled)`)
      if (!choice) return
      choice.click()
    } else return
    event.preventDefault()
  }

  // The focus on the ticket on screen, each time another comes: a reader hears which.
  React.useEffect(() => {
    if (current) panel.current?.focus({ preventScroll: true })
  }, [current])

  const ticket = current ? (seen.current.get(current) ?? null) : null
  const at = current ? items.indexOf(current) + 1 : items.length
  const counts = tally(items, outcomes)
  const progress = items.length ? (counts.done + counts.skipped) / items.length : 1
  const position = t("Ticket {{at}} of {{count}}", { at: String(at), count: String(items.length) })

  return (
    <Dialog open onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent
        data-series-window={column}
        showCloseButton={false}
        aria-modal="true"
        onKeyDown={onKeyDown}
        // The focus goes to the ticket, not to the first button of the list.
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          panel.current?.focus({ preventScroll: true })
        }}
        className="top-0 left-0 flex h-dvh w-full max-w-none translate-x-0 translate-y-0 flex-col gap-0 rounded-none border-0 p-0 sm:top-4 sm:left-4 sm:h-[calc(100dvh-2rem)] sm:w-[calc(100%-2rem)] sm:max-w-none sm:rounded-2xl sm:border"
      >
        <header className="flex flex-col gap-2 border-b px-4 pt-3 pb-2 sm:px-6">
          <div className="flex items-center gap-3">
            <DialogTitle className="text-base">{t(words.title)}</DialogTitle>
            <DialogDescription className="sr-only">{t(words.description)}</DialogDescription>
            {items.length ? (
              <span data-slot="series-position" className="text-muted-foreground font-mono text-sm tabular-nums">
                {finished ? items.length : at} / {items.length}
              </span>
            ) : null}
            <Button
              variant="ghost"
              size="icon-sm"
              className="ms-auto"
              title={t("Close")}
              aria-label={t("Close")}
              onClick={onClose}
            >
              <XIcon />
            </Button>
          </div>
          {/* Drawn once there is a series to go through: full on an empty one, it said "done" about nothing. */}
          {items.length ? (
            <div
              role="progressbar"
              aria-label={t(words.description)}
              aria-valuemin={0}
              aria-valuemax={items.length}
              aria-valuenow={counts.done + counts.skipped}
              className="bg-muted h-1.5 overflow-hidden rounded-full"
            >
              <div
                className="bg-primary h-full rounded-full transition-[width] duration-300"
                style={{ width: `${Math.round(progress * 100)}%` }}
              />
            </div>
          ) : null}
          {items.length ? (
            <ol data-slot="series-list" className="scroll-thin -mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
              {items.map((id, index) => (
                <li key={id} className="shrink-0">
                  <Entry
                    ticket={seen.current.get(id)}
                    number={index + 1}
                    outcome={outcomes[id]}
                    current={id === current && !finished}
                    gone={!liveIds.has(id) && outcomes[id] !== "done"}
                    onClick={() => jump(id)}
                  />
                </li>
              ))}
            </ol>
          ) : null}
          {/* Said to a screen reader as it changes: which ticket, and what became of the last one. */}
          <p className="sr-only" aria-live="polite">
            {finished ? "" : position}
          </p>
          {undoable && (leaving?.why === "done" || finished || current !== undoable.id) ? (
            <p
              role="status"
              data-slot="series-settled"
              className="bg-tr-green/10 text-foreground flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm"
            >
              <CircleCheck className="text-tr-green size-4 shrink-0" />
              <span className="min-w-0 flex-1 truncate">
                {t(words.settled)}
                {seen.current.get(undoable.id) ? ` — ${titleOf(seen.current.get(undoable.id)!)}` : ""}
              </span>
              <Button variant="ghost" size="xs" onClick={() => void undo()}>
                {t("Undo")}
              </Button>
            </p>
          ) : null}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {finished || (!items.length && queue) ? (
            <Recap
              column={column}
              done={counts.done}
              skipped={counts.skipped}
              onAgain={again}
              onClose={onClose}
            />
          ) : ticket ? (
            <section
              key={ticket.id}
              ref={panel}
              tabIndex={-1}
              aria-label={`${position} — ${titleOf(ticket)}`}
              data-series-ticket={ticket.id}
              className={cn(
                "animate-in fade-in slide-in-from-right-4 mx-auto flex max-w-3xl flex-col gap-4 px-4 py-5 outline-none duration-300 sm:px-6",
                leaving && "opacity-50 transition-opacity"
              )}
            >
              <div className="flex flex-col gap-2">
                <p className="text-muted-foreground font-mono text-xs">#{ticket.short}</p>
                <h2 className="text-xl leading-snug font-semibold break-words">{titleOf(ticket)}</h2>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                  {ticket.project ? (
                    <span className="text-muted-foreground flex min-w-0 items-center gap-1.5">
                      <ProjectThumb
                        project={{ name: ticket.project, icon: ticket.project_icon }}
                        className="size-5 rounded-full border-0"
                      />
                      <span className="truncate">{ticket.project}</span>
                    </span>
                  ) : null}
                  <Cause ticket={ticket} />
                </div>
                {ticket.block ? (
                  <p className="text-muted-foreground text-sm break-words">{blockSaid(ticket.block.help)}</p>
                ) : null}
              </div>
              {leaving?.why === "gone" ? (
                <p role="status" className="text-muted-foreground text-sm">
                  {t("This ticket left the series: it moved elsewhere.")}
                </p>
              ) : (
                <TicketDecision ticket={ticket} onDone={(solution) => decided(ticket.id, solution)} />
              )}
            </section>
          ) : null}
        </div>

        {finished || !ticket ? null : (
          <footer className="flex flex-wrap items-center gap-2 border-t px-4 py-2 sm:px-6">
            <Button variant="outline" size="sm" disabled={!previous || Boolean(leaving)} onClick={back}>
              <ArrowLeft />
              {t("Previous")}
            </Button>
            <Button variant="outline" size="sm" data-slot="series-skip" disabled={Boolean(leaving)} onClick={skip}>
              {t("Skip")}
              <ArrowRight />
            </Button>
            <Button asChild variant="ghost" size="sm">
              <a href={ticketHref(ticket.id)} target="_blank" rel="noreferrer">
                <ExternalLink />
                {t("Open the ticket")}
              </a>
            </Button>
            <p className="text-muted-foreground ms-auto hidden font-mono text-xs lg:block">
              {t("→ or J: skip · ← or K: previous · 1–9: a choice · Esc: close")}
            </p>
          </footer>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** The cause of a blocked ticket, with its family's mark. Nothing on one in review. */
function Cause({ ticket, compact = false }: { ticket?: Ticket; compact?: boolean }) {
  const block = ticket?.block
  if (!block) return null
  const Icon = FAMILY_ICON[block.family] ?? ServerCrash
  return (
    <span className="flex min-w-0 items-center gap-1.5" data-slot="series-cause" data-code={block.code}>
      <Icon className={cn("shrink-0", compact ? "size-3" : "size-4")} style={{ color: familyColor(block.family) }} />
      <span className={cn("truncate", compact && "sr-only")}>{blockSaid(block.label)}</span>
    </span>
  )
}

/** One ticket of the list at the top: its number, its project's icon, its short title, its cause. */
function Entry({
  ticket,
  number,
  outcome,
  current,
  gone,
  onClick,
}: {
  ticket?: Ticket
  number: number
  outcome?: Outcome
  current: boolean
  gone: boolean
  onClick: () => void
}) {
  const t = useT()
  const done = outcome === "done"
  const title = ticket ? titleOf(ticket) : ""
  return (
    <button
      type="button"
      disabled={done}
      aria-current={current ? "step" : undefined}
      data-series-entry={ticket?.id}
      data-outcome={outcome ?? (gone ? "gone" : "")}
      title={title}
      onClick={onClick}
      className={cn(
        "hover:bg-muted focus-visible:ring-ring/50 flex h-8 max-w-56 items-center gap-1.5 rounded-full border px-2.5 text-xs outline-none focus-visible:ring-2",
        current && "border-primary bg-primary/5",
        done && "text-muted-foreground line-through",
        outcome === "skipped" && "border-dashed"
      )}
    >
      {done ? (
        <CircleCheck className="text-tr-green size-3.5 shrink-0" aria-label={t("Decided")} />
      ) : (
        <span className="text-muted-foreground font-mono tabular-nums">{number}</span>
      )}
      {ticket?.project ? (
        <ProjectThumb
          project={{ name: ticket.project, icon: ticket.project_icon }}
          className="size-4 shrink-0 rounded-full border-0"
        />
      ) : null}
      <span className="min-w-0 truncate">{title}</span>
      <Cause ticket={ticket} compact />
    </button>
  )
}

/** The end of the series: how many were decided, how many passed over, and the way back to those. */
function Recap({
  column,
  done,
  skipped,
  onAgain,
  onClose,
}: {
  column: SeriesColumn
  done: number
  skipped: number
  onAgain: () => void
  onClose: () => void
}) {
  const t = useT()
  // Enter closes only here, at the end: the Close button holds the focus, so the key is the button's own.
  const close = React.useRef<HTMLButtonElement>(null)
  React.useEffect(() => close.current?.focus({ preventScroll: true }), [])
  const said =
    column === "blocked"
      ? counted(done, "{{count}} ticket unblocked", "{{count}} tickets unblocked")
      : counted(done, "{{count}} ticket decided", "{{count}} tickets decided")
  return (
    <section
      data-slot="series-recap"
      className="mx-auto flex max-w-xl flex-col items-center gap-4 px-4 py-16 text-center"
    >
      {/* The mascot arrives with a small rise; the robot itself stops moving under prefers-reduced-motion. */}
      <div className="animate-in fade-in zoom-in-95 slide-in-from-bottom-2 duration-500 motion-reduce:animate-none">
        <Robot state="success" size={128} />
      </div>
      <p role="status" className="text-xl font-semibold">
        {done || skipped
          ? [said, skipped ? counted(skipped, "{{count}} ticket skipped", "{{count}} tickets skipped") : ""]
              .filter(Boolean)
              .join(", ")
          : t(WORDS[column].empty)}
      </p>
      <div className="flex flex-wrap justify-center gap-2">
        {skipped ? (
          <Button onClick={onAgain} data-slot="series-again">
            {t("Review the skipped tickets")}
          </Button>
        ) : null}
        <Button ref={close} variant="outline" onClick={onClose} aria-keyshortcuts="Enter">
          {t("Close")} <kbd className="font-mono text-xs opacity-60">↵</kbd>
        </Button>
      </div>
    </section>
  )
}
