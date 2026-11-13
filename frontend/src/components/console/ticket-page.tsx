import * as React from "react"
import { useLocation, useRouter } from "@tanstack/react-router"
import {
  ArrowLeft,
  ChevronRight,
  CircleAlert,
  CopyIcon,
  GitBranch,
  MessageCircleQuestion,
  RotateCw,
  Scale,
  Zap,
} from "lucide-react"
import { ActionList } from "react-data-form"
import { Link, useCurrentViewResourceContext } from "react-resource-view"

import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useConsole, useSteps } from "@/hooks/use-console"
import { ApiError, why } from "@/lib/api"
import { copy } from "@/lib/copy"
import { type DecisionTab, actionOf } from "@/lib/decision"
import { useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import { isFinished } from "@/lib/result"
import type { TicketDetail } from "@/lib/types"
import { useRoute } from "@/lib/router"
import { cn } from "@/lib/utils"
import { canAct } from "@/lib/role"
import {
  boardHref,
  holdTicket,
  readTicket,
  releaseTicket,
} from "@/resources/tickets"

import { EmptyState } from "./empty-state"
import { Eyebrow } from "./frame"
import { Markdown } from "./markdown"
import { PriorityBadge } from "./priority"
import { Robot } from "./robot"
import { Pulse, TicketLive } from "./session-log"
import { TicketTabContext, WINDOW_TAB } from "./ticket-decision"
import { TicketDecision } from "./ticket-decision-panel"
import { TicketAudit } from "./ticket-audit"
import { TicketOn } from "./ticket-on"
import { TicketEstimate } from "./ticket-estimate"
import { TicketMission, TicketResult } from "./ticket-result"
import { TicketTime } from "./ticket-time"
import {
  SEED,
  LABEL,
  NO_COMMIT,
  choiceWord,
  columnTitle,
  TicketActions,
  TicketBlock,
  TicketCi,
  TicketEarlier,
  TicketLinks,
  TicketSubtype,
  ago,
  capital,
  lasted,
  when,
} from "./ticket-bits"

// The Discussion tab is opened on demand: its chat stays out of the first load.
const TicketTalk = React.lazy(() => import("./ticket-talk").then((module) => ({ default: module.TicketTalk })))

/* One ticket, as a page.
 *
 * The `read` view of the tickets resource: what react-resource-view holds by
 * the time this draws is the card, as the board has it — so the page is drawn
 * at once — and the page under it, the brief, the report a run appended, the
 * notes between, is read here from `/api/tickets/<id>`, once per opening (see
 * `readTicket`). Opening this page is also what loads the ticket's discussion.
 *
 * It opens the way the board's cards do and then says more: the column and the
 * metadata, as one block of two columns — see `TicketSummary`.
 *
 * Under them, three tabs: the brief;
 * the discussion; and the session. They were sections folded one under the
 * other for a while, all three on one page — and a running session, open at the
 * bottom of a long brief, was a page you scrolled to the end of every time it
 * moved. A tab is one thing at a time, the whole height for it, and the tab
 * list says which of the other two has something new — see `TicketTabs`.
 *
 * The way back to the board and the title are the header's, as on every page
 * of the console; the page drew its own under it, and said both twice. The
 * header is this file's too — see `TicketHead`.
 */

export function TicketPage() {
  const context = useCurrentViewResourceContext()
  const page = context.data as TicketDetail | undefined
  const { ticket: open, openTicket } = useConsole()
  const t = useT()
  // The stream keeps the open ticket fresher than the page read once: the
  // column and the progress line are read from it where it is the same ticket.
  const ticket = page ? (open && open.id === page.id ? { ...page, ...open } : page) : null
  const brief = useBrief(page, ticket ? isFinished(ticket.column) : false)
  // Unblock or Decide, pressed on the ticket itself: a tab to switch to, under it.
  const [asked, setAsked] = React.useState<{ tab: DecisionTab; at: number }>()
  const goTo = React.useCallback((tab: DecisionTab) => setAsked({ tab, at: Date.now() }), [])
  // The tab on show, for the button above them to know it is already there.
  const [shown, setShown] = React.useState<string>()
  const tabs = React.useMemo(() => ({ goTo, shown }), [goTo, shown])

  // The page is the ticket's terminal too: opening it loads the discussion.
  React.useEffect(() => {
    if (page) openTicket(page)
  }, [page, openTicket])

  // The board, in the layout it was left in: coming back onto the cards, when
  // the table is what you were reading the board in, is losing your place.
  const back = boardHref()

  return (
    <div>
      {ticket ? (
        <>
          {/* On a phone, the Decide tab is under the checks and the summary,
              below the first screen: the page's first line points at it, in
              other words than the tab's. Not on the tab already. */}
          {ticket.column === "review" && shown !== "decide" && canAct() ? (
            <Button
              variant="outline"
              data-slot="ticket-decide-cue"
              className="text-tr-pink hover:text-tr-pink mb-3 w-full justify-start sm:hidden"
              onClick={() => goTo("decide")}
            >
              <Scale />
              {t("Your decision is awaited")}
              <ChevronRight className="ml-auto" />
            </Button>
          ) : null}

          {/* Why it stopped, as on its card: the gesture it proposes is
              among the actions below, the answer in the discussion. Not a
              session that committed nothing, which is no fault when there was
              nothing to change: the discussion says it in passing, on the
              session's line. */}
          {ticket.block && ticket.block.code !== NO_COMMIT ? (
            <div className="mb-3">
              <TicketBlock block={ticket.block} />
            </div>
          ) : null}

          {/* Where the pull request's checks stand, and each one. */}
          {ticket.ci ? (
            <div className="mb-3">
              <TicketCi ci={ticket.ci} detailed />
            </div>
          ) : null}

          {/* What the last pass said, that its card no longer draws: only while
              it waits in ready, the stream moving it on before the page is read again. */}
          {ticket.earlier && (ticket.column === "ready" || ticket.column === "draft") ? (
            <div className="mb-3">
              <TicketEarlier earlier={ticket.earlier} />
            </div>
          ) : null}

          {/* Priority, model and date are the grid's: the tags the card wears
              would say them a second time, one line above. */}
          {/* Chosen once per ticket, not every time the column moves: a
              tab that switched itself under the reader would lose them. */}
          <TicketTabContext.Provider value={tabs}>
            <TicketTabs
              key={ticket.id}
              ticket={ticket}
              brief={brief}
              talking={open?.id === ticket.id}
              asked={asked}
              onTab={setShown}
            />
          </TicketTabContext.Provider>
        </>
      ) : context.loadError instanceof ApiError && context.loadError.status === 404 ? (
        // Not there, or not shown to the integration: asking again changes
        // nothing, and what the board said is in the journal.
        <EmptyState
          robot="error"
          title={t("This ticket could not be found.")}
          action={
            <Link to={back} className={buttonVariants({ variant: "ghost", size: "sm" })}>
              <ArrowLeft />
              {t("Back to the board")}
            </Link>
          }
        >
          {t(
            "This ticket does not exist: it was deleted, or was never on this board."
          )}
        </EmptyState>
      ) : context.error ? (
        // Why, as the server said it, and the two ways on from here: a
        // board that did not answer often answers the second time.
        <EmptyState
          robot="error"
          title={t("This ticket could not be read.")}
          action={
            <>
              <Button variant="outline" size="sm" onClick={() => context.fetchData()}>
                <RotateCw />
                {t("Try again")}
              </Button>
              <Link to={back} className={buttonVariants({ variant: "ghost", size: "sm" })}>
                <ArrowLeft />
                {t("Back to the board")}
              </Link>
            </>
          }
        >
          {(context.loadError ? why(context.loadError) : "") || t("The server gave no reason.")}
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-2">
          <Robot state="thinking" size={56} className="mb-2" />
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="mt-2 h-20 w-full" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
        </div>
      )}
    </div>
  )
}

/* The brief of the ticket on screen, read once per opening.
 *
 * Read again when the board says the ticket was edited while the page is
 * open, and let go of when the page is left. `content` stays undefined until
 * it is read; `problem` is why it could not be. Read again, too, when its work
 * ends under the reader (`finished`): the result it wrote is what the Result
 * tab, come with it, shows. */
function useBrief(page: TicketDetail | undefined, finished: boolean) {
  const [brief, setBrief] = React.useState<{
    id: string
    content?: string
    mission?: string
    result?: string
    results?: TicketDetail["results"]
    journal?: string
    on?: string
    model?: TicketDetail["model_in_use"]
    previews?: TicketDetail["previews"]
    problem?: string
  }>()
  const [attempt, setAttempt] = React.useState(0)
  const id = page?.id
  const edited = page?.edited ?? ""

  React.useEffect(() => {
    holdTicket()
    return releaseTicket
  }, [])

  React.useEffect(() => {
    if (!id) return
    let live = true
    readTicket(id, edited).then(
      (detail) =>
        live &&
        setBrief({
          id,
          content: detail.content,
          mission: detail.mission,
          result: detail.result,
          results: detail.results,
          journal: detail.journal,
          on: detail.on,
          model: detail.model_in_use,
          previews: detail.previews,
        }),
      (error) => live && setBrief({ id, problem: why(error) })
    )
    return () => {
      live = false
    }
  }, [id, edited, attempt, finished])

  const mine = brief && brief.id === id ? brief : undefined
  return {
    content: mine?.content,
    mission: mine?.mission,
    result: mine?.result,
    results: mine?.results,
    journal: mine?.journal,
    on: mine?.on,
    model: mine?.model,
    previews: mine?.previews,
    problem: mine?.problem,
    again: () => {
      setBrief(undefined)
      setAttempt((count) => count + 1)
    },
  }
}

/* What the page says about the ticket, as one block of two columns.
 *
 * Ticket on the left — what kind of work it is, on what, how urgent, where it
 * stands — and Execution on the right: the pull request, what it cost, which
 * model, which session. It was a ruled grid with a cell, and a label, for each
 * of them, and the brief began a screen lower for it. What a ticket does not
 * have yet says nothing at all rather than "—", so one that never ran draws
 * the Ticket column alone, across the whole width.
 */
function TicketSummary({ ticket, onSession }: { ticket: TicketDetail; onSession: () => void }) {
  const t = useT()
  const { board } = useConsole()
  // Until the page's own read has said, a model written on the ticket is the one it has.
  const used =
    ticket.model_in_use ??
    (ticket.model ? { label: ticket.model_label ?? ticket.model, full: ticket.model, default: false } : undefined)
  const created = ago(ticket.created)
  const pull = ticket.pull_request.match(/\/pull\/(\d+)/)?.[1]
  // The board's word for the column is its own, often English ("Progress"):
  // the console's own, in its language, where it has one.
  const status = LABEL[ticket.column]
    ? t(LABEL[ticket.column])
    : capital(columnTitle(ticket.column, board.columns.find((item) => item.key === ticket.column)?.name))
  const cost = typeof ticket.cost === "number" && ticket.cost ? money(ticket.cost) : ""
  const took = typeof ticket.duration === "number" && ticket.duration ? lasted(ticket.duration) : ""
  const executed = Boolean(
    ticket.pull_request || cost || used?.label || ticket.session || ticket.worktime || took || ticket.runner
  )
  const sep = <span className="text-muted-foreground/60">·</span>
  const line = "flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1"
  return (
    <div
      data-slot="ticket-summary"
      className={cn(
        "bg-card mt-4 grid rounded-xl border text-sm",
        executed && "md:grid-cols-2 md:[&>*+*]:border-l [&>*+*]:border-t md:[&>*+*]:border-t-0"
      )}
    >
      <div className="flex min-w-0 flex-col gap-1.5 px-3.5 py-3">
        <Eyebrow>{t("Ticket")}</Eyebrow>
        <div className={line}>
          <span className="font-semibold">{ticket.project || t("no project — a document")}</span>
          {ticket.type ? (
            <>
              {sep}
              <span>{choiceWord(ticket.type)}</span>
            </>
          ) : null}
          {ticket.subtype ? <TicketSubtype subtype={ticket.subtype} /> : null}
          {typeof ticket.priority === "number" ? (
            <>
              {sep}
              <PriorityBadge score={ticket.priority} />
            </>
          ) : null}
        </div>
        <div className={cn(line, "text-muted-foreground")}>
          <span className="text-foreground inline-flex items-center gap-1.5">
            <span className={cn("size-1.5 shrink-0 rounded-full", SEED[ticket.column] ?? "bg-muted-foreground")} />
            {status}
          </span>
          {created ? (
            <>
              {sep}
              <span>
                {t("created")} {created}
              </span>
            </>
          ) : null}
          {ticket.scheduled ? (
            <>
              {sep}
              <span>
                {t("scheduled")} {when(ticket.scheduled)}
              </span>
            </>
          ) : null}
          {ticket.estimate ? (
            <>
              {sep}
              <TicketEstimate estimate={ticket.estimate} />
            </>
          ) : null}
        </div>
      </div>
      {executed ? (
        <div className="flex min-w-0 flex-col gap-1.5 px-3.5 py-3">
          <Eyebrow>{t("Execution")}</Eyebrow>
          <div className={line}>
            {ticket.pull_request ? (
              <a
                href={ticket.pull_request}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1 font-semibold underline-offset-2 hover:underline"
              >
                <GitBranch className="size-3.5" />
                {pull ? `PR #${pull}` : t("pull request")}
              </a>
            ) : null}
            {cost ? <span>{cost}</span> : null}
            {/* The column empty is not "no model": it is the one the session
                announced, or the runner's, or Claude Code's own. The server
                says which, as provider/model; the full identifier is the tooltip. */}
            {used?.label ? (
              <span title={used.full}>
                {used.label.replace(/^claude\//, "")}
                {used.default ? (
                  <span className="text-muted-foreground font-normal"> · {t("default")}</span>
                ) : null}
              </span>
            ) : null}
            {/* The runs' time with the clock stopped while it waited — not the
                time since it was made, which holds the queue and the review. */}
            {ticket.worktime ? (
              <span className="inline-flex min-w-0 items-center gap-1">
                <span className="text-muted-foreground">{t("worked")}</span>
                <TicketTime time={ticket.worktime} />
              </span>
            ) : null}
            {/* The last session alone: the column the runner writes after each run. */}
            {took ? <span className="text-muted-foreground">{t("last session {{time}}", { time: took })}</span> : null}
          </div>
          {ticket.session || ticket.runner ? (
            // A separator leads the item it precedes and sits in a margin the
            // line clips: where the item starts a row, it is out of sight
            // rather than left at the end of the row above.
            <div className="overflow-hidden">
              <div className={cn(line, "text-muted-foreground -ml-4 gap-x-0")}>
                {ticket.session ? (
                  <span className="inline-flex items-center gap-1.5 pl-4">
                    {t("session")}
                    <button
                      type="button"
                      onClick={onSession}
                      className="text-foreground cursor-pointer font-mono text-xs underline-offset-2 hover:underline"
                      title={ticket.session}
                    >
                      {ticket.session.slice(0, 8)}
                    </button>
                  </span>
                ) : null}
                {/* Which machine has it, for the days two of them share a board
                    — and the other half of the answer to "why has nothing
                    happened": nobody claimed it. */}
                {ticket.runner ? (
                  <span className="relative pl-4 before:absolute before:left-1.5 before:text-muted-foreground/60 before:content-['·']">
                    {t("taken by")}{" "}
                    <span className="font-mono text-xs" title={ticket.runner}>
                      {ticket.runner}
                    </span>
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

/* The tabs of a ticket: its brief, its discussion, its session — and, on one
 * in review, what you decide (see `ticket-decision.tsx`).
 *
 * Which one a ticket opens on says what it is waiting for. A running ticket
 * opens on its session, because that is what somebody opening it then has
 * come to watch; a ticket waiting on you, on its discussion, because the
 * question in it is the one thing on the page you can do something about; any
 * other, on its brief. The discussion arrives after the page — it is a second
 * question to the board — so a ticket whose question is still unanswered is
 * known to be waiting only once it has: the tab follows it then, from the
 * brief, unless the reader has already picked one. It never moves by itself
 * after that: a tab that switched under the reader would lose them, and the
 * end of a run, or an answer sent from the discussion, is exactly when it
 * would.
 *
 * The tab picked is written in the address (`&tab=live`), so a reload, the
 * way back, or a link pasted elsewhere comes back to it — on the ticket's own
 * page only: the window over the board has the board's address, and keeps its
 * tab to itself, opened on the discussion, or on Decide, by the card that
 * asked for it.
 *
 * A blocked ticket has no tab of its own: its question is answered in the
 * discussion, which it opens on, scrolled to the question — and an address
 * written when it had one, `&tab=unblock`, opens there too. The Decide tab is
 * there only while the ticket is in review. Once a choice is sent it goes,
 * with nothing left to decide, and the ticket shows its discussion — its
 * session, when one starts: that is what comes next.
 *
 * The mission is always there; the result only once the work is over — in
 * review, validated or done —, first, and what such a ticket opens on: it is
 * what one comes back to it for. Before that there is nothing to read in it
 * but « nothing yet », and an address naming it (`&tab=result`, a link kept
 * from when the ticket was in review) opens on the mission instead. It comes
 * by itself, with the stream, the moment the ticket goes into review — without
 * taking the reader off the tab they are reading.
 *
 * The status, the actions and the session's whereabouts stay above the tabs,
 * on every one of them, the block of facts first.
 * `talking` says the discussion held is this ticket's, and not still the last
 * one's.
 */
const TABS = ["result", "mission", "discussion", "live", "decide", "journal"] as const
type Tab = (typeof TABS)[number]

const isTab = (value: string | null | undefined): value is Tab => TABS.includes(value as Tab)

/** A tab named in an address, as it is called now: Unblock was folded into the
 * discussion, and the Brief became the mission. */
const tabNamed = (value: string | null): Tab | undefined =>
  value === "unblock" ? "discussion" : value === "brief" ? "mission" : isTab(value) ? value : undefined

/** The query string with its tab said again, under `key` — the rest of it left exactly as written. */
function withTab(searchStr: string, tab: Tab, key: string): string {
  const rest = searchStr
    .replace(/^\?/, "")
    .split("&")
    .filter((part) => part && !part.startsWith(`${key}=`))
  return `?${[...rest, `${key}=${tab}`].join("&")}`
}

/** The tab named in the address, and how to name another — when the address is
 * this ticket's page, or the window it is opened in over a list. */
function useAddressedTab(id: string): [Tab | undefined, (tab: Tab) => void] {
  const { pathname, searchStr } = useLocation()
  const router = useRouter()
  const { params } = useRoute()
  const onPage = params.resourceAction === ActionList.read && String(params.id ?? "") === id
  const opened = params.childViewResource
  const inWindow = opened?.resourceAction === ActionList.read && String(opened.id ?? "") === id
  const key = onPage ? "tab" : WINDOW_TAB
  const mine = onPage || inWindow
  const named = tabNamed(new URLSearchParams(searchStr).get(key))
  const write = React.useCallback(
    (tab: Tab) => {
      if (mine) router.history.replace(pathname + withTab(searchStr, tab, key))
    },
    [mine, router, pathname, searchStr, key]
  )
  return [mine ? named : undefined, write]
}

function TicketTabs({
  ticket,
  brief,
  talking,
  asked,
  onTab,
}: {
  ticket: TicketDetail
  brief: ReturnType<typeof useBrief>
  talking: boolean
  /** A tab the ticket's own Unblock or Decide button asked for — the latest press. */
  asked?: { tab: DecisionTab; at: number }
  /** Told which tab is on show. */
  onTab: (tab: string) => void
}) {
  const { talk, talkWaiting } = useConsole()
  const { sessions } = useSteps()
  const t = useT()
  const session = sessions.find((candidate) => candidate.source === ticket.short)
  const running = ticket.column === "running" || Boolean(session)
  const waiting = ticket.column === "blocked" || (talking && talkWaiting)
  // Sent: the tab goes at once, before the stream has said the ticket moved.
  const [settled, setSettled] = React.useState(false)
  React.useEffect(() => setSettled(false), [ticket.column])
  // A reader decides nothing: no tab offers it.
  const deciding = settled || ticket.column !== "review" || !canAct() ? null : "decide"
  const action = actionOf(ticket.column)
  const finished = isFinished(ticket.column)
  const [addressed, address] = useAddressedTab(ticket.id)
  const [tab, setTab] = React.useState<Tab>(
    () => addressed ?? (running ? "live" : waiting ? "discussion" : finished ? "result" : "mission")
  )
  const picked = React.useRef(Boolean(addressed))
  // Left by itself when the decision was sent: still free to follow a session that starts.
  const left = React.useRef(false)
  const show = React.useCallback(
    (next: Tab, chosen: boolean) => {
      if (chosen) picked.current = true
      left.current = !chosen
      setTab(next)
      address(next)
    },
    [address]
  )
  React.useEffect(() => {
    if (waiting && !picked.current) setTab((was) => (was === "mission" || was === "result" ? "discussion" : was))
  }, [waiting])
  // The way back, or forward, to the same ticket on another tab.
  React.useEffect(() => {
    if (addressed) setTab(addressed)
  }, [addressed])
  // No result before the work is over — named in the address, or sent back
  // to work under the reader: the mission, and the address says so.
  const early = tab === "result" && !finished
  const current: Tab = early ? "mission" : tab
  React.useEffect(() => {
    if (!early) return
    setTab("mission")
    address("mission")
  }, [early, address])
  React.useEffect(() => onTab(current), [current, onTab])
  // The Unblock or Decide button above the tabs, pressed.
  React.useEffect(() => {
    if (asked) show(asked.tab, true)
  }, [asked, show])
  // Nothing left to decide — sent from here, or moved elsewhere: the tab goes,
  // and the ticket shows what comes next.
  const gone = tab === "decide" && tab !== deciding
  React.useEffect(() => {
    if (gone) show(running ? "live" : "discussion", false)
  }, [gone, running, show])
  React.useEffect(() => {
    if (running && left.current && tab === "discussion") show("live", false)
  }, [running, tab, show])
  // What was said, not a line saying the discussion could not be read.
  const count = talking ? talk.filter((message) => message.role !== "error").length : 0

  return (
    <>
    <Tabs
      value={current}
      onValueChange={(value) => {
        if (isTab(value)) show(value, true)
      }}
      className="gap-4"
    >
      {/* The whole width on a phone, three equal thirds: a tab list sized to
          its words leaves the third one to be scrolled to. */}
      {/* The ticket's gestures on the tabs' line, at its end: a row of their
          own, for a "…" that most tickets hold alone, was a line lost. */}
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b">
      <TabsList className="scroll-thin h-auto w-full justify-start gap-1 overflow-x-auto rounded-none bg-transparent p-0 sm:w-fit">
        {finished ? (
          <TabsTrigger
            value="result" data-slot="ticket-result-tab"
            className="data-[state=active]:border-b-primary -mb-px h-9 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3 data-[state=active]:bg-transparent data-[state=active]:shadow-none"
          >
            {t("Result")}
          </TabsTrigger>
        ) : null}
        <TabsTrigger
          value="mission" data-slot="ticket-mission-tab"
          className="data-[state=active]:border-b-primary -mb-px h-9 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3 data-[state=active]:bg-transparent data-[state=active]:shadow-none"
        >
          {t("Mission")}
          {brief.on?.trim() ? (
            <Zap
              data-slot="ticket-on-badge"
              className="text-tr-amber size-3.5"
              aria-label={t("has an automation prompt")}
            />
          ) : null}
        </TabsTrigger>
        <TabsTrigger
          value="discussion" data-slot="ticket-talk-tab"
          className="data-[state=active]:border-b-primary -mb-px h-9 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3 data-[state=active]:bg-transparent data-[state=active]:shadow-none"
        >
          {t("Discussion")}
          {waiting ? (
            <MessageCircleQuestion
              data-slot="ticket-waiting-badge"
              className="text-tr-amber size-4"
              aria-label={t("a question is waiting for you")}
            />
          ) : null}
          {count ? (
            <span className="bg-muted-foreground/15 text-muted-foreground rounded-full px-1.5 text-[0.7rem] tabular-nums">
              {count}
            </span>
          ) : null}
        </TabsTrigger>
        <TabsTrigger
          value="live" data-slot="ticket-live-tab"
          className="data-[state=active]:border-b-primary -mb-px h-9 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3 data-[state=active]:bg-transparent data-[state=active]:shadow-none"
        >
          {t("Live")}
          {running ? (
            <>
              <Pulse />
              <span className="sr-only">{t("writing now")}</span>
            </>
          ) : null}
        </TabsTrigger>
        {deciding && action ? (
          <TabsTrigger
          value={deciding} data-slot="ticket-decide-tab"
          className="data-[state=active]:border-b-primary -mb-px h-9 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3 data-[state=active]:bg-transparent data-[state=active]:shadow-none"
        >
            {t(action)}
            <CircleAlert
              data-slot="ticket-decide-badge"
              className="text-tr-pink size-4"
              aria-label={t("your decision is awaited")}
            />
          </TabsTrigger>
        ) : null}
        <TabsTrigger
          value="journal" data-slot="ticket-journal-tab"
          className="data-[state=active]:border-b-primary -mb-px h-9 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3 data-[state=active]:bg-transparent data-[state=active]:shadow-none"
        >
          {t("Journal")}
        </TabsTrigger>
      </TabsList>
      <TicketActions ticket={ticket} className="ml-auto pb-1" />
      </div>

      {finished ? (
        <TabsContent value="result">
          {brief.content === undefined ? (
            <BriefPending brief={brief} />
          ) : (
            <TicketResult
              ticket={ticket}
              result={brief.result ?? ""}
              versions={brief.results ?? []}
              journal={brief.journal ?? ""}
              previews={brief.previews}
              onSaved={brief.again}
            />
          )}
        </TabsContent>
      ) : null}
      <TabsContent value="mission">
        {brief.content === undefined ? (
          <BriefPending brief={brief} />
        ) : (
          <div className="flex flex-col gap-6">
            <TicketMission mission={brief.mission ?? brief.content} />
            <TicketOn ticket={{ ...ticket, on: brief.on ?? "" }} />
          </div>
        )}
      </TabsContent>
      <TabsContent value="journal">
        <section data-slot="ticket-journal" className="flex flex-col gap-2">
          {brief.content === undefined ? (
            <BriefPending brief={brief} />
          ) : brief.journal?.trim() ? (
            <Markdown text={brief.journal} />
          ) : (
            <p className="text-muted-foreground text-sm">
              {t("Nothing yet: Ponos writes this part at the end of every session.")}
            </p>
          )}
        </section>
        <TicketAudit ticket={ticket} />
      </TabsContent>
      <TabsContent value="discussion">
        <React.Suspense fallback={null}>
          <TicketTalk ticket={ticket} onSession={() => show("live", true)} />
        </React.Suspense>
      </TabsContent>
      <TabsContent value="live">
        <TicketLive ticket={ticket} />
      </TabsContent>
      {deciding ? (
        <TabsContent value={deciding}>
          <TicketDecision ticket={ticket} onDone={() => setSettled(true)} />
        </TabsContent>
      ) : null}
    </Tabs>
    {/* What it is, what it cost, which model: under what it delivered, not above it. */}
    <TicketSummary
      ticket={{ ...ticket, model_in_use: brief.model }}
      onSession={() => show("live", true)}
    />
    </>
  )
}

/* The brief not read yet: why, and the way to ask again — or the lines it will fill. */
function BriefPending({ brief }: { brief: ReturnType<typeof useBrief> }) {
  const t = useT()
  return brief.problem !== undefined ? (
    <EmptyState
      robot="error"
      title={t("This ticket could not be read.")}
      action={
        <Button variant="outline" size="sm" onClick={brief.again}>
          <RotateCw />
          {t("Try again")}
        </Button>
      }
    >
      {brief.problem || t("The server gave no reason.")}
    </EmptyState>
  ) : (
    <div className="flex flex-col gap-2" aria-busy="true">
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-5/6" />
      <Skeleton className="h-3 w-2/3" />
    </div>
  )
}

/* The layout's header, written here rather than told to it.
 *
 * The package's own says the record's identity under the title — for a ticket,
 * the whole id, `#3eb451680af481ab9ab5dca1a49e1a7b`, where the board, the
 * palette and the tab all call it `#a49e1a7b` — and cuts the title with "…"
 * and nothing to read the rest in. It lets a view replace the title and the
 * actions, but the line under them only with the whole header: so this is the
 * whole header, the same shapes, the short id with a button that copies the
 * long one, and a title that takes a second line before it gives up.
 */
export function TicketHead() {
  const page = useCurrentViewResourceContext().data as TicketDetail | undefined
  const { ticket: open } = useConsole()
  const t = useT()
  // The pull request is opened while the page is on screen: the stream has it first.
  const ticket = page ? (open && open.id === page.id ? { ...page, ...open } : page) : null
  const copyIt = () => {
    if (!ticket) return
    void copy(ticket.id, ticket.id)
  }
  return (
    <header data-slot="admin-header" className="w-full">
      <div className="border-border flex flex-wrap items-end gap-x-6 gap-y-4 border-b pb-5">
        <div className="min-w-0 flex-1">
          <Link
            to={boardHref()}
            className="text-muted-foreground hover:text-foreground mb-1.5 inline-flex items-center gap-1 text-sm transition-colors"
          >
            <ArrowLeft className="size-4" />
            {t("Dashboard")}
          </Link>
          <h2
            className="line-clamp-2 text-2xl font-semibold tracking-tight break-words"
            title={ticket?.title}
          >
            {ticket ? ticket.title : t("Ticket")}
          </h2>
          {ticket ? (
            <p className="text-muted-foreground mt-1 flex items-center gap-1 text-sm">
              {t("Ticket")} · <span className="font-mono">#{ticket.short}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                onClick={copyIt}
                title={t("Copy the full id")}
                aria-label={t("Copy the full id")}
              >
                <CopyIcon />
              </Button>
            </p>
          ) : null}
        </div>
        {/* The pull request, the session: where else the ticket is. */}
        {ticket ? (
          <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 md:w-auto">
            <TicketLinks ticket={ticket} />
          </div>
        ) : null}
      </div>
    </header>
  )
}
