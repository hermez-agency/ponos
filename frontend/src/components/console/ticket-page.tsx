import * as React from "react"
import { useLocation, useRouter } from "@tanstack/react-router"
import {
  ArrowLeft,
  CircleAlert,
  CopyIcon,
  MessageCircleQuestion,
  RotateCw,
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
import { useFrench, useT } from "@/lib/i18n"
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
import { Markdown } from "./markdown"
import { Robot } from "./robot"
import { Pulse, TicketLive } from "./session-log"
import { TicketTabContext, WINDOW_TAB } from "./ticket-decision"
import { TicketDecision } from "./ticket-decision-panel"
import { TicketAudit } from "./ticket-audit"
import { TicketOn } from "./ticket-on"
import { TicketValidation } from "./ticket-validation"
import { TicketGoal } from "./ticket-goal"
import { TicketMission, TicketResult } from "./ticket-result"
import { TicketDelivery, TicketFacts, TicketStatus } from "./ticket-status"
import { useCloseWindow } from "./record-window"
import { Eyebrow } from "./frame"

/* What only an opened ticket says, in French: fetched with its page, see `ticket-french.ts`. */
const words = () => import("@/lib/ticket-french").then((module) => module.TICKET_FRENCH)

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
 * It opens on where the ticket stands and what it is waiting for, then what it
 * is and its pull request — the three blocks of `ticket-status.tsx`, the same
 * in the window over the board and on the page.
 *
 * Under them, the tabs: the brief;
 * the discussion; and what happened — the session and the journal. They were sections folded one under the
 * other for a while, all three on one page — and a running session, open at the
 * bottom of a long brief, was a page you scrolled to the end of every time it
 * moved. A tab is one thing at a time, the whole height for it, and the tab
 * list says which of the other two has something new — see `TicketTabs`.
 *
 * The way back to the board and the title are the header's, as on every page
 * of the console; the page drew its own under it, and said both twice. The
 * header is this file's too — see `TicketHead`.
 */

/** A page with room for a column beside the ticket's tabs. */
const WIDE = "(width >= 80rem)"

function useWide(): boolean {
  return React.useSyncExternalStore(
    (listener) => {
      const query = window.matchMedia(WIDE)
      query.addEventListener("change", listener)
      return () => query.removeEventListener("change", listener)
    },
    () => window.matchMedia(WIDE).matches
  )
}

export function TicketPage() {
  const context = useCurrentViewResourceContext()
  const inWindow = useCloseWindow()
  const page = context.data as TicketDetail | undefined
  const { ticket: open, openTicket } = useConsole()
  const t = useT()
  // Not drawn in English while its French is on the way: the lines it will fill meanwhile.
  const worded = useFrench(words)
  // The stream keeps the open ticket fresher than the page read once: the
  // column and the progress line are read from it where it is the same ticket.
  const ticket = page ? (open && open.id === page.id ? { ...page, ...open } : page) : null
  const brief = useBrief(page, ticket ? isFinished(ticket.column) : false)
  // Unblock or Decide, pressed on the ticket itself: a tab to switch to, under it.
  const [asked, setAsked] = React.useState<{ tab: DecisionTab | "live"; at: number }>()
  const goTo = React.useCallback((tab: DecisionTab) => setAsked({ tab, at: Date.now() }), [])
  // The tab on show, for the button above them to know it is already there.
  const [shown, setShown] = React.useState<string>()
  const tabs = React.useMemo(() => ({ goTo, shown }), [goTo, shown])

  // The page is the ticket's terminal too: opening it loads the discussion.
  React.useEffect(() => {
    if (page) openTicket(page)
  }, [page, openTicket])

  // On the ticket's own page, wide enough, the facts are a column beside the
  // tabs; in the window over a list, or narrower, a line above them.
  const rail = useWide() && inWindow === null

  // The board, in the layout it was left in: coming back onto the cards, when
  // the table is what you were reading the board in, is losing your place.
  const back = boardHref()

  return (
    <div>
      {ticket && worded ? (
        <>
          {/* Where it stands and what it waits for, with its gestures: first,
              and on every tab — what one opens a ticket to find out. Then what
              it is and what it cost, the pull request once, and the tabs. On a
              page wide enough, the facts are a column beside them. */}
          <TicketTabContext.Provider value={tabs}>
          <div
            data-slot="ticket-view"
            className={cn("min-w-0 gap-3", rail ? "grid items-start gap-x-8" : "flex flex-col")}
            // Said here rather than as two classes: the first load's stylesheet has no room to spare.
            style={rail ? { gridTemplateColumns: "minmax(0, 1fr) 18rem", gridTemplateRows: "auto 1fr" } : undefined}
          >
            <TicketStatus ticket={ticket} />
            <div className={cn(rail && "sticky top-4 col-start-2 row-span-2 row-start-1")}>
              <TicketFacts
                ticket={{ ...ticket, model_in_use: brief.model }}
                rail={rail}
                onSession={() => setAsked({ tab: "live", at: Date.now() })}
              />
            </div>
            <div className={cn("flex min-w-0 flex-col gap-3", rail && "col-start-1")}>
              <TicketDelivery ticket={ticket} />
              {/* Chosen once per ticket, not every time the column moves: a
                  tab that switched itself under the reader would lose them. */}
              <TicketTabs
                key={ticket.id}
                ticket={ticket}
                brief={brief}
                talking={open?.id === ticket.id}
                asked={asked}
                onTab={setShown}
              />
            </div>
          </div>
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
      ) : context.error && !ticket ? (
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
    validation?: string
    validation_inherited?: string
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
          validation: detail.validation,
          validation_inherited: detail.validation_inherited,
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
    validation: mine?.validation,
    validation_inherited: mine?.validation_inherited,
    model: mine?.model,
    previews: mine?.previews,
    problem: mine?.problem,
    again: () => {
      setBrief(undefined)
      setAttempt((count) => count + 1)
    },
  }
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
 * Activity is what happened, in one place: the session — its steps, live
 * while it runs — and the journal Ponos writes at the end of each, with who
 * did what on the ticket. They were two tabs, Live and Journal, the first one
 * empty of anything live on nine tickets out of ten; a running ticket reads
 * its session first, any other the journal first. The tab is still `live` in
 * an address, and `&tab=journal` opens it too.
 *
 * The status, the actions and the session's whereabouts stay above the tabs,
 * on every one of them — see `ticket-status.tsx`.
 * `talking` says the discussion held is this ticket's, and not still the last
 * one's.
 */
const TRIGGER =
  "data-[state=active]:border-b-primary -mb-px h-10 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-2.5 data-[state=active]:bg-transparent data-[state=active]:shadow-none sm:px-3"

const TABS = ["result", "mission", "discussion", "live", "decide"] as const
type Tab = (typeof TABS)[number]

const isTab = (value: string | null | undefined): value is Tab => TABS.includes(value as Tab)

/** A tab named in an address, as it is called now: Unblock was folded into the
 * discussion, the Brief became the mission, and the Journal is read under the
 * session, on Activity. */
const tabNamed = (value: string | null): Tab | undefined =>
  value === "unblock"
    ? "discussion"
    : value === "brief"
      ? "mission"
      : value === "journal"
        ? "live"
        : isTab(value)
          ? value
          : undefined

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
  asked?: { tab: DecisionTab | "live"; at: number }
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
      {/* A line of its own, the whole width: five tabs at most, which a phone
          holds without one cut at its edge. The ticket's gestures are above,
          with its status. */}
      <div className="border-b">
      {/* Scrolled sideways only: the pixel by which its tabs sit on the line
          under them made it a thing the wheel scrolled, one pixel, instead of the page. */}
      <TabsList className="scroll-thin -mb-px h-auto w-full justify-start gap-0.5 overflow-x-auto overflow-y-hidden rounded-none bg-transparent p-0 pb-px sm:gap-1">
        {/* What the ticket waits for, first. */}
        {deciding && action ? (
          <TabsTrigger
          value={deciding} data-slot="ticket-decide-tab"
          // On a phone the filled button above the tabs is the way in: the tab
          // shows once it is the one open, and the four others fit the width.
          className={cn(TRIGGER, "max-sm:data-[state=inactive]:hidden")}
        >
            {t(action)}
            <CircleAlert
              data-slot="ticket-decide-badge"
              className="text-tr-pink size-4"
              aria-label={t("your decision is awaited")}
            />
          </TabsTrigger>
        ) : null}
        {finished ? (
          <TabsTrigger
            value="result" data-slot="ticket-result-tab"
            className={TRIGGER}
          >
            {t("Result")}
          </TabsTrigger>
        ) : null}
        <TabsTrigger
          value="mission" data-slot="ticket-mission-tab"
          className={TRIGGER}
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
          className={TRIGGER}
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
          className={TRIGGER}
        >
          {t("Activity")}
          {running ? (
            <>
              <Pulse />
              <span className="sr-only">{t("writing now")}</span>
            </>
          ) : null}
        </TabsTrigger>
      </TabsList>
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
            <TicketValidation
              ticket={{
                ...ticket,
                validation: brief.validation ?? "",
                validation_inherited: brief.validation_inherited ?? "",
              }}
            />
            <TicketOn ticket={{ ...ticket, on: brief.on ?? "" }} />
          </div>
        )}
      </TabsContent>
      <TabsContent value="discussion">
        <React.Suspense fallback={null}>
          <TicketTalk ticket={ticket} onSession={() => show("live", true)} />
        </React.Suspense>
      </TabsContent>
      <TabsContent value="live">
        {/* What somebody opening it has come for, first: the session while it
            writes, what the sessions said of themselves once they are over. */}
        <div className={cn("flex gap-8", running ? "flex-col" : "flex-col-reverse")}>
          <section data-slot="ticket-session" className="flex flex-col gap-2">
            <Eyebrow>{t("Session")}</Eyebrow>
            <TicketLive ticket={ticket} />
          </section>
          <section data-slot="ticket-journal" className="flex flex-col gap-2">
            <Eyebrow>{t("Journal")}</Eyebrow>
            {brief.content === undefined ? (
              <BriefPending brief={brief} />
            ) : brief.journal?.trim() ? (
              <Markdown text={brief.journal} />
            ) : (
              <p className="text-muted-foreground text-sm">
                {t("Nothing yet: Ponos writes this part at the end of every session.")}
              </p>
            )}
            <TicketAudit ticket={ticket} />
          </section>
        </div>
      </TabsContent>
      {deciding ? (
        <TabsContent value={deciding}>
          <TicketDecision ticket={ticket} onDone={() => setSettled(true)} />
        </TabsContent>
      ) : null}
    </Tabs>
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
 * long one, a title that takes a second line before it gives up, and the goal
 * the ticket serves — what its window says in its own header.
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
      <div className="border-border flex flex-wrap items-end gap-x-6 gap-y-4 border-b pb-4">
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
            <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <p className="flex items-center gap-1">
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
              {/* The goal it serves, as under the title of its window. The pull
                  request and the session are in the page, each said once. */}
              <TicketGoal ticket={ticket} />
            </div>
          ) : null}
        </div>
      </div>
    </header>
  )
}
