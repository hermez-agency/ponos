import * as React from "react"
import { ChevronLeft, ChevronRight, LayoutGrid } from "lucide-react"
import {
  ActionList,
  useFormContext,
  type FormInterface,
  type InputControllerComponentInterface,
} from "react-data-form"
import {
  Link,
  ListTable,
  RowWrapperColumnComponent,
  createResourceCollection,
  createViewResource,
  generateLinkByResource,
  layout,
  useCurrentViewResourceContext,
  useListViewContext,
  type ListComponentPropsInterface,
  type ResourceDefinition,
  type RowComponentPropsInterface,
  type RowInterface,
} from "react-resource-view"

import { MarkdownInputController } from "@/components/console/markdown-editor"
import {
  choiceWord,
  columnTitle,
  SEED,
  TicketActions,
  TicketBlock,
  TicketCi,
  TicketFoot,
  TicketHeld,
  TicketSync,
  TicketTags,
  ago,
  capital,
  lasted,
  when,
} from "@/components/console/ticket-bits"
import { IdeasButton } from "@/components/console/ideas-deck"
import {
  EDITOR_SETTLES,
  GoalInputController,
  NewTicketFields,
  NewTicketFoot,
  PillsInputController,
  OnInputController,
  PlanInputController,
  ProjectInputController,
  SegmentedInputController,
} from "@/components/console/new-ticket-lazy"
import { EmptyState } from "@/components/console/empty-state"
import { ProjectThumb } from "@/components/console/project-picture"
import { ModelInputController } from "@/components/console/model-input-lazy"
import { PriorityBadge, PriorityInputController } from "@/components/console/priority"
import { Robot, TicketRobot } from "@/components/console/robot"
import { RunnerStrip } from "@/components/console/runner-strip"
import { HealthBand } from "@/components/console/health-band"
import { StatisticsBand } from "@/components/console/statistics"
import { ToHandle } from "@/components/console/to-handle"
import { CardLive } from "@/components/console/session-log"
import { useOpensOverTheList } from "@/components/console/record-window"
import { SeriesButton } from "@/components/console/ticket-decision"
import { ticketWindow } from "@/components/console/ticket-window"
import {
  Marked,
  NoMatch,
  TicketSearch,
  useSearchWords,
  useTicketFilter,
} from "@/components/console/ticket-search"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { ApiError, api } from "@/lib/api"
import { optimistic } from "@/lib/optimistic"
import {
  addTicket,
  boardOnce,
  currentBoard,
  dropTicket,
  moveTicket,
  replaceTicket,
  subscribeBoard,
  titleOf,
  useBoard,
} from "@/lib/board-store"
import { counted, t, useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import { DEFAULT_SCORE, readScore } from "@/lib/priority"
import { layoutOf, useLayoutInTheAddress, useRememberedLayout } from "@/lib/resource-view"
import { columnState } from "@/lib/bulk"
import {
  clearSelection,
  pick,
  pickAll,
  useSelected,
  useSelecting,
  useSelection,
} from "@/lib/selection-store"
import type { ColumnKey, Ticket, TicketDetail } from "@/lib/types"
import { cn } from "@/lib/utils"
import { canAct, readOnly } from "@/lib/role"
import { usePhone } from "@/lib/phone"
import { openingColumn } from "@/lib/to-handle"

/* The tickets, declared once for react-resource-view.
 *
 * One declaration says what the board is: where its rows come from (the
 * stream), what a card looks like (`TicketCard`), which columns it is laid out
 * in (the board's own), how a card is moved (a drop is a status change), what
 * a new ticket asks for (the create form), and what opening one shows (the
 * ticket page). The package does the rest — the list, its header, the panel a
 * form opens in, the URL.
 */

export const TICKETS = "tickets"

/* The page under a ticket, read once per opening.
 *
 * Reading it is the slow part of opening a ticket — the server reads its whole
 * page — and the package asks for the record again every time the
 * stream moves the board, so one opening sent the same request two or three
 * times. The read is kept, promise and all, for as long as the page is open:
 * asked again for the same ticket it is the same read, unless the board says
 * the ticket was edited since. Leaving the page lets go of it, so the next
 * opening reads a brief changed since. A ticket the board does not have
 * stays not had: asking again would only fetch the same 404. */
let held: { id: string; edited: string; read: Promise<TicketDetail> } | null = null
let letGo: ReturnType<typeof setTimeout> | undefined

export function readTicket(id: string, edited = ""): Promise<TicketDetail> {
  if (!held || held.id !== id || (edited && held.edited && edited !== held.edited)) {
    const read = api.ticket(id)
    const reading = { id, edited, read }
    held = reading
    read.then(
      (detail) => {
        if (!reading.edited) reading.edited = detail.edited
      },
      (error) => {
        // A failed read is not kept: "Try again" has to try.
        if (held === reading && !(error instanceof ApiError && error.status === 404)) held = null
      }
    )
  }
  return held.read
}

/** The ticket page is on screen: what it read stays read. */
export function holdTicket() {
  clearTimeout(letGo)
}

/* The ticket page left the screen. A tick later rather than now: React's
 * strict mode takes a page off and puts it back at once, and that is not
 * somebody leaving. */
export function releaseTicket() {
  letGo = setTimeout(() => {
    held = null
  })
}

/** A ticket as the views hold it: the row, and an IRI so the package can address it. */
export type TicketItem = Ticket & {
  "@id": string
  "@type": string
  content?: string
  /** The cost as a table cell reads it — the number is for the badges. */
  spent: string
  /** How long the run took, in words. */
  took: string
  /** When it is due, written the way the console writes a date. */
  due: string
  /** When it last changed, in the words a card has room for. */
  changed: string
}

/** What the console writes about a ticket: a new one, or the column an old one moves to. */
export interface TicketWrite {
  id?: string
  column?: ColumnKey
  title?: string
  body?: string
  project?: string
  ready?: boolean
  /** A score from 0 to 100, as typed: empty is 50. */
  priority?: string | number
  type?: string
  model?: string
  subtype?: string
  /** The page of the goal it serves; empty for none. */
  goal?: string
  /** « Plan d'abord »: a plan, and a yes, before any code. */
  plan?: boolean
  /** The prompt run at every change of its status; empty for none. */
  on?: string
}

const item = (ticket: Ticket | TicketDetail): TicketItem => ({
  ...ticket,
  "@id": `/api/tickets/${ticket.id}`,
  "@type": TICKETS,
  // The card, the table and the page's header all read the title from here.
  title: titleOf(ticket),
  spent: typeof ticket.cost === "number" && ticket.cost ? money(ticket.cost) : "",
  took: typeof ticket.duration === "number" && ticket.duration ? lasted(ticket.duration) : "",
  due: when(ticket.scheduled),
  changed: ago(ticket.edited),
})

/** The column's name, as the board spells it. */
export function columnName(key: string): string {
  return capital(columnTitle(key, currentBoard()?.columns.find((column) => column.key === key)?.name))
}

/* -- the forms ------------------------------------------------------------ */

/* The title, as a field that knows when it is wrong.
 *
 * The package's own text field draws the sentence under a refused field but
 * never marks the field itself, so a screen reader heard "Title, required" and
 * nothing more. Same box, with `aria-invalid` while the form holds a violation
 * for it, and the sentence tied to it. */
const TitleInputController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const invalid = Boolean(formInput.violations?.length)
  const id = formInput.id ?? "field-title"
  const field = React.useRef<HTMLInputElement>(null)
  useSendOnControlEnter(field)
  return (
    <>
      <Input
        ref={field}
        id={id}
        name={formInput.name}
        defaultValue={String(formInput.value ?? "")}
        onChange={(event) => onChange({ ...formInput, value: event.target.value, violations: [] })}
        placeholder={t(formInput.placeholder ?? "")}
        required
        autoComplete="off"
        // The one line the board shows: the largest thing in the dialog.
        className="h-11 text-lg font-semibold md:text-lg"
        // The dialog opens before the form inside it is drawn, so the only
        // thing it can hand the cursor to is its cross. A new ticket starts
        // with its title: the field takes the cursor as it appears.
        autoFocus
        aria-invalid={invalid || undefined}
        aria-errormessage={invalid ? `${id}-problem` : undefined}
      />
      {invalid ? (
        <span id={`${id}-problem`} className="sr-only">
          {formInput.violations?.map((violation) => violation.message).join(" ")}
        </span>
      ) : null}
    </>
  )
}

/* Ctrl+Enter (⌘+Enter on a Mac) launches the ticket from any field of the
 * form, the brief included — Enter alone is a new line there. It is the launch
 * button pressed, so a draft asked for a moment ago does not make this one a
 * draft too. Listened to on the form, before the field: the editor would
 * otherwise take the key for itself. From the brief it waits a moment, because
 * the editor tells the form what it holds a little after the last key, and the
 * last words typed would be left out of the ticket. */
function useSendOnControlEnter(field: React.RefObject<HTMLElement | null>) {
  React.useEffect(() => {
    const form = field.current?.closest("form")
    if (!form) return
    const send = (event: KeyboardEvent) => {
      if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return
      event.preventDefault()
      event.stopPropagation()
      const editing = (event.target as Element | null)?.closest?.('[data-slot="markdown-editor"]')
      const launch = () => {
        const button = form.querySelector<HTMLButtonElement>("[data-launch]")
        if (button) button.click()
        else form.requestSubmit()
      }
      window.setTimeout(launch, editing ? EDITOR_SETTLES : 0)
    }
    form.addEventListener("keydown", send, true)
    return () => form.removeEventListener("keydown", send, true)
  }, [field])
}

/* Three a board may or may not have a column for: type, sub-type, model —
 * the priority, a score, is `PriorityInputController`'s. Drawn only where it
 * has one — a value for a missing column would be dropped on its way in — and
 * always optional. The options are the
 * board's (see `Api._choices`): read from the board the console already holds,
 * which is there before a dialog over it can open. The empty one comes first,
 * and says in its tooltip what empty means. */
function choiceInput(
  key: "type" | "model" | "subtype" | "goal",
  empty: string,
  meaning: string,
  controller: InputControllerComponentInterface
) {
  return {
    label: { type: "Type", model: "Model", subtype: "Sub-type", goal: "Goal" }[key],
    controller,
    hidden: () => !currentBoard()?.choices?.[key]?.length,
    getValueOptions: async () => [
      { value: "", label: t(empty), description: meaning ? t(meaning) : undefined },
      // A sub-type in the developers' word, as the card says it.
      ...(key === "subtype"
        ? (currentBoard()?.subtypes ?? []).map((subtype) => ({
            value: subtype.key,
            label: subtype.label,
          }))
        : // The type in the console's language (`choiceWord`),
          // their values the board's; a model and a goal by their own names.
          (currentBoard()?.choices?.[key] ?? []).map((choice) =>
            key === "model" || key === "goal" ? choice : { ...choice, label: choiceWord(choice.label) }
          )),
    ],
  }
}

/** A refusal about one field, in the shape the form draws under that field. */
class FieldProblem extends Error {
  readonly data: { error: string; violations: { propertyPath: string; message: string }[] }

  constructor(field: string, message: string) {
    super(message)
    this.data = { error: message, violations: [{ propertyPath: field, message }] }
  }
}
/** The projects a ticket can point at — those with a page — and none, which makes it a document. */
export async function projectChoices() {
  const { projects } = await api.projects().catch(() => ({ projects: [] }))
  for (const project of projects) knownProjects.set(project.id, { name: project.name, kind: project.kind })
  return [
    { value: "", label: "no project — a document" },
    // The kind said the way the rest of the console says it: the list of
    // projects says "code work", and this said "code".
    // Behind the project's mark, as the list draws it: the label is
    // drawn as it is given, an element as well as a sentence.
    ...projects
      // One the configuration alone names has no page to point at.
      .filter((project) => project.id)
      .map((project) => ({
        value: project.id,
        label: (
          <span className="inline-flex min-w-0 items-center gap-2">
            <ProjectThumb project={project} className="size-5 rounded" />
            {`${project.name} — ${project.kind === "code" ? t("code work") : t("document work")}`}
          </span>
        ),
      })),
  ]
}

/* What a new ticket asks for. Drawn by react-data-form, submitted to
 * `createItem` — in the two columns of `NewTicketFields`, with the draft and
 * launch buttons of `NewTicketFoot` under them (see `new-ticket.tsx`).
 *
 * A label is translated by the package as it draws it; the greyed example in
 * a field is not — it is used as it is given. That one is read from the
 * dictionary here, as the field is drawn, which is what the getter is for: the
 * declaration is built once, and the language can change after it.
 */
const createForm: FormInterface = {
  components: { formInputs: NewTicketFields, formSubmitAction: NewTicketFoot },
  inputs: {
    title: {
      label: "Title",
      required: true,
      // An example, and a key: the package reads the placeholder through the
      // dictionary as it draws the field. It used to be French in every
      // language.
      placeholder: "Remove the banner from the dashboard",
      controller: TitleInputController,
      // The example in the field says what it is: the label is for the screen reader.
      className: "[&_[data-slot=field-label]]:sr-only",
    },
    body: {
      label: "The brief",
      get placeholder() {
        return t("What must change, where, and how you will know it is done.")
      },
      controller: MarkdownInputController,
      // The decorator around the field: the brief takes what the column has left.
      className: "flex min-h-0 flex-1 flex-col [&>[data-slot=field]]:flex-1 [&_[data-slot=markdown-editor]]:min-h-60 [&_[data-slot=markdown-editor]]:flex-1",
    },
    project: {
      label: "Project",
      // A board can hold many projects: typed into, not scrolled through.
      controller: ProjectInputController,
      getValueOptions: projectChoices,
    },
    type: choiceInput(
      "type",
      "Auto",
      "The road the ticket takes. Empty, the runner deduces it before the ticket runs.",
      SegmentedInputController
    ),
    subtype: choiceInput(
      "subtype",
      "deduced by the runner",
      "What kind of change a code ticket is: the prefix of its commit and its CHANGELOG section. Empty, the runner deduces it.",
      PillsInputController
    ),
    // The goal it serves: none unless chosen, and drawn only where the board
    // can point at one and there are goals still worked toward to point at —
    // those of the chosen project first.
    goal: choiceInput("goal", "no goal", "", GoalInputController),
    // A score, drawn only where the board has the column to keep it in.
    priority: {
      label: "Priority",
      controller: PriorityInputController,
      hidden: () => !currentBoard()?.priority,
    },
    model: {
      ...choiceInput("model", "the runner's model", "", ModelInputController),
      // Empty is the runner's model, and the field says so rather than "Select...".
      get placeholder() {
        return t("The runner's model")
      },
    },
    // « Plan d'abord », drawn only where the board has the box to tick.
    plan: {
      label: "Plan first",
      defaultValue: false,
      controller: PlanInputController,
      // The box says its own name beside it: the field's label is for the screen reader.
      className: "[&_[data-slot=field-label]]:sr-only",
      hidden: () => !currentBoard()?.plan,
    },
    // The prompt run at every change of status: written here, kept on the page.
    on: {
      label: "Automation (On)",
      defaultValue: "",
      controller: OnInputController,
    },
    // Said by the button that sends the form: "Save as draft" or "Launch the ticket".
    ready: { defaultValue: true, hidden: () => true },
  },
}

/* The status, in the table, with the robot the card wears beside it. The cell
 * holds the board's word for the column, not its key: the key is found again
 * by that word, and a status the board has no column for is a draft, as it is
 * on the board. */
const StatusCell: InputControllerComponentInterface = ({ formInput }) => {
  const status = String(formInput.value ?? "")
  const column =
    currentBoard()?.columns.find((candidate) => candidate.name === status)?.key ?? "draft"
  return (
    <span className="inline-flex items-center gap-2">
      <TicketRobot column={column} size={18} className="shrink-0" />
      {status}
    </span>
  )
}

/* The model, in the table, as `provider/model` like everywhere else: the
 * server says it, the column holds what was typed. */
const ModelCell: InputControllerComponentInterface = ({ formInput }) => {
  const original = useFormContext().form.originalData as TicketItem | undefined
  return <>{original?.model_label || String(formInput.value ?? "")}</>
}

/** A priority, as the badge the card wears: its score, in its colour. */
const PriorityCell: InputControllerComponentInterface = ({ formInput }) =>
  typeof formInput.value === "number" ? <PriorityBadge score={formInput.value} /> : null

/* The title, in the table, as the way into the ticket — the window over the
 * list, as a card's title is. */
const TitleCell: InputControllerComponentInterface = ({ formInput }) => {
  const id = String((useFormContext().form.originalData as TicketItem | undefined)?.id ?? "")
  const title = String(formInput.value ?? "")
  const words = useSearchWords()
  const open = useOpensOverTheList(tickets, "read", id)
  if (!id) return <>{title}</>
  return (
    <Link to={ticketHref(id)} onClick={open} className="font-medium hover:underline">
      <Marked text={title} words={words} />
    </Link>
  )
}

/* The columns of the table layout. Read only: a ticket is moved on the board,
 * not typed into here. The headings go through the dictionary on their way to
 * the page, and the two cells that are a number on the card — what it cost and
 * how long it took — are read from the words `item` writes them in. */
const rowForm: FormInterface = {
  inputs: {
    title: { label: "Ticket", readonly: true, controller: TitleCell },
    project: { label: "Project", readonly: true },
    status: { label: "Status", readonly: true, controller: StatusCell },
    priority: { label: "Priority", readonly: true, controller: PriorityCell },
    model: { label: "Model", readonly: true, controller: ModelCell },
    spent: { label: "Cost", readonly: true },
    took: { label: "Took", readonly: true },
    due: { label: "Scheduled", readonly: true },
  },
}

/* -- one card ------------------------------------------------------------- */

/* How a ticket is drawn on the board. The card is the way into the ticket —
 * its title is the link; a click opens it in a
 * window over the board (see `ticketWindow`).
 *
 * Read top to bottom it answers, in order: what is it, what is said about it,
 * what is it doing, where does the work go, how long has it been sitting there
 * and what has it cost. "What is it doing" is live on a
 * running card: what its session last said, as it says it. The `-m-4` is the frame
 * react-resource-view draws around every record being pushed back out of the
 * way: the coloured edge has to be the card's own edge, not a stripe inside a
 * second border.
 *
 * The age never wraps: "il y a 1 j" over two lines was a line of the card
 * spent on it. The title and the summary do, anywhere if they must: a path, a URL or a
 * branch name has no space to break at, and unbroken it set the width of the
 * whole column, which then ran under the ones beside it.
 *
 * `content-visibility: auto` is for the windows: a modal sets `pointer-events`
 * on the body, which is inherited, so every element of the page has its style
 * computed again — on opening and again on closing. With two hundred cards
 * that was 150 ms each time (`scripts/measure-console.mjs`, 446 tickets); the
 * cards a column has scrolled out of view are not computed at all. The frame
 * is the column's and the grip's, outside the card, so the paint containment
 * clips nothing. The height it falls back on is a typical card's; the browser
 * remembers the real one once a card has been seen.
 *
 * What the card draws is memoised on the ticket, the words and the way in:
 * opening a ticket writes its window into the address, which every card read,
 * and 1 800 cards drawn again held the click for a second and a half before
 * the window showed (`scripts/measure-board.mjs`). The words and the way in
 * stay the same objects for as long as they say the same thing.
 *
 * A card is also picked, for the bar that acts on several at once (see
 * `bulk-bar.tsx`): by its box, in its top corner on hover — or, on a touch
 * screen with no hover, by a long press. Once one card is picked, a click
 * anywhere on any card picks it rather than opening it or pressing its
 * buttons, and Shift picks the run of cards from the one picked last.
 */
function TicketCard({ row }: RowComponentPropsInterface) {
  const ticket = row?.data as TicketItem | undefined
  // The words of a search, marked where the card says them.
  const words = useSearchWords()
  // The ticket's window over the list, under a project's page as on the board.
  const open = useOpensOverTheList(tickets, "read", ticket?.id ?? "")
  if (!ticket) return null
  return <TicketCardBody ticket={ticket} words={words} open={open} />
}

const TicketCardBody = React.memo(function TicketCardBody({
  ticket,
  words,
  open,
}: {
  ticket: TicketItem
  words: string[]
  open: (event: React.MouseEvent<HTMLElement>) => void
}) {
  const href = ticketHref(ticket.id)
  const t = useT()
  const selected = useSelected(ticket.id)
  const selecting = useSelecting()
  const press = useLongPress(ticket.id)

  // While cards are being picked, a click is a pick, wherever it lands on the
  // card: caught on the way down, before the title's link or a button hears it.
  const onClickCapture = (event: React.MouseEvent<HTMLDivElement>) => {
    const onBox = (event.target as Element).closest("[data-slot=card-select]")
    if (press.swallow()) {
      event.preventDefault()
      event.stopPropagation()
      return
    }
    if (!onBox && !selecting) return
    event.preventDefault()
    event.stopPropagation()
    pick(ticket.id, orderAround(event.currentTarget), event.shiftKey)
  }

  return (
    <div
      data-ticket-card={ticket.id}
      data-selected={selected || undefined}
      onClickCapture={onClickCapture}
      {...press.handlers}
      className={cn(
        "group/card relative -m-4 flex min-w-0 flex-col gap-2 rounded-2xl p-3 [contain-intrinsic-size:auto_9rem] [content-visibility:auto] [-webkit-touch-callout:none] pointer-coarse:select-none",
        selected && "bg-primary/5 ring-primary ring-2 ring-inset"
      )}
    >
      {/* Picking cards is for acting on them: a reader has nothing to act with. */}
      {canAct() ? (
        <Checkbox
          data-slot="card-select"
          checked={selected}
          aria-label={t("Select “{{title}}”", { title: ticket.title })}
          tabIndex={selecting ? 0 : -1}
          className={cn(
            "bg-background absolute top-3 right-3 z-10",
            !selecting && "opacity-0 group-hover/card:opacity-100 focus-visible:opacity-100 pointer-coarse:hidden"
          )}
        />
      ) : null}
      {/* Given up on: still read, struck through, the way a list crosses out
          what it no longer means to do. */}
      <Link
        to={href}
        onClick={open}
        // Picked up, the title carries the card, not its address.
        draggable={false}
        className={cn(
          "text-[0.93rem] leading-snug font-semibold break-words hover:underline",
          selecting && "pe-6",
          ticket.column === "cancelled" && "text-muted-foreground line-through"
        )}
      >
        <Marked text={ticket.title} words={words} />
      </Link>

      <TicketTags ticket={ticket} />
      <TicketSync ticket={ticket} />
      <TicketHeld ticket={ticket} />
      {/* A blocked card says why in its Unblock button's tooltip. */}
      {ticket.column !== "blocked" ? <TicketBlock block={ticket.block} /> : null}
      {/* In review, the checks are said in the line along the bottom. */}
      {ticket.column !== "review" ? <TicketCi ci={ticket.ci} /> : null}

      {ticket.column === "running" ? (
        <CardLive ticket={ticket} />
      ) : ticket.progress ? (
        <p className="text-muted-foreground line-clamp-3 text-xs leading-relaxed break-words">
          <Marked text={ticket.progress} words={words} />
        </p>
      ) : null}
      {/* What it delivered, once it has: the first lines of its result. */}
      {ticket.excerpt && ["review", "validated", "done"].includes(ticket.column) ? (
        <p
          data-slot="card-excerpt"
          className="border-border text-foreground/80 line-clamp-3 border-l-2 pl-2 text-xs leading-relaxed whitespace-pre-line break-words"
        >
          {ticket.excerpt}
        </p>
      ) : null}

      <TicketActions ticket={ticket} className="-mx-1" />
      <TicketFoot ticket={ticket} />
    </div>
  )
})

/** The ids of the cards drawn in the column this card is in, in their order: where a Shift-click runs. */
function orderAround(card: Element): string[] {
  const column = card.closest("[data-board-column]")
  if (!column) return []
  return Array.from(column.querySelectorAll("[data-ticket-card]"), (one) => one.getAttribute("data-ticket-card") ?? "")
}

/* A long press picks a card, on a touch screen — the one gesture a phone has
 * for « this one, not open it ». A finger that moves is scrolling, and lets go
 * of it. The click the browser may send when the finger lifts is swallowed:
 * the card was just picked, not opened. */
const LONG_PRESS = 450

function useLongPress(id: string) {
  const timer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const start = React.useRef<{ x: number; y: number } | null>(null)
  const fired = React.useRef(false)
  const stop = () => {
    clearTimeout(timer.current)
    start.current = null
  }
  React.useEffect(() => () => clearTimeout(timer.current), [])
  return {
    swallow: () => {
      const was = fired.current
      fired.current = false
      return was
    },
    handlers: {
      onPointerDown: (event: React.PointerEvent<HTMLDivElement>) => {
        fired.current = false
        if (event.pointerType === "mouse") return
        const card = event.currentTarget
        start.current = { x: event.clientX, y: event.clientY }
        clearTimeout(timer.current)
        timer.current = setTimeout(() => {
          fired.current = true
          start.current = null
          pick(id, orderAround(card))
          navigator.vibrate?.(10)
        }, LONG_PRESS)
      },
      onPointerMove: (event: React.PointerEvent<HTMLDivElement>) => {
        const from = start.current
        if (from && Math.hypot(event.clientX - from.x, event.clientY - from.y) > 10) stop()
      },
      onPointerUp: stop,
      onPointerCancel: stop,
      // The menu a long press opens on a link would cover the card just picked.
      onContextMenu: (event: React.MouseEvent<HTMLDivElement>) => {
        if (fired.current) event.preventDefault()
      },
    },
  }
}

/* -- the board ------------------------------------------------------------ */

/* What sits above whatever react-resource-view is drawing.
 *
 * It asks the list to reread the store whenever the stream moves the board,
 * and once the board is there it draws the runner's figures over it, then the
 * statistics of the period — which is what makes the list a dashboard. The heading is the
 * package's own since 0.7.0 — the resource's icon, the view's name and the
 * line under it — so the board no longer opens with a `PageHead` of its own,
 * which would say it all twice.
 *
 * Until the first board arrives, it is the page: the package covers the screen
 * with three bouncing dots while the list loads, and the first thing a console
 * shows is that wait — as long as the board takes to answer. The robot, thinking,
 * over the dots, says the same thing with the runner's own face.
 */
function BoardTop() {
  const { fetchData, isLoading, resourceAction, parentResource } = useCurrentViewResourceContext()
  const embedded = Boolean(parentResource) && resourceAction === ActionList.list
  // Asked of the store, not read once: nothing above this draws again when the
  // first board arrives.
  const held = React.useSyncExternalStore(subscribeBoard, () => currentBoard() !== null)
  return embedded ? (
    <EmbeddedTop />
  ) : (
    <DashboardTop
      fetchData={fetchData}
      loading={isLoading && !held}
      listing={resourceAction === ActionList.list}
    />
  )
}

/** The same list drawn inside another page: reread when the stream moves, and none of the dashboard's figures. */
function EmbeddedTop() {
  const { fetchData } = useCurrentViewResourceContext()
  useRememberedLayout(TICKETS)
  const latest = React.useRef(fetchData)
  latest.current = fetchData
  React.useEffect(() => subscribeBoard(() => latest.current()), [])
  return null
}

function DashboardTop({
  fetchData,
  loading,
  listing,
}: {
  fetchData: () => void
  loading: boolean
  listing: boolean
}) {
  useLayoutInTheAddress(TICKETS)
  const latest = React.useRef(fetchData)
  latest.current = fetchData
  React.useEffect(() => subscribeBoard(() => latest.current()), [])
  // On a phone the dashboard opens on what waits for you, before the health
  // band and the figures (see `to-handle.tsx`).
  const phone = usePhone()
  // The figures are the board's: a ticket's page is drawn under the same
  // `top`, and has its own column to say what it is doing.
  if (!loading)
    return listing ? (
      <>
        {phone ? <ToHandle /> : null}
        <HealthBand />
        <RunnerStrip action={<IdeasButton inline />} />
        <StatisticsBand />
      </>
    ) : null
  return (
    <div className="bg-background fixed inset-0 z-[51] flex flex-col items-center justify-center gap-3">
      <Robot state="thinking" size={96} />
      <p className="text-muted-foreground font-mono text-xs">{t("Reading the board…")}</p>
    </div>
  )
}

/* The board's own empty line.
 *
 * Left to the package, a board with nothing on it said "No results yet —
 * nothing matched your search", in English, on a console set to French and on a
 * page where nobody has searched for anything. An empty board is not a failed
 * search: it is a board waiting for its first ticket, and the button that makes
 * one is already at the top of the page. */
function NoTicket() {
  return (
    <EmptyState robot="sleep">
      {t("Nothing on the board yet — a ticket moved to the ready column is a session that starts.")}
    </EmptyState>
  )
}

/** The empty line under a project: the board may be full, it is this project that has nothing. */
function NoProjectTicket() {
  return <EmptyState robot="sleep">{t("No ticket points at this project yet.")}</EmptyState>
}

/** A column's name as a heading: the board's own word, with a capital, under its colour.
 *
 * With the number of its cards when there is one to say. The package counts
 * the cards it is handed, and a column that is handed its thirty latest is not
 * a column of thirty: the count is the column's own, drawn here, and the
 * package's is hidden (see `BoardColumn`). While a search is on, it says how
 * many of them it kept, out of how many: "3 / 12". On the board, Blocked and
 * In review end on the way through all of their cards at once — see
 * `SeriesButton`.
 *
 * In progress is read against the places the runner has — `places`, its
 * `max_concurrent` — as "5/5", and goes amber when the queue is full. A search
 * does not change how full the runner is, so that figure is never the kept one. */
function heading(
  key: string,
  name: string,
  count?: number,
  total?: number,
  series = false,
  places?: number,
  select?: React.ReactNode
) {
  const filled = total ?? count
  const full = filled !== undefined && places !== undefined && key === "running"
  return (
    <span className="flex items-center gap-2">
      {select}
      <span className={cn("size-1.5 shrink-0 rounded-full", SEED[key] ?? "bg-muted-foreground")} />
      <span className="truncate">{capital(name)}</span>
      {count === undefined && !full ? null : (
        <span
          className={cn(
            "bg-background ms-auto shrink-0 rounded-full px-2 py-0.5 text-xs font-normal tabular-nums",
            full && filled >= places ? "text-tr-amber" : "text-muted-foreground"
          )}
        >
          {full ? `${filled}/${places}` : total === undefined ? count : `${count} / ${total}`}
        </span>
      )}
      {series && (key === "blocked" || key === "review" || key === "draft") ? <SeriesButton column={key} /> : null}
    </span>
  )
}

/* The columns where cards only ever pile up, and how many of their latest are
 * drawn at a time.
 *
 * Done grows by every ticket the runner has ever finished: 344 cards on the
 * board of September 2026, each with its robot, all drawn every time somebody
 * went to the board — the browser held for a third of a second on a slow
 * machine (`scripts/measure-console.mjs`). Nobody reads the three hundredth card of
 * Done; the most recent are the ones worth a look. So a terminal column draws
 * its `TERMINAL_PAGE` latest — by when the ticket was last touched, which is
 * when it got there — and a button under it draws that many more.
 *
 * Every other column is work in flight, in the order the queue takes it, and
 * draws its first `WORK_PAGE` the same way. A board of 1 800 tickets — 700 of
 * them drafts — drawn whole had every one of its cards drawn again when a
 * ticket's window opened over it: the click held for 300 ms after everything
 * else had been made cheaper (`scripts/measure-board.mjs`). A card dropped in
 * a column is drawn whatever its rank, or a card dragged into Ready behind
 * five hundred others would be dropped out of sight.
 *
 * What a search keeps is what is counted: the rows are the ones it left, so a
 * search that finds an old ticket finds it among thirty, not behind three
 * hundred. */
const TERMINAL = new Set<string>(["done", "cancelled"])
export const TERMINAL_PAGE = 30
const WORK_PAGE = 50

/* How far each column was opened, for as long as the tab lives: going to a
 * ticket and back to the board is not starting again from the first page. */
const opened = new Map<string, number>()

const touched = (row: RowInterface) => Date.parse(String(row.data?.edited ?? "")) || 0

/** One column of the board, as the package draws it — cut short, with the way to the rest. */
function BoardColumn({
  column,
  label,
  rows,
  total,
  series,
  places,
  dragging,
  onDragging,
}: {
  column: string
  label: string
  rows: RowInterface[]
  /** How many the column holds, search or not — said only while one is on. */
  total?: number
  /** The board's own columns, not a project's: they offer to go through their cards. */
  series: boolean
  /** How many tickets the runner takes at once — the board's, so only on the board. */
  places?: number
  dragging: boolean
  onDragging: (dragging: boolean) => void
}) {
  const page = TERMINAL.has(column) ? TERMINAL_PAGE : WORK_PAGE
  const [shown, setShown] = React.useState(() => opened.get(column) ?? page)
  // The tickets dropped here since the board was opened, by id.
  const [dropped, setDropped] = React.useState<ReadonlySet<string>>(() => new Set())
  const mine = React.useMemo(() => {
    const own = rows.filter((row) => row.data?.column === column)
    return TERMINAL.has(column) ? own.sort((a, b) => touched(b) - touched(a)) : own
  }, [rows, column])
  const drawn = mine.filter((row, index) => index < shown || dropped.has(String(row.data?.id)))
  const left = mine.length - drawn.length
  const ids = drawn.map((row) => String(row.data?.id))
  const selection = useSelection()
  const state = columnState(ids, selection)
  // The column's box picks every card it draws — those a search kept, and no
  // more than the page shown. Next to its name while cards are being picked,
  // on hover otherwise.
  const select = ids.length && canAct() ? (
    <Checkbox
      data-slot="column-select"
      checked={state}
      onCheckedChange={() => pickAll(ids)}
      aria-label={t("Select the column “{{column}}”", { column: capital(label) })}
      className={cn(
        "bg-background",
        !selection.size && "opacity-0 group-hover/column:opacity-100 focus-visible:opacity-100 pointer-coarse:hidden"
      )}
    />
  ) : null
  // The package's column finds the card dropped on it among the rows it is
  // handed, and draws only those of its own column: handed the others too, a
  // card carried from another column is one it knows.
  const carried = [...rows.filter((row) => row.data?.column !== column), ...drawn]

  const more = () => {
    const next = shown + page
    opened.set(column, next)
    setShown(next)
  }

  // The package's column writes the drop; this only remembers which card it was.
  const keepDropped = (event: React.DragEvent) => {
    const id = event.dataTransfer.getData("text")
    if (id && !dropped.has(id)) setDropped(new Set(dropped).add(id))
  }

  // The package draws its column 18rem wide and rigid; the wrapper is what
  // shares the width, and the column fills it — no wider: left at
  // `min-width: auto`, its widest card would widen it. Its own count is
  // hidden: it counts what it was handed, and the heading says the column's.
  return (
    <div
      onDrop={keepDropped}
      data-board-column={column}
      className={cn(
        "group/column flex flex-1 basis-0 snap-start flex-col gap-2 *:w-auto *:min-w-0 [&_header>p]:flex-1 [&_header>span]:hidden",
        // Alone on a phone's screen, it takes the width there is.
        "max-md:min-w-0",
        COLUMN_MIN
      )}
    >
      <RowWrapperColumnComponent
        identifierKey="column"
        valueIdentifier={{
          value: column,
          label: heading(column, label, mine.length, total, series, places, select),
        }}
        isDragging={dragging}
        handleDragging={onDragging}
        rows={carried}
      />
      {left > 0 ? (
        <Button variant="outline" size="sm" onClick={more}>
          {t("Show more ({{count}} left)", { count: String(left) })}
        </Button>
      ) : null}
    </div>
  )
}

/* The narrowest a column is drawn: wide enough for a card's badge and its
 * date to share a line. Below it a card's title wraps a word to a line; above it the columns share the width, with no upper bound, and past
 * what the screen holds the board scrolls sideways — the board, not the page. */
const COLUMN_MIN = "min-w-[21rem]"

/* The column a phone's board was last left on, for as long as the tab lives:
 * opening a ticket and coming back is not starting again from Blocked. */
let chosenColumn: string | undefined

/* The board on a phone: one column at a time, chosen from a row of tabs, each
 * with how many cards it holds — « Bloqué 3 · En revue 2 ». Seven columns side
 * by side, each 21rem wide, were six swipes across, and Blocked was the fourth.
 * The row scrolls sideways when the names do not fit; the column chosen is the
 * one drawn, full width. It opens on Blocked, then In review — what waits for
 * you — or on the one picked last (`openingColumn`). */
function PhoneTabs({
  columns,
  shown,
  onChoose,
}: {
  columns: { key: string; name: string; count: number }[]
  shown: string
  onChoose: (key: string) => void
}) {
  const t = useT()
  const row = React.useRef<HTMLDivElement>(null)
  // The tab on show is brought into the row's view — Blocked, fourth, opened
  // out of sight — by scrolling the row alone: `scrollIntoView` would move the
  // page down to the board as well.
  React.useLayoutEffect(() => {
    const element = row.current
    const tab = element?.querySelector<HTMLElement>(`[data-board-tab="${shown}"]`)
    if (!element || !tab) return
    element.scrollLeft = tab.offsetLeft - element.offsetLeft - (element.clientWidth - tab.offsetWidth) / 2
  }, [shown])
  if (columns.length < 2) return null
  return (
    <div
      ref={row}
      role="tablist"
      aria-label={t("Columns of the board")}
      data-slot="board-tabs"
      className="scroll-thin -mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1"
    >
      {columns.map((column) => {
        const on = column.key === shown
        return (
          <button
            key={column.key}
            type="button"
            role="tab"
            aria-selected={on}
            data-board-tab={column.key}
            onClick={() => onChoose(column.key)}
            className={cn(
              "focus-visible:ring-ring/50 flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-sm whitespace-nowrap outline-none focus-visible:ring-2",
              on ? "bg-foreground text-background border-transparent" : "text-muted-foreground bg-card"
            )}
          >
            <span className={cn("size-1.5 shrink-0 rounded-full", SEED[column.key] ?? "bg-muted-foreground")} />
            {capital(column.name)}
            <span className="tabular-nums opacity-70">{column.count}</span>
          </button>
        )
      })}
    </div>
  )
}

/* Whether the empty columns are drawn anyway, as the last person at this
 * browser left it. Hidden by default: on a board with three columns at "rien",
 * those three took as much room as the ones with work in them. */
const EMPTY_KEY = "ponos-board-empty-columns"

function useEmptyColumnsShown() {
  const [shown, setShown] = React.useState(() => {
    try {
      return localStorage.getItem(EMPTY_KEY) === "shown"
    } catch {
      return false
    }
  })
  const change = React.useCallback((next: boolean) => {
    setShown(next)
    try {
      localStorage.setItem(EMPTY_KEY, next ? "shown" : "hidden")
    } catch {
      // Storage off: the choice lasts as long as the tab, which is still one.
    }
  }, [])
  return [shown, change] as const
}

/* A hidden column, while a card is being dragged: a thin strip under its name
 * that takes a drop the way a column does. Without it, hiding an empty column
 * would have taken away the only way to move a card to Review or Blocked by
 * hand. The drop is the one the package's column makes — the same
 * `updateData`, so the same write — and the column is drawn again as soon as
 * the card is in it, because it is no longer empty. */
function DropZone({
  column,
  label,
  onDropped,
}: {
  column: string
  label: React.ReactNode
  onDropped: () => void
}) {
  const list = useListViewContext()
  const [over, setOver] = React.useState(false)
  return (
    <div
      onDragOver={(event) => {
        event.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault()
        setOver(false)
        const id = event.dataTransfer.getData("text")
        if (id) list.updateData?.({ id, column }, true)
        onDropped()
      }}
      className={cn(
        "border-border bg-muted/30 flex min-h-40 w-10 shrink-0 snap-start justify-center self-stretch rounded-2xl border border-dashed py-3 text-xs font-medium transition-colors",
        over && "border-primary bg-primary/5 w-24"
      )}
    >
      <span className="[writing-mode:vertical-rl]">{label}</span>
    </div>
  )
}

/** The board's columns, in the board's order and words, each a drop target.
 *
 * Seven columns do not fit a laptop, and the board used to show four of them
 * with nothing to say there were three more. The columns share the width of
 * the page now, none narrower than `COLUMN_MIN`, the strip snaps to a
 * column's edge, and each end that has more beyond it says so — a fade, and a
 * button that scrolls one screen further.
 *
 * A column with no card is not drawn, unless you asked for it: a line over the
 * board says how many are hidden and brings them back. While a card is being
 * dragged, each hidden column is a thin drop zone in its place.
 *
 * The search bar is over them (see `TicketSearch`). A search hides cards, not
 * columns: a column with tickets stays where it was, saying how many of them
 * the search kept — it would otherwise be a board whose columns move at every
 * letter typed. */
function BoardColumns({ rows: all = [] }: ListComponentPropsInterface) {
  const board = useBoard()
  const { kept: rows, filtering } = useTicketFilter(all)
  const everyTicket = React.useMemo(() => all.map((row) => row.data as Ticket), [all])
  const { resource } = useCurrentViewResourceContext()
  const [dragging, setDragging] = React.useState(false)
  const [emptyShown, setEmptyShown] = useEmptyColumnsShown()
  const strip = React.useRef<HTMLDivElement>(null)
  const [more, setMore] = React.useState({ left: false, right: false })
  const selecting = useSelecting()
  // What was picked is the board's: left, the board forgets it.
  React.useEffect(() => clearSelection, [])

  const measure = React.useCallback(() => {
    const element = strip.current
    if (!element) return
    const left = element.scrollLeft > 4
    const right = element.scrollLeft + element.clientWidth < element.scrollWidth - 4
    setMore((was) => (was.left === left && was.right === right ? was : { left, right }))
  }, [])

  const columns = board.columns.filter(
    // Offered only where the runner would honour a card dropped there, and
    // where the board has the option a cancelled card is written with.
    (column) =>
      (column.key !== "validated" || board.validate) && (column.key !== "cancelled" || board.cancel)
  )
  // Counted on every row, whatever the search keeps: a column emptied by a
  // search is not an empty column, and is not folded away.
  const empty = new Set(
    columns
      .filter((column) => !all.some((row) => row.data?.column === column.key))
      .map((column) => column.key)
  )
  const totals = (key: string) =>
    filtering ? all.filter((row) => row.data?.column === key).length : undefined
  const hidden = emptyShown ? 0 : empty.size

  React.useEffect(() => {
    const element = strip.current
    if (!element) return
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    for (const child of Array.from(element.children)) observer.observe(child)
    return () => observer.disconnect()
  }, [measure, board.columns.length, rows.length, hidden, dragging])

  const scroll = (direction: 1 | -1) =>
    strip.current?.scrollBy({ left: direction * strip.current.clientWidth * 0.8, behavior: "smooth" })

  // On a phone, one column at a time, under tabs that count their cards.
  const phone = usePhone()
  const drawnColumns = columns.filter((column) => emptyShown || !empty.has(column.key))
  const [chosen, setChosen] = React.useState(() => chosenColumn)
  const shownColumn = openingColumn(
    drawnColumns.map((column) => column.key),
    new Set(columns.filter((column) => !empty.has(column.key)).map((column) => column.key)),
    chosen
  )
  const choose = (key: string) => {
    chosenColumn = key
    setChosen(key)
  }

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <TicketSearch
        tickets={everyTicket}
        shown={rows.length}
        projects={resource["@id"] !== PROJECT_TICKETS}
      />
      {filtering && !rows.length ? <NoMatch /> : null}
      {empty.size ? (
        <p className="text-muted-foreground flex items-center justify-end gap-1 text-xs">
          {emptyShown
            ? null
            : counted(empty.size, "{{count}} empty column hidden", "{{count}} empty columns hidden")}
          <Button variant="ghost" size="xs" onClick={() => setEmptyShown(!emptyShown)}>
            {emptyShown ? t("Hide empty columns") : t("Show them")}
          </Button>
        </p>
      ) : null}
      {phone ? (
        <PhoneTabs
          columns={drawnColumns.map((column) => ({
            key: column.key,
            name: columnTitle(column.key, column.name),
            count: rows.filter((row) => row.data?.column === column.key).length,
          }))}
          shown={shownColumn}
          onChoose={choose}
        />
      ) : null}
      <div className={cn("relative", filtering && !rows.length && "hidden")}>
        <div
          ref={strip}
          onScroll={measure}
          className="scroll-thin flex snap-x snap-mandatory items-start gap-3 overflow-x-auto scroll-smooth pb-2"
        >
          {columns.map((column) => {
            const name = columnTitle(column.key, column.name)
            // A phone draws the column its tabs are on, and none of the others.
            if (phone && column.key !== shownColumn) return null
            if (!emptyShown && empty.has(column.key)) {
              return dragging ? (
                <DropZone
                  key={column.key}
                  column={column.key}
                  label={heading(column.key, name)}
                  onDropped={() => setDragging(false)}
                />
              ) : null
            }
            return (
              <BoardColumn
                key={column.key}
                column={column.key}
                label={name}
                rows={rows}
                total={totals(column.key)}
                series={resource["@id"] !== PROJECT_TICKETS}
                places={resource["@id"] !== PROJECT_TICKETS ? board.places : undefined}
                dragging={dragging}
                onDragging={setDragging}
              />
            )
          })}
        </div>
        {more.left ? (
          <div className="from-background pointer-events-none absolute inset-y-0 left-0 flex w-12 items-start bg-gradient-to-r to-transparent pt-1">
            <Button
              variant="outline"
              size="icon-sm"
              className="pointer-events-auto rounded-full shadow-sm"
              aria-label={t("Earlier columns")}
              onClick={() => scroll(-1)}
            >
              <ChevronLeft />
            </Button>
          </div>
        ) : null}
        {more.right ? (
          <div className="from-background pointer-events-none absolute inset-y-0 right-0 flex w-12 items-start justify-end bg-gradient-to-l to-transparent pt-1">
            <Button
              variant="outline"
              size="icon-sm"
              className="pointer-events-auto rounded-full shadow-sm"
              aria-label={t("More columns")}
              onClick={() => scroll(1)}
            >
              <ChevronRight />
            </Button>
          </div>
        ) : null}
      </div>
      {selecting && canAct() ? (
        <React.Suspense fallback={null}>
          <LazyBulkBar />
        </React.Suspense>
      ) : null}
    </div>
  )
}

/* The bar that acts on the cards picked, fetched with the first one (see `bulk-bar.tsx`). */
const LazyBulkBar = React.lazy(() =>
  import("@/components/console/bulk-bar").then((module) => ({ default: module.BulkBar }))
)

/* The table, under the same search bar as the board: the package's own table,
 * handed the rows the search keeps. */
function TicketTable({ rows: all = [] }: ListComponentPropsInterface) {
  const { kept, filtering } = useTicketFilter(all)
  const everyTicket = React.useMemo(() => all.map((row) => row.data as Ticket), [all])
  const { resource } = useCurrentViewResourceContext()
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <TicketSearch
        tickets={everyTicket}
        shown={kept.length}
        projects={resource["@id"] !== PROJECT_TICKETS}
      />
      {filtering && !kept.length ? <NoMatch /> : <ListTable rows={kept} />}
    </div>
  )
}

/* The projects the form offered last, by id: the provisional card of a ticket
 * being created names its project from here, not from a read it would wait for. */
const knownProjects = new Map<string, { name: string; kind: string }>()

let provisionals = 0

/** A new ticket, drawn on the board at once under a provisional id, and written behind it: the real card replaces it when the server answers, and it is taken off when the server refuses. */
export async function createTicket(fresh: TicketWrite): Promise<TicketItem> {
  const title = String(fresh.title ?? "").trim()
  // Said under the field it is about, not only in a toast in the corner.
  if (!title) throw new FieldProblem("title", t("A ticket needs a title."))
  const score = readScore(fresh.priority)
  if (score === undefined) throw new FieldProblem("priority", t("A priority is a number from 0 to 100."))
  const project = knownProjects.get(String(fresh.project ?? ""))
  // A draft lands among the drafts, with the status the board keeps them
  // under, or none on a board that names no such option.
  const drafts = currentBoard()?.columns.find((candidate) => candidate.key === "draft")
  const column = fresh.ready === false ? "draft" : "ready"
  const now = new Date().toISOString()
  const card: Ticket = {
    id: `pending${++provisionals}`,
    short: "",
    title,
    url: "",
    status: column === "draft" ? drafts?.name ?? "" : "",
    column,
    project: project?.name ?? "",
    kind: project?.kind ?? "",
    // The key was sent; the card says it as the board spells it.
    type: currentBoard()?.choices?.type?.find((choice) => choice.value === fresh.type)?.label ?? "",
    subtype: String(fresh.subtype ?? ""),
    goal: currentBoard()?.choices?.goal?.find((choice) => choice.value === fresh.goal)?.label ?? "",
    goal_id: String(fresh.goal ?? ""),
    // What the server will write: the score given, or the middle one.
    priority: currentBoard()?.priority ? (score ?? DEFAULT_SCORE) : null,
    model: String(fresh.model ?? ""),
    progress: "",
    runner: "",
    pull_request: "",
    session: "",
    session_link: "",
    cost: null,
    duration: null,
    scheduled: "",
    created: now,
    edited: now,
  }
  void optimistic({
    apply: () => addTicket(card),
    request: () =>
      api.createTicket({
        title,
        body: String(fresh.body ?? ""),
        project: String(fresh.project ?? ""),
        ready: fresh.ready !== false,
        priority: score ?? "",
        type: String(fresh.type ?? ""),
        model: String(fresh.model ?? ""),
        subtype: String(fresh.subtype ?? ""),
        goal: String(fresh.goal ?? ""),
        plan: fresh.plan === true,
        on: String(fresh.on ?? ""),
      }),
    rollback: () => dropTicket(card.id),
    failure: t("The ticket could not be created"),
    // The stream may have brought the real card already: it is then the only one left.
    settled: (made) => {
      const id = made.id.replace(/-/g, "")
      replaceTicket(card.id, { ...card, id, short: id.slice(-8), title: made.title })
    },
  })
  return item(card)
}

/* -- the tickets of one project ------------------------------------------- */

/* The same list, under a project's page. It is this resource declared again
 * (see `declare` below) with what only a project's tickets change: the project
 * is the page's, so it is neither a column nor a choice, and the table says
 * what a ticket is and when it moved rather than who runs it. */

/** The id, as a card writes it. */
const IdCell: InputControllerComponentInterface = ({ formInput }) => (
  <span className="text-muted-foreground font-mono text-xs">#{String(formInput.value ?? "")}</span>
)

const shared = rowForm.inputs ?? {}

const projectRowForm: FormInterface = {
  inputs: {
    short: { label: "Id", readonly: true, controller: IdCell },
    title: shared.title,
    status: shared.status,
    priority: shared.priority,
    type: { label: "Type", readonly: true },
    spent: shared.spent,
    changed: { label: "Last modified", readonly: true },
  },
}

/* Which tickets a list is about: all of them, or a project's. The search over
 * them is the bar's (see `TicketSearch`), done on the rows this hands over —
 * which is why it hands them all over: a column says "3 / 12", and needs the
 * twelve. */
function matches(ticket: Ticket, filter: Record<string, unknown> = {}): boolean {
  const project = String(filter.project ?? "").trim()
  return !project || ticket.project === project
}

/* -- the declaration ------------------------------------------------------ */

/* What the board's list is, apart from which tickets it holds and how its
 * table reads: said once, for the board and for a project's tickets. */

/* A ticket's page and its head: drawn once a ticket is opened, and fetched
 * then — the board is the first page, and its first load has a budget. */
const LazyTicketPage = React.lazy(() =>
  import("@/components/console/ticket-page").then((module) => ({ default: module.TicketPage }))
)
const LazyTicketHead = React.lazy(() =>
  import("@/components/console/ticket-page").then((module) => ({ default: module.TicketHead }))
)

const TicketPage = () => (
  <React.Suspense fallback={null}>
    <LazyTicketPage />
  </React.Suspense>
)

const TicketHead = () => (
  <React.Suspense fallback={null}>
    <LazyTicketHead />
  </React.Suspense>
)
const viewsOf = (form: FormInterface, empty: React.FC): ResourceDefinition<TicketItem, TicketWrite>["views"] => ({
  list: {
    // The page is the Dashboard everywhere else — the menu, the bar — so the
    // section under its figures is the board, not the same word a third time.
    title: "Board",
    // The resource's name and the line under it are what the list's own header
    // says, next to its icon: the board opens on its own words. What the board
    // is, without naming where it is kept.
    description: "Your board, live. Drop a card in another column and the runner is told.",
    form,
    /* The two tabs over the list. Their labels go through the dictionary as
     * the tabs are drawn, and their address is their type: `board`, `table`,
     * in every language. */
    layouts: [
      layout.board({
        label: "Board",
        // The page's whole width, for the board and the table alike: switching
        // between them must not move the page. The forms keep the column every
        // other page is drawn in.
        fullWidth: true,
        groupBy: "column",
        // The board's own columns, drawn by `BoardColumns` from the board the
        // stream holds rather than declared here.
        columns: [],
        components: { list: BoardColumns, row: TicketCard },
      }),
      layout.table({ label: "List", fullWidth: true, components: { list: TicketTable } }),
    ],
    // A row of the table opens the ticket by its title, as a card does, in
    // the window over the list (see `TitleCell`). The package's own read
    // button would have been a second way in.
    rowActions: [],
    components: { empty },
  },
  create: {
    title: "New ticket",
    form: createForm,
    // Over the board rather than instead of it, and in the middle of it: a
    // handful of fields are a question asked, not a page to settle into. The dialog is
    // already as wide as a brief wants and scrolls inside when one runs long.
    open: "dialog",
  },
  read: {
    title: "Ticket",
    // Over the list it was opened from, in the console's own window (see
    // `ticket-window.tsx`); its address alone is the ticket's page.
    open: ticketWindow,
    // The layout's header, in the same shapes but written for a ticket: its
    // short id, its whole title.
    components: { view: TicketPage, navigation: TicketHead },
  },
})

const options: ResourceDefinition<TicketItem, TicketWrite> = {
  name: "Dashboard",
  path: "/api/board",
  icon: LayoutGrid,
  // Nothing is deleted from here. `update` stays allowed: the package
  // makes a card draggable, and writes its drop, only where a ticket may be
  // updated. There is no form to edit one with (no `update` view): moving a
  // card is the only update the board makes (see `updateItem`).
  permissions: { delete: false, export: false, ...readOnly() },

  repository: {
    // The rows are the stream's; reading the board again here would be asking
    // for what every open tab already holds.
    getCollection: async (filter) => {
      const board = await boardOnce()
      return {
        data: createResourceCollection({
          id: "/api/board",
          items: board.tickets.filter((ticket) => matches(ticket, filter)).map(item),
        }),
      } as never
    },
    // What the board already knows, at once: the title, the column, the
    // project and the cost are on the card, and the page draws them without
    // waiting for the server. The brief is the page's to read (see `readTicket`).
    // A ticket the board does not hold — an address typed before the board
    // arrived — is read whole, and that read is the one the page uses; what
    // the server said when it fails is the page's to say (`loadError`).
    getItem: async ({ id }) => {
      const wanted = String(id).replace(/-/g, "")
      const row = currentBoard()?.tickets.find((ticket) => ticket.id === wanted)
      if (row) return { data: item(row) }
      return { data: item(await readTicket(wanted)) }
    },
    // A card dropped in a column is a status change, and nothing else about a
    // ticket is written from the board. The same move the buttons on a card
    // make, put back where it was if the write fails.
    updateItem: async (patch) => {
      const id = String(patch.id)
      const column = patch.column as ColumnKey | undefined
      const before = currentBoard()?.tickets.find((ticket) => ticket.id === id)
      if (column) moveTicket(id, column)
      const after = currentBoard()?.tickets.find((ticket) => ticket.id === id) ?? before
      return { data: after ? item(after) : (patch as unknown as TicketItem) }
    },
    createItem: async (fresh) => ({ data: await createTicket(fresh) }),
    removeItem: async () => {
      throw new Error("a ticket is not deleted from the console")
    },
  },

  // Over every view of a ticket — the list, its page, the window and the
  // dialog: it rereads the board whenever the stream moves it.
  components: { top: BoardTop },
  views: viewsOf(rowForm, NoTicket),
}

export const tickets = createViewResource<TicketItem, TicketWrite>(TICKETS, options)

/* The same tickets under a project's page: this declaration, with the table
 * of `projectRowForm`, the search bar without its project filter, and an empty line
 * that speaks of the project rather than of the board. Not a copy of the
 * options: a column, a card or a way of moving one is changed in one place. */
export const PROJECT_TICKETS = "project-tickets"

export const projectTickets = createViewResource<TicketItem, TicketWrite>(PROJECT_TICKETS, {
  ...options,
  views: viewsOf(projectRowForm, NoProjectTicket),
})

/** Where the board is, in the layout it was last worked in. */
export const boardHref = () =>
  generateLinkByResource({
    resource: tickets,
    resourceAction: ActionList.list,
    viewVariantId: layoutOf(TICKETS),
  })

/** Where a ticket is. */
export const ticketHref = (id: string) =>
  generateLinkByResource({ resource: tickets, resourceAction: ActionList.read, id })
