import * as React from "react"
import { Link } from "@tanstack/react-router"
import {
  CircleCheck,
  CircleX,
  ChevronRight,
  ExternalLink,
  LoaderCircle,
  GitMerge,
  KeyRound,
  type LucideIcon,
  MessageCircleQuestion,
  MoreHorizontal,
  ServerCrash,
  SquareTerminal,
} from "lucide-react"

import { ProjectThumb } from "@/components/console/project-picture"
import { projectHref } from "@/resources/projects"
import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { PriorityBadge } from "@/components/console/priority"
import { DecideButton } from "@/components/console/ticket-decision"
import { CardTime } from "@/components/console/ticket-time"
import { moveWithToast as move } from "@/hooks/use-console"
import { currentBoard, titleOf, useBoard } from "@/lib/board-store"
import { actionsOf } from "@/lib/decision"
import { currentLanguage, t, useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import type { Block, BlockFamily, Ci, CiState, Subtype, Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"

/* What a ticket wears wherever it is drawn — on its card, at the top of its
 * page: the column it is in, the tags, the links out, and the gestures it
 * offers where it stands. */

/* What a column is called where the board has not named it itself. English
 * here, and translated where it is drawn: the board's own words come from
 * Notion and are repeated as they are. */
export const LABEL: Record<string, string> = {
  draft: "Draft",
  ready: "Ready",
  running: "In progress",
  blocked: "Blocked",
  paused: "Paused",
  review: "In review",
  validated: "Validated",
  failed: "Failed",
  done: "Done",
  cancelled: "Cancelled",
}

/** A column's name as the board heads it: the board's word, with a capital — Notion's may have none. */
export const capital = (name: string): string => name.charAt(0).toUpperCase() + name.slice(1)

/* The heading over a column: the console's word for it, in its language,
 * wherever the runner has one — which is every column it acts on.
 *
 * It was the board's own word, repeated as it is: but that word is a status
 * option, and an option is spelt for the board's sake — "progress", "review",
 * "Ready" — so a French console headed its columns in English beside its
 * "Brouillon", while the ticket's page said "En revue" for the same column.
 * The board's word is kept for a column the runner has no word for. */
export function columnTitle(key: string, name?: string): string {
  const ours = LABEL[key]
  if (ours) return t(ours)
  return name || key
}

/* The words a ticket's type is written in on the board: the runner's own
 * ("Writing", "Publication"), which it acts on and which stay its values — but
 * said, wherever the console draws them, in its language. A word the
 * dictionary does not know (a type a board added) is drawn as it is. */
export const choiceWord = (value: string): string => (value ? t(value) : value)

/** The colour of a column, as text. */
export const TONE: Record<string, string> = {
  ready: "text-tr-green",
  running: "text-primary",
  blocked: "text-tr-amber",
  review: "text-tr-violet",
  validated: "text-tr-pink",
  failed: "text-tr-red",
  cancelled: "text-muted-foreground line-through",
}

/** The same colour again, as a dot — over a column, beside a status. Done
 * has none, and is the plain grey dot; cancelled is that grey hollowed out,
 * the one end apart from the other. */
export const SEED: Record<string, string> = {
  ready: "bg-tr-green",
  running: "bg-primary",
  blocked: "bg-tr-amber",
  review: "bg-tr-violet",
  validated: "bg-tr-pink",
  failed: "bg-tr-red",
  cancelled: "ring-muted-foreground bg-transparent ring-[1.5px] ring-inset",
}

/* How long ago, in the two words a card has room for. Cards are read in a
 * glance and a glance does not parse a timestamp: "12 min ago" says the one
 * thing you wanted from it, and the exact instant is on the ticket's page. */
export function ago(at: string): string {
  const then = new Date(at).getTime()
  if (Number.isNaN(then)) return ""
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (seconds < 90) return t("just now")
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return t("{{count}} min ago", { count: String(minutes) })
  const hours = Math.round(minutes / 60)
  if (hours < 24) return t("{{count}}h ago", { count: String(hours) })
  const days = Math.round(hours / 24)
  return days < 30
    ? t("{{count}}d ago", { count: String(days) })
    : t("{{count}}mo ago", { count: String(Math.round(days / 30)) })
}

/* The moment a ticket is due, in the words the console is set to.
 *
 * `/api/board` writes it as the board holds it — `2026-09-19T00:00+02:00` — and
 * an ISO string beside "il y a 7 h" reads like something leaked out of a
 * database. A start gate written as a day is a day: Notion's date column has no
 * time in it, and the midnight the API adds is not something anybody chose. */
export function when(at: string): string {
  if (!at) return ""
  const date = new Date(at)
  if (Number.isNaN(date.getTime())) return at
  const midnight = date.getHours() === 0 && date.getMinutes() === 0
  return date.toLocaleString(currentLanguage(), {
    dateStyle: "medium",
    ...(midnight ? {} : { timeStyle: "short" }),
  })
}

/** How long a run took, from the minutes the board counts them in. */
export function lasted(minutes: number): string {
  if (minutes < 60) return t("{{count}} min", { count: String(Math.round(minutes)) })
  const hours = Math.floor(minutes / 60)
  const rest = Math.round(minutes - hours * 60)
  const said = t("{{count}} h", { count: String(hours) })
  return rest ? `${said} ${String(rest).padStart(2, "0")}` : said
}

/* Whether a page's address is one a browser may be sent to.
 *
 * A Markdown board's page is a file on this disk, and a `file://` link offered
 * by a page served over HTTP is one Chrome declines to follow without saying
 * anything — a link that does nothing reads as a broken console. */
export const reachable = (address: string): boolean => /^https?:\/\//.test(address)

/* Why a ready card is still in its column. A ready column that stays full
 * with nothing to say why reads as a broken runner — so every ready card says
 * what it is waiting for, in the server's words (`held` in `web/board.py`). */
export function TicketHeld({ ticket }: { ticket: Ticket }) {
  const t = useT()
  const held = ticket.column === "ready" ? ticket.held : undefined
  // Not said on the card: a project that holds its places says so on every card
  // of its own, and the line repeated over a column is noise. The runner still
  // writes it in its own journal (see `board.py`).
  if (!held || held.reason === "project") return null
  const said: Record<string, string> = {
    date: t("waiting: scheduled for {{at}}", { at: when(held.detail) }),
    credits: t("waiting: out of credit until {{at}}", { at: held.detail }),
    reserve: t("waiting: credit reserve reached until {{at}}", { at: held.detail }),
    budget: t("waiting: today's spending limit reached until {{at}}", { at: held.detail }),
    running: t("waiting: a session is still on it — run again once it ends"),
    places: t("waiting: all {{count}} places taken — starts at the next free one", {
      count: held.detail,
    }),
    limit: t("waiting: --limit reached for this pass"),
    pass: t("waiting: the next reading of the board by the pass under way"),
    next: t("waiting: the next run of the timer"),
    timer: t("waiting: the timer is off — nothing takes it"),
  }
  return (
    <div className="flex flex-wrap gap-1.5" data-slot="ticket-held">
      <Chip
        className={cn(
          "whitespace-normal",
          ["timer", "credits", "budget"].includes(held.reason) && "border-tr-amber text-tr-amber"
        )}
      >
        {said[held.reason] ?? t("waiting")}
      </Chip>
    </div>
  )
}

/* Why a stopped ticket stopped, as `blocks.py` catalogues it: one icon per
 * family, so that a column of blocked cards sorts itself at a glance — the
 * merges, the sessions that came back empty, Ponos's own machinery, the
 * questions, the accesses only you can give. */
export const FAMILY_ICON: Record<BlockFamily, LucideIcon> = {
  merge: GitMerge,
  session: SquareTerminal,
  infrastructure: ServerCrash,
  question: MessageCircleQuestion,
  access: KeyRound,
}

/** The colour of a family — on its icon, never on the words beside it. */
export const familyColor = (family: BlockFamily): string => `var(--family-${family})`

/** A colour, softened — a chart's bars read as one shape sooner than as a wall of ink. */
export const fade = (color: string, opacity = 75): string => `color-mix(in oklab, ${color} ${opacity}%, transparent)`

/** A cause's words in the language the console is read in. Written by the server in both. */
export function blockSaid(words: { en: string; fr: string }): string {
  return (currentLanguage() === "fr" ? words.fr : words.en) || words.en
}

/* The cause on a stopped card: a badge with its label, and the line of help
 * under it. The gesture it proposes is with the others, in `TicketActions`.
 * A blocked card keeps neither: the label and the help move to the tooltip of
 * its Unblock button, whose icon is the cause's — the button says what to do. */
/** The cause of a session that committed nothing — see `blocks.py`: no fault when there was nothing to change. */
export const NO_COMMIT = "session.no-commit"

export function TicketBlock({ block }: { block?: Block | null }) {
  if (!block) return null
  const Icon = FAMILY_ICON[block.family] ?? ServerCrash
  return (
    <div className="flex flex-col gap-1" data-slot="ticket-block" data-code={block.code}>
      <div className="flex flex-wrap gap-1.5">
        <Chip className="text-foreground font-medium">
          <Icon className="size-3" style={{ color: familyColor(block.family) }} />
          <span title={block.code}>{blockSaid(block.label)}</span>
        </Chip>
      </div>
      <p className="text-muted-foreground text-xs leading-relaxed break-words">{blockSaid(block.help)}</p>
    </div>
  )
}

const CI_STATE: Record<CiState, { icon: LucideIcon; color: string; spin?: boolean }> = {
  pending: { icon: LoaderCircle, color: "text-tr-amber", spin: true },
  passed: { icon: CircleCheck, color: "text-tr-green" },
  failed: { icon: CircleX, color: "text-tr-red" },
}

const CI_WORDS = (): Record<CiState, string> => ({
  pending: t("CI running"),
  passed: t("CI passed"),
  failed: t("CI failed"),
})

const BUCKET: Record<string, CiState> = {
  pass: "passed",
  skipping: "passed",
  fail: "failed",
  cancel: "failed",
}

const CI_OPEN_KEY = "ponos-ci-open"

/* Whether the list of checks is unfolded: one choice for every ticket, kept
 * with the browser like the theme. Until it has been made, the list is folded —
 * unless the checks failed, when the list is what you came for. */
function useCiOpen(failed: boolean) {
  const [chosen, setChosen] = React.useState<boolean | null>(() => {
    try {
      const stored = localStorage.getItem(CI_OPEN_KEY)
      return stored === null ? null : stored === "open"
    } catch {
      return null
    }
  })
  const choose = React.useCallback((next: boolean) => {
    setChosen(next)
    try {
      localStorage.setItem(CI_OPEN_KEY, next ? "open" : "folded")
    } catch {
      // Storage off: the choice lasts as long as the tab.
    }
  }, [])
  return [chosen ?? failed, choose] as const
}

/* Where a review's checks stand, as an icon and a colour: on the card it is
 * the whole of it, and the detail adds each check and the link to GitHub's
 * page. Nothing for a pull request without checks — `ci` is null then. */
export function TicketCi({ ci, detailed = false }: { ci?: Ci | null; detailed?: boolean }) {
  useT()
  const [open, choose] = useCiOpen(ci?.state === "failed")
  if (!ci) return null
  const { icon: Icon, color, spin } = CI_STATE[ci.state]
  const badge = (
    <Chip className="text-foreground font-medium">
      <Icon className={cn("size-3", color, spin && "animate-spin")} />
      <span>{CI_WORDS()[ci.state]}</span>
    </Chip>
  )
  if (!detailed) {
    return (
      <div className="flex" data-slot="ticket-ci" data-state={ci.state}>
        {badge}
      </div>
    )
  }
  const stateOf = (bucket: string): CiState => BUCKET[bucket] ?? "pending"
  const failing = ci.checks.filter((check) => stateOf(check.bucket) === "failed")
  const passing = ci.checks.filter((check) => stateOf(check.bucket) === "passed").length
  return (
    <Collapsible
      open={open}
      onOpenChange={choose}
      className="flex flex-col gap-1.5"
      data-slot="ticket-ci"
      data-state={ci.state}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <CollapsibleTrigger className="focus-visible:ring-ring/50 flex min-w-0 items-center gap-1.5 rounded-md outline-none focus-visible:ring-2">
          <ChevronRight
            className={cn("text-muted-foreground size-3.5 shrink-0 transition-transform", open && "rotate-90")}
            aria-hidden
          />
          {badge}
          {ci.checks.length ? (
            <span className="text-muted-foreground font-mono text-xs tabular-nums">
              {passing}/{ci.checks.length}
            </span>
          ) : null}
          {!open && failing.length ? (
            <span className="text-tr-red min-w-0 truncate text-xs" data-slot="ticket-ci-failing">
              {failing.map((check) => check.name).join(", ")}
            </span>
          ) : null}
        </CollapsibleTrigger>
        <a
          href={ci.link}
          target="_blank"
          rel="noreferrer noopener"
          className="text-muted-foreground inline-flex items-center gap-1 text-xs hover:underline"
        >
          {t("Checks on GitHub")}
          <ExternalLink className="size-3" />
        </a>
      </div>
      <CollapsibleContent>
        <ul className="flex flex-col gap-0.5 text-xs">
          {ci.checks.map((check) => {
            const state = stateOf(check.bucket)
            const { icon: CheckIcon, color, spin } = CI_STATE[state]
            const name = <span className="min-w-0 truncate">{check.name}</span>
            return (
              <li key={`${check.name}-${check.link}`} className="flex items-center gap-1.5" data-state={state}>
                <CheckIcon className={cn("size-3 shrink-0", color, spin && "animate-spin")} />
                {check.link ? (
                  <a href={check.link} target="_blank" rel="noreferrer noopener" className="min-w-0 hover:underline">
                    {name}
                  </a>
                ) : (
                  name
                )}
              </li>
            )
          })}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** A sub-type as the board sends it, from its key — undefined for none, or one it does not know. */
export function subtypeOf(key?: string): Subtype | undefined {
  return key ? currentBoard()?.subtypes?.find((subtype) => subtype.key === key) : undefined
}

/** The colour of a sub-type — on its dot and in its bars, never on its words. "" is no sub-type at all. */
export const subtypeColor = (key: string): string => `var(--subtype-${key || "none"}, currentColor)`

/** A sub-type's dot: the one mark it is known by, in the legend, the filters and the badge alike. */
export function SubtypeDot({ subtype, className }: { subtype: string; className?: string }) {
  return (
    <span
      aria-hidden
      data-slot="subtype-dot"
      className={cn("inline-block size-2 shrink-0 rounded-full", className)}
      style={{ background: subtypeColor(subtype) }}
    />
  )
}

/* What kind of change a code ticket is, as a small badge: a dot and its name,
 * the border in its colour. Discreet on purpose — it is read after the title,
 * not before it. Nothing for a ticket without one. */
export function TicketSubtype({ subtype }: { subtype?: string }) {
  const known = subtypeOf(subtype)
  if (!known) return null
  return (
    <Chip
      className="text-foreground"
      style={{
        borderColor: `color-mix(in oklab, ${subtypeColor(known.key)} 45%, transparent)`,
        background: `color-mix(in oklab, ${subtypeColor(known.key)} 8%, transparent)`,
      }}
    >
      <span
        data-slot="ticket-subtype"
        data-subtype={known.key}
        className="inline-flex items-center gap-1.5"
        title={`${known.commit}:${known.changelog ? ` · CHANGELOG ${known.changelog}` : ""}`}
      >
        <SubtypeDot subtype={known.key} />
        {known.label}
      </span>
    </Chip>
  )
}

/** A tag: one word about a ticket, drawn small enough that five of them still read as one row. */
export function Chip({
  children,
  className,
  style,
}: {
  children: React.ReactNode
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <span
      style={style}
      className={cn(
        "text-muted-foreground inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[0.7rem] whitespace-nowrap",
        className
      )}
    >
      {children}
    </span>
  )
}

export function Away({ label, href }: { label: string; href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline-offset-2 hover:underline"
    >
      {label}
      <ExternalLink className="size-3" />
    </a>
  )
}

/** Notion, the pull request, the session — whichever the ticket has. */
export function TicketLinks({ ticket }: { ticket: Ticket }) {
  const t = useT()
  return (
    <>
      {reachable(ticket.url) ? <Away label="Notion" href={ticket.url} /> : null}
      {ticket.pull_request ? <Away label={t("pull request")} href={ticket.pull_request} /> : null}
      {ticket.session_link ? <Away label={t("session")} href={ticket.session_link} /> : null}
    </>
  )
}

/* A move made from the console that is not in Notion yet — or will not be, and
 * why. On the card itself, because that is where the column it claims to be
 * in is drawn: a card standing in Review that Notion has in Done has to say so
 * right there. */
export function TicketSync({ ticket }: { ticket: Ticket }) {
  const t = useT()
  if (!ticket.sync) return null
  const said =
    ticket.sync === "pending"
      ? t("waiting to be sent to Notion")
      : ticket.sync === "failed"
        ? t("not sent to Notion")
        : t("changed in Notion meanwhile — not overwritten")
  return (
    <div className="flex flex-wrap gap-1.5">
      <Chip
        className={cn(
          ticket.sync === "pending" && "animate-pulse",
          ticket.sync === "failed" && "border-tr-red text-tr-red",
          ticket.sync === "conflict" && "border-tr-amber text-tr-amber"
        )}
      >
        <span title={ticket.sync_error || undefined}>{said}</span>
      </Chip>
    </div>
  )
}

/** What is said *about* a ticket rather than in it: how urgent, on which model, when. */
export function TicketTags({ ticket, lead }: { ticket: Ticket; lead?: React.ReactNode }) {
  const scored = typeof ticket.priority === "number"
  if (!lead && !scored && !ticket.model && !ticket.scheduled && !subtypeOf(ticket.subtype)) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {lead}
      {scored ? <PriorityBadge score={ticket.priority as number} /> : null}
      <TicketSubtype subtype={ticket.subtype} />
      {ticket.model ? (
        <Chip className="min-w-0 max-w-full">
          <span className="truncate" data-slot="ticket-model" title={ticket.model_label || ticket.model}>
            {ticket.model_label || ticket.model}
          </span>
        </Chip>
      ) : null}
      {ticket.scheduled ? <Chip>⏱ {when(ticket.scheduled)}</Chip> : null}
    </div>
  )
}

/* A review's checks, said in the line along the bottom of its card rather than
 * as a badge over its buttons: a fact like its age and its cost, read in the
 * same row. A red one keeps its colour on the words too — it is the one that
 * asks to be seen. */
function FootCi({ ci }: { ci?: Ci | null }) {
  if (!ci) return null
  const { icon: Icon, color, spin } = CI_STATE[ci.state]
  return (
    <span
      data-slot="ticket-ci"
      data-state={ci.state}
      className={cn(
        "flex shrink-0 items-center gap-1 whitespace-nowrap",
        ci.state === "failed" && "text-tr-red font-semibold"
      )}
    >
      <Icon className={cn("size-3", color, spin && "animate-spin")} />
      {CI_WORDS()[ci.state]}
    </span>
  )
}

/* The line along the bottom of a card: where the work goes and how long ago the
 * ticket was made, what it has cost, and the way out to the page it is written
 * on. All facts rather than prose, so all set in the mono face and read as a
 * single ruled row. The project gives way (it truncates) before the age, and
 * both before the cost: a long project name must not push the figure out. */
export function TicketFoot({ ticket }: { ticket: Ticket }) {
  const t = useT()
  const hasCost = typeof ticket.cost === "number" && ticket.cost
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t pt-2.5 font-mono text-[0.7rem]">
      {ticket.project && ticket.project_id ? (
        <Link
          to={projectHref(ticket.project_id)}
          data-slot="ticket-project"
          title={ticket.project}
          aria-label={t("Open the project {{name}}", { name: ticket.project })}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 flex max-w-full min-w-0 items-center gap-1 rounded-sm outline-none hover:underline focus-visible:ring-2"
          onClick={(event) => event.stopPropagation()}
        >
          <ProjectThumb
            project={{ name: ticket.project, icon: ticket.project_icon }}
            className="size-4 rounded-full border-0"
          />
          <span className="min-w-0 truncate">{ticket.project}</span>
        </Link>
      ) : (
        <span className="text-muted-foreground max-w-full min-w-0 truncate">{ticket.project || t("no project")}</span>
      )}
      <FootCi ci={ticket.column === "review" ? ticket.ci : null} />
      {ago(ticket.created) ? (
        <span
          className="text-muted-foreground whitespace-nowrap"
          title={new Date(ticket.created).toLocaleString(currentLanguage(), {
            dateStyle: "medium",
            timeStyle: "short",
          })}
        >
          {ago(ticket.created)}
        </span>
      ) : null}
      {/* 12 min · $0.64: the work beside what it cost, the quieter of the two. */}
      <CardTime time={ticket.worktime} />
      {hasCost ? <span className="whitespace-nowrap tabular-nums">{money(ticket.cost as number)}</span> : null}
      {reachable(ticket.url) ? (
        <a
          href={ticket.url}
          target="_blank"
          rel="noreferrer noopener"
          className="text-muted-foreground hover:text-foreground ms-auto shrink-0"
          aria-label={t("Open in Notion")}
          onClick={(event) => event.stopPropagation()}
        >
          <ExternalLink className="size-3.5" />
        </a>
      ) : null}
    </div>
  )
}

/* The gestures of a ticket in progress and of one put aside — pause, abandon,
 * resume — are kept out of the first load, which has a budget (see
 * `new-ticket-lazy.tsx`). */
const StopGestures = React.lazy(() => import("@/components/console/ticket-stop"))

/* A gesture that costs something once it is made — a pull request merged, a
 * paid session started — asked for twice: once on the card, once in a dialog
 * that says what is about to happen. The others are one click, because moving
 * a card back is one click too. Without a label, it draws no button of its
 * own: something else — an entry in a menu — opens it. */
function Confirmed({
  label,
  title,
  body,
  confirm,
  onConfirm,
  className,
  open,
  onOpenChange,
}: {
  label?: string
  title: string
  body: string
  confirm: string
  onConfirm: () => void
  className?: string
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={body}
      confirm={confirm}
      onConfirm={onConfirm}
      trigger={
        label ? (
          <Button variant="outline" size="sm" className={className}>
            {label}
          </Button>
        ) : null
      }
    />
  )
}

/** The gestures a ticket offers where it stands, or nothing at all where it offers none.
 *
 * Drawn as buttons — an outline, 32 pixels high — rather than as grey words:
 * a card's gestures are the one thing on it you act on, and they read as text
 * you could not click. Where a gesture moves the ticket, the toast that
 * follows names the column it lands in, in the board's own word.
 *
 * Every way back to Ready is confirmed, because Ready is where the next pass
 * starts a paid session: "make ready" on a Done card used to be one stray click
 * away from one. On Done — the column that holds almost every card — the
 * gesture is rare, so it waits behind a "…" rather than sitting on each card.
 */
export function TicketActions({
  ticket,
  className,
  answer,
}: {
  ticket: Ticket
  className?: string
  /** Where answering opens — the ticket's page, on its discussion. None where the discussion already is. */
  answer?: { href: string; onClick?: React.MouseEventHandler<HTMLAnchorElement> }
}) {
  const board = useBoard()
  const t = useT()
  const [asked, setAsked] = React.useState(false)
  const [validating, setValidating] = React.useState(false)
  // A ticket the runner has in hand is not one you move: it is one you stop.
  // Pausing keeps what was done and is one click; abandoning loses it, and asks.
  // Where the board has neither column, nothing is drawn — an empty row would
  // leave a gap on the card where the gestures would have been.
  if (ticket.column === "running" || ticket.column === "paused")
    return (
      <React.Suspense fallback={null}>
        <StopGestures ticket={ticket} className={className} />
      </React.Suspense>
    )
  // A blocked card has one gesture, Unblock: it opens the ticket's discussion,
  // where its question is answered — by a quick reply, a sentence, or running
  // it again as it is — see `ticket-talk.tsx`. Three buttons that all put it
  // back to work left you to guess which one was yours.
  if (ticket.column === "blocked")
    return (
      <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
        <DecideButton
          ticket={ticket}
          icon={ticket.block ? FAMILY_ICON[ticket.block.family] : undefined}
          title={
            ticket.block
              ? [blockSaid(ticket.block.label), blockSaid(ticket.block.help)].filter(Boolean).join("\n")
              : undefined
          }
        />
      </div>
    )
  const named = (key: string) =>
    columnTitle(key, board.columns.find((column) => column.key === key)?.name)
  const block = ticket.column === "failed" ? ticket.block : null
  // A ticket that has run already is run again — « Relancer » — rather than
  // made ready as a draft would be.
  const again = ticket.column === "review" || ticket.column === "done" || ticket.column === "failed"
  const ready = {
    title: again
      ? t("Run “{{title}}” again?", { title: titleOf(ticket) })
      : t("Make “{{title}}” ready?", { title: titleOf(ticket) }),
    body: [
      ticket.column === "validated"
        ? t("Its validation is withdrawn: the runner will not merge or publish it.")
        : "",
      again
        ? t(
            "The ticket goes back to {{column}} and the next pass starts a new session on it — a session that is paid for, like the first one.",
            { column: named("ready") }
          )
        : t(
            "The ticket goes to {{column}} and the next pass starts a session on it — a session that is paid for.",
            { column: named("ready") }
          ),
    ]
      .filter(Boolean)
      .join(" "),
    confirm: again ? t("Run it again") : t("Make it ready"),
    onConfirm: () => void move(ticket, "ready"),
  }
  // The gesture the cause of a stop proposes, first on the card. Answering
  // and the pull request are links; the others put the ticket back in ready,
  // which is the one thing the console can do about them — the line of help
  // says what to do first, when there is something.
  const ci = block?.action === "base-ci" ? actionsOf(ticket.pull_request) : ""
  const proposed = !block
    ? null
    : block.action === "answer" && answer ? (
        <Button variant="outline" size="sm" asChild className="text-tr-amber hover:text-tr-amber">
          <Link to={answer.href} onClick={answer.onClick} data-slot="block-action">
            <MessageCircleQuestion />
            {t("Answer")}
          </Link>
        </Button>
      ) : block.action === "open-pr" && ticket.pull_request ? (
        <Button variant="outline" size="sm" asChild>
          <a href={ticket.pull_request} target="_blank" rel="noreferrer noopener" data-slot="block-action">
            {t("See the pull request")}
            <ExternalLink />
          </a>
        </Button>
      ) : ci ? (
        <Button variant="outline" size="sm" asChild>
          <a href={ci} target="_blank" rel="noreferrer noopener" data-slot="block-action">
            {t("See the base's CI")}
            <ExternalLink />
          </a>
        </Button>
      ) : null
  // Giving a ticket up is offered wherever it stands but in the runner's hands,
  // and only on a board that has a column to give it up in. Behind "…": it is
  // the gesture a card is least often for, and one click from it is enough —
  // the way back is on the cancelled card itself.
  const cancel =
    board.cancel && ticket.column !== "cancelled" ? (
      <DropdownMenuItem onSelect={() => void move(ticket, "cancelled")}>{t("Cancel the ticket")}</DropdownMenuItem>
    ) : null
  // Validating is the gesture the runner acts on — it merges the pull request,
  // or publishes what the ticket holds — where "done" only files the ticket
  // away yourself. Offered only on a board that has the column.
  const validate = {
    title: t("Validate “{{title}}”?", { title: titleOf(ticket) }),
    body: ticket.pull_request
      ? t("The runner merges its pull request on its next pass. A merge is not taken back from here.")
      : t("The runner publishes what the ticket holds on its next pass."),
    confirm: t("Validate"),
    onConfirm: () => void move(ticket, "validated"),
  }
  const menu = (items: React.ReactNode) => (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" aria-label={t("More actions")} title={t("More actions")}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">{items}</DropdownMenuContent>
    </DropdownMenu>
  )
  // A card in review is there to be decided on, and says so with one small
  // button, the same height as the others on the console; the plain gestures wait behind "…", in the order they are
  // reached for, giving it up last and apart. Five buttons in three styles made
  // Decide and validate fight for the eye. The menu only opens the same
  // dialogs: what each gesture asks first, and where it moves the ticket, are
  // those of the buttons it replaces.
  if (ticket.column === "review")
    return (
      <div className={cn("flex flex-wrap items-center justify-end gap-1.5", className)}>
        <DecideButton ticket={ticket} />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="icon-sm"
              className="shrink-0"
              aria-label={t("More actions")}
              title={t("More actions")}
            >
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {board.validate ? (
              <DropdownMenuItem onSelect={() => setValidating(true)}>{t("Validate and publish")}</DropdownMenuItem>
            ) : null}
            <DropdownMenuItem onSelect={() => setAsked(true)}>{t("Run the agent again")}</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void move(ticket, "done")}>{t("Mark done")}</DropdownMenuItem>
            {board.cancel ? (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" onSelect={() => void move(ticket, "cancelled")}>
                  {t("Cancel the ticket")}
                </DropdownMenuItem>
              </>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
        <Confirmed open={asked} onOpenChange={setAsked} {...ready} />
        {board.validate ? <Confirmed open={validating} onOpenChange={setValidating} {...validate} /> : null}
      </div>
    )
  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {/* What a card waiting on you is for: why it waits, and what to do —
          see `ticket-decision.tsx`. The plain gestures stay beside it. */}
      <DecideButton ticket={ticket} />
      {proposed}
      {/* A cancelled ticket is reopened as a draft: given up on is not ready,
          and the session a ready ticket starts is paid for. */}
      {ticket.column === "cancelled" ? (
        <Button
          variant="outline"
          size="sm"
          title={t("Back to the drafts: the runner does not touch it until it is made ready.")}
          onClick={() => void move(ticket, "draft")}
        >
          {t("Reopen")}
        </Button>
      ) : null}
      {ticket.column === "done" ? (
        <>
          {menu(
            <>
              <DropdownMenuItem onSelect={() => setAsked(true)}>{t("Run again")}</DropdownMenuItem>
              {cancel}
            </>
          )}
          <Confirmed open={asked} onOpenChange={setAsked} {...ready} />
        </>
      ) : ticket.column !== "ready" ? (
        <Confirmed label={again ? t("Run again") : t("Make ready")} {...ready} />
      ) : null}
      {ticket.column === "ready" ? (
        <Button
          variant="outline"
          size="sm"
          title={t("The runner no longer touches it, until it is made ready again.")}
          onClick={() => void move(ticket, "blocked")}
        >
          {t("Set aside")}
        </Button>
      ) : null}
      {cancel && ticket.column !== "done" ? menu(cancel) : null}
    </div>
  )
}
