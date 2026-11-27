import * as React from "react"
import { ChevronDown, ExternalLink, GitBranch } from "lucide-react"

import { useBoardWith } from "@/lib/board-store"
import { useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import { reading } from "@/lib/phase"
import { canAct } from "@/lib/role"
import type { Board, TicketDetail } from "@/lib/types"
import { upcoming } from "@/lib/later"
import { cn } from "@/lib/utils"

import { PriorityBadge } from "./priority"
import { TicketEstimate } from "./ticket-estimate"
import { TicketProjectChoice } from "./ticket-project"
import { AfterField, LaunchNow, ModelField, PriorityField, ProjectField, ScheduledField } from "./ticket-settings"
import { AwaitedLink, TicketWaits } from "./ticket-waits"
import { TicketTime } from "./ticket-time"
import { TicketValidation } from "./ticket-validation"
import {
  Chip,
  FAMILY_ICON,
  LABEL,
  NO_COMMIT,
  SEED,
  TicketActions,
  TicketCi,
  TicketEarlier,
  TicketHeld,
  TicketSubtype,
  ago,
  blockSaid,
  capital,
  choiceWord,
  columnTitle,
  fade,
  familyColor,
  lasted,
  when,
} from "./ticket-bits"

/* What a ticket's view opens on, above its tabs — the same three blocks in the
 * window over the board and on the ticket's page.
 *
 * The view said everything about a ticket at one weight: its column was the
 * fifth word of a strip, between the priority and « created 3d ago »; the pull
 * request was said three times (the header, the strip, the result) and its
 * checks twice; and what the ticket was waiting for — a decision, an answer —
 * was a tab to find among six, or a line of small print. Somebody opening a
 * ticket asks two things, in this order: where does it stand, and is there
 * something for me to do. So:
 *
 * - `TicketStatus` answers both, first: the column in its colour, one sentence
 *   on what it is waiting for, and the ticket's gestures — the one that
 *   matters as a filled button.
 * - `TicketFacts` is what the ticket is and what running it came to, each
 *   said once and under its name, the settings among them changed in place
 *   (`ticket-settings.tsx`). The whole list in the rail beside the tabs, where
 *   the view has room for one; one line and a « Details » where it has not.
 * - `TicketDelivery` is the pull request, once: where it stands, its checks,
 *   the way to its diff.
 *
 * See `notes/design/ticket-view/audit.md` for what was wrong and the
 * directions weighed.
 */

/** The banner's tint: the column's colour, as on the board. A column without
 * one is plain. A colour and not ten classes: see `Unfolded`, on the budget. */
const BAND: Record<string, string> = {
  waiting: "var(--tr-green)",
  ready: "var(--tr-green)",
  running: "var(--primary)",
  blocked: "var(--tr-amber)",
  review: "var(--tr-violet)",
  validated: "var(--tr-pink)",
}

const boardColumns = (board: Board) => board.columns
const boardScored = (board: Board) => Boolean(board.priority)

/** The column a ticket is in, in the console's word for it where it has one. */
function useStatusWord(column: string): string {
  const t = useT()
  const columns = useBoardWith(boardColumns)
  return LABEL[column]
    ? t(LABEL[column])
    : capital(columnTitle(column, columns.find((item) => item.key === column)?.name))
}

/** What the ticket is waiting for, in one sentence — nothing for a column the console has no word on. */
function useAwaited(ticket: TicketDetail): string {
  const t = useT()
  switch (ticket.column) {
    case "draft":
      return t("A draft: the runner does not touch it until it is made ready.")
    case "waiting":
      return t("Waiting for its moment: it is made ready by itself once its date has come and the tickets it waits for are finished.")
    case "ready":
      return t("Waiting for a free place: a session starts on it by itself.")
    case "running": {
      const phase = reading(ticket.phase, Date.now())
      return phase?.said ? capital(t(phase.said.key, phase.said.params)) : t("A session is working on it.")
    }
    case "paused":
      return t("Paused: what was done is kept, and nothing runs until it is resumed.")
    case "blocked":
      // The cause says it, under the status: see below.
      return ticket.block && ticket.block.code !== NO_COMMIT ? "" : t("Stopped: it waits for you to run it again.")
    case "review":
      return canAct() ? t("Your decision is awaited.") : t("Waiting for a decision.")
    case "validated":
      return ticket.pull_request
        ? t("Validated: the runner merges its pull request.")
        : t("Validated: the runner publishes it at the next free place.")
    case "done":
      return t("Finished: nothing is left to do.")
    case "cancelled":
      return t("Given up: nothing runs on it.")
    default:
      return ""
  }
}

export function TicketStatus({ ticket }: { ticket: TicketDetail }) {
  const t = useT()
  const status = useStatusWord(ticket.column)
  const awaited = useAwaited(ticket)
  // Not a session that committed nothing, which is no fault when there was
  // nothing to change: the discussion says it in passing, on the session's line.
  const block = ticket.block && ticket.block.code !== NO_COMMIT ? ticket.block : null
  const Cause = block ? FAMILY_ICON[block.family] : null
  return (
    <section
      data-slot="ticket-status"
      data-column={ticket.column}
      className="bg-card flex min-w-0 flex-col gap-2 rounded-xl border px-4 py-3"
      style={
        BAND[ticket.column]
          ? {
              borderColor: fade(BAND[ticket.column], 45),
              backgroundImage: `linear-gradient(${fade(BAND[ticket.column], 6)}, ${fade(BAND[ticket.column], 6)})`,
            }
          : undefined
      }
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-56">
          <p className="flex items-center gap-2 text-base leading-snug font-semibold">
            <span className={cn("size-2 shrink-0 rounded-full", SEED[ticket.column] ?? "bg-muted-foreground")} />
            <span data-slot="ticket-status-word">{status}</span>
          </p>
          {block ? (
            <div data-slot="ticket-block" data-code={block.code} className="mt-1 flex flex-col gap-0.5">
              <p className="flex items-center gap-1.5 text-sm font-medium">
                {Cause ? <Cause className="size-4 shrink-0" style={{ color: familyColor(block.family) }} /> : null}
                <span title={block.code}>{blockSaid(block.label)}</span>
              </p>
              <p className="text-muted-foreground text-sm leading-relaxed break-words">{blockSaid(block.help)}</p>
            </div>
          ) : awaited ? (
            <p data-slot="ticket-status-awaited" className="text-muted-foreground mt-0.5 text-sm break-words">
              {awaited}
            </p>
          ) : null}
        </div>
        {/* The ticket's gestures, where its status is said: the one it waits for first. */}
        <TicketActions ticket={ticket} className="shrink-0" />
      </div>
      {/* Stopped on its project: another one, chosen here, and run again. */}
      {block ? <TicketProjectChoice ticket={ticket} /> : null}
      {/* Why a ready ticket is still waiting, when the wait is out of the ordinary. */}
      <TicketHeld ticket={ticket} />
      {/* And what a waiting one waits for: its date, the tickets it comes after. */}
      <TicketWaits ticket={ticket} />
      {/* A date still to come: when, unless the line above says it already, and « Launch now »
          where the date is all that holds the ticket back — ready, or validated. */}
      {upcoming(ticket.scheduled, Date.now()) && !["done", "cancelled"].includes(ticket.column) ? (
        <div className="flex flex-wrap items-center gap-1.5" data-slot="ticket-scheduled-line">
          {(ticket.column === "ready" && ticket.held?.reason === "date") || ticket.column === "waiting" ? null : (
            <Chip>⏱ {t("Scheduled for {{at}}", { at: when(ticket.scheduled) })}</Chip>
          )}
          {canAct() && ["waiting", "ready", "validated"].includes(ticket.column) ? <LaunchNow ticket={ticket} /> : null}
        </div>
      ) : null}
      {/* What the last pass said, that its card no longer draws: only while it
          waits in ready, the stream moving it on before the page is read again. */}
      {ticket.earlier && (ticket.column === "ready" || ticket.column === "draft") ? (
        <TicketEarlier earlier={ticket.earlier} />
      ) : null}
    </section>
  )
}

/* The facts, each one row of a list: its name, then what it is.
 *
 * One list, drawn two ways. Folded, it is a line: the names are kept for a
 * screen reader only, and the rows few look for (`rare`) are not drawn.
 * Unfolded — by its « Details » button, or by itself in the rail beside the
 * tabs (`rail`) — it is a column, every row under its name, and its settings
 * are fields. Which of the two
 * is decided here, by the page, and not by a breakpoint in the stylesheet:
 * the first load's stylesheet is held to a budget (tests/test_release.py) and
 * two dozen rules for one list of a ticket's page had no room in it.
 */
const Unfolded = React.createContext(false)

function Fact({
  name,
  rare = false,
  stacked = false,
  children,
}: {
  name: string
  rare?: boolean
  /** Its name above it, the whole width under: a setting with more to say than a word. */
  stacked?: boolean
  children: React.ReactNode
}) {
  const unfolded = React.use(Unfolded)
  if ((rare || stacked) && !unfolded) return null
  if (stacked)
    return (
      <div className="flex min-w-0 flex-col gap-1">
        <dt className="text-muted-foreground text-xs">{name}</dt>
        <dd className="min-w-0">{children}</dd>
      </div>
    )
  return (
    <div className={cn("flex min-w-0 items-baseline gap-x-3", unfolded && "justify-between")}>
      <dt className={cn("text-muted-foreground shrink-0 text-xs", !unfolded && "sr-only")}>{name}</dt>
      <dd className={cn("flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5", unfolded && "justify-end")}>
        {children}
      </dd>
    </div>
  )
}

export function TicketFacts({
  ticket,
  rail = false,
  validation,
  onSession,
}: {
  ticket: TicketDetail
  /** In the rail beside the tabs: the whole list, every fact under its name, the settings changed in place. */
  rail?: boolean
  /** Review (Force validated), once the page is read: a setting of its own, among the facts. */
  validation?: { validation: string; validation_inherited: string }
  /** The session's log, on the ticket's Activity tab. */
  onSession: () => void
}) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const scored = useBoardWith(boardScored)
  const unfolded = open || rail
  // Until the page's own read has said, a model written on the ticket is the one it has.
  const used =
    ticket.model_in_use ??
    (ticket.model ? { label: ticket.model_label ?? ticket.model, full: ticket.model, default: false } : undefined)
  const created = ago(ticket.created)
  const cost = typeof ticket.cost === "number" && ticket.cost ? money(ticket.cost) : ""
  const took = typeof ticket.duration === "number" && ticket.duration ? lasted(ticket.duration) : ""
  // The branch, on the repository the pull request is on: that is where it is read.
  const branchUrl =
    ticket.branch && /\/pull\/\d+/.test(ticket.pull_request)
      ? ticket.pull_request.replace(
          /\/pull\/\d+.*$/,
          `/tree/${ticket.branch.split("/").map(encodeURIComponent).join("/")}`
        )
      : ""
  const branch = (
    <>
      <GitBranch className="size-3.5 shrink-0" />
      <span className="truncate">{ticket.branch}</span>
    </>
  )
  return (
    <section
      data-slot="ticket-summary"
      data-open={unfolded}
      aria-label={t("About this ticket")}
      className={cn("flex min-w-0 items-start gap-2 text-sm", rail && "bg-card rounded-xl border px-4 py-3")}
    >
      <Unfolded value={unfolded}>
      <dl
        className={cn(
          "flex min-w-0 flex-1 gap-x-4",
          unfolded ? "flex-col gap-y-2" : "flex-wrap items-baseline gap-y-1"
        )}
      >
        <Fact name={t("Project")}>
          {unfolded ? (
            <ProjectField ticket={ticket}>
              <span className="font-semibold">{ticket.project || t("no project — a document")}</span>
            </ProjectField>
          ) : (
            <span className="font-semibold">{ticket.project || t("no project — a document")}</span>
          )}
        </Fact>
        {ticket.type ? (
          <Fact name={t("Type")}>
            <span>{choiceWord(ticket.type)}</span>
            {ticket.subtype ? <TicketSubtype subtype={ticket.subtype} /> : null}
          </Fact>
        ) : null}
        {typeof ticket.priority === "number" || (unfolded && scored) ? (
          <Fact name={t("Priority")}>
            {unfolded ? (
              <PriorityField ticket={ticket}>
                {typeof ticket.priority === "number" ? <PriorityBadge score={ticket.priority} /> : null}
              </PriorityField>
            ) : typeof ticket.priority === "number" ? (
              <PriorityBadge score={ticket.priority} />
            ) : null}
          </Fact>
        ) : null}
        {cost ? (
          <Fact name={t("Cost")}>
            <span>{cost}</span>
          </Fact>
        ) : null}
        {/* The column empty is not "no model": it is the one the session
            announced, or the runner's, or Claude Code's own. The server says
            which, as provider/model; the full identifier is the tooltip. */}
        {used?.label || unfolded ? (
          <Fact name={t("Model")}>
            {unfolded ? (
              <ModelField ticket={ticket} used={used}>
                {used?.label ? <ModelSaid used={used} /> : <span className="text-muted-foreground">—</span>}
              </ModelField>
            ) : used?.label ? (
              <ModelSaid used={used} />
            ) : null}
          </Fact>
        ) : null}
        {/* The runs' time with the clock stopped while it waited — not the
            time since it was made, which holds the queue and the review. */}
        {ticket.worktime ? (
          <Fact name={t("Worked")}>
            <TicketTime time={ticket.worktime} />
          </Fact>
        ) : null}
        {/* The last session alone: the column the runner writes after each run. */}
        {took ? (
          <Fact name={t("Last session")} rare>
            <span>{took}</span>
          </Fact>
        ) : null}
        {ticket.estimate ? (
          <Fact name={t("Estimate")} rare>
            <TicketEstimate estimate={ticket.estimate} />
          </Fact>
        ) : null}
        {created ? (
          <Fact name={t("Creation")} rare>
            <span>{created}</span>
          </Fact>
        ) : null}
        {ticket.scheduled || (unfolded && canAct() && !["done", "cancelled"].includes(ticket.column)) ? (
          <Fact name={t("Scheduled")}>
            {unfolded ? (
              <ScheduledField ticket={ticket}>
                <span>{when(ticket.scheduled)}</span>
              </ScheduledField>
            ) : (
              <span>{when(ticket.scheduled)}</span>
            )}
          </Fact>
        ) : null}
        {/* The tickets it waits for (« Après »): changed here, in the rail; said as links elsewhere. */}
        {ticket.after?.length || (unfolded && canAct() && !["done", "cancelled"].includes(ticket.column)) ? (
          <Fact name={t("Waits for")} stacked={unfolded}>
            {unfolded ? (
              <AfterField ticket={ticket} />
            ) : (
              <span className="flex flex-wrap gap-x-2">
                {(ticket.after ?? []).map((one) => (
                  <AwaitedLink key={one.id} awaited={one} />
                ))}
              </span>
            )}
          </Fact>
        ) : null}
        {ticket.branch ? (
          <Fact name={t("Branch")} rare>
            {branchUrl ? (
              <a
                href={branchUrl}
                target="_blank"
                rel="noreferrer noopener"
                data-slot="ticket-summary-branch"
                className="inline-flex max-w-full min-w-0 items-center gap-1 font-mono text-xs underline-offset-2 hover:underline"
              >
                {branch}
              </a>
            ) : (
              <span
                data-slot="ticket-summary-branch"
                className="inline-flex max-w-full min-w-0 items-center gap-1 font-mono text-xs"
              >
                {branch}
              </span>
            )}
          </Fact>
        ) : null}
        {ticket.session ? (
          <Fact name={t("Session")} rare>
            <span data-slot="ticket-summary-details" className="inline-flex items-center gap-1.5">
              <button
                type="button"
                onClick={onSession}
                className="cursor-pointer font-mono text-xs underline-offset-2 hover:underline"
                title={ticket.session}
              >
                {ticket.session.slice(0, 8)}
              </button>
              {ticket.session_link ? (
                <a
                  href={ticket.session_link}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="text-muted-foreground hover:text-foreground"
                  title={t("Open the session")}
                  aria-label={t("Open the session")}
                >
                  <ExternalLink className="size-3.5" />
                </a>
              ) : null}
            </span>
          </Fact>
        ) : null}
        {ticket.runner ? (
          <Fact name={t("Taken by")} rare>
            <span className="font-mono text-xs break-all">{ticket.runner}</span>
          </Fact>
        ) : null}
        {validation ? (
          <Fact name={t("Review")} stacked>
            <TicketValidation ticket={{ ...ticket, ...validation }} compact />
          </Fact>
        ) : null}
      </dl>
      </Unfolded>
      {/* Said in the page, not in a tooltip: a finger has no hover. The rail has them all already. */}
      {rail ? null : (
      <button
        type="button"
        data-slot="ticket-summary-more"
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
        className="text-muted-foreground hover:text-foreground -my-1 inline-flex min-h-7 shrink-0 cursor-pointer items-center gap-0.5 rounded px-1 text-xs"
      >
        {t("Details")}
        <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      )}
    </section>
  )
}

/** The model, as `provider/model` without the provider when it is Claude's; the full identifier is the tooltip. */
function ModelSaid({ used }: { used: { label: string; full: string; default?: boolean } }) {
  const t = useT()
  return (
    <span title={used.full}>
      {used.label.replace(/^claude\//, "")}
      {used.default ? <span className="text-muted-foreground font-normal"> · {t("default")}</span> : null}
    </span>
  )
}

/* The pull request, said once for the whole view: where it stands, its checks
 * — each one, a click away — and the way to its diff. */
export function TicketDelivery({ ticket }: { ticket: TicketDetail }) {
  const t = useT()
  if (!ticket.pull_request) return null
  const number = ticket.pull_request.match(/\/pull\/(\d+)/)?.[1]
  const state =
    ticket.column === "done"
      ? t("merged")
      : ticket.column === "validated"
        ? t("validated, being merged")
        : ticket.column === "review"
          ? t("open, waiting for your review")
          : ticket.column === "cancelled"
            ? t("closed")
            : t("open")
  return (
    <section
      data-slot="ticket-delivery"
      aria-label={t("Pull request")}
      className="bg-card flex min-w-0 flex-col gap-2 rounded-xl border px-4 py-2.5 text-sm"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <a
          href={ticket.pull_request}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1.5 font-semibold underline-offset-2 hover:underline"
        >
          <GitBranch className="size-4" />
          {number ? `PR #${number}` : t("pull request")}
        </a>
        <span className="text-muted-foreground">{state}</span>
        <a
          href={`${ticket.pull_request.replace(/\/+$/, "")}/files`}
          target="_blank"
          rel="noreferrer noopener"
          className="text-primary ml-auto inline-flex items-center gap-1 underline-offset-2 hover:underline"
        >
          {t("View the diff")}
          <ExternalLink className="size-3.5" />
        </a>
      </div>
      {ticket.ci ? <TicketCi ci={ticket.ci} detailed /> : null}
    </section>
  )
}
