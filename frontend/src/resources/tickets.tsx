import * as React from "react"
import { ChevronLeft, ChevronRight, LayoutGrid } from "lucide-react"
import {
  ActionList,
  SelectInputController,
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
  NewTicketFields,
  NewTicketFoot,
  PillsInputController,
  ProjectInputController,
  SegmentedInputController,
} from "@/components/console/new-ticket-lazy"
import { EmptyState } from "@/components/console/empty-state"
import { ProjectThumb } from "@/components/console/project-picture"
import { Robot, TicketRobot } from "@/components/console/robot"
import { RunnerStrip } from "@/components/console/runner-strip"
import { StatisticsBand } from "@/components/console/statistics"
import { CardLive } from "@/components/console/session-log"
import { TicketHead, TicketPage } from "@/components/console/ticket-page"
import { useOpensOverTheList } from "@/components/console/record-window"
import { ticketWindow } from "@/components/console/ticket-window"
import {
  Marked,
  NoMatch,
  TicketSearch,
  useSearchWords,
  useTicketFilter,
} from "@/components/console/ticket-search"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import {
  addTicket,
  boardOnce,
  currentBoard,
  moveTicket,
  subscribeBoard,
  titleOf,
  useBoard,
} from "@/lib/board-store"
import { counted, t } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import { layoutOf, useLayoutInTheAddress, useRememberedLayout } from "@/lib/resource-view"
import type { ColumnKey, Ticket, TicketDetail } from "@/lib/types"
import { cn } from "@/lib/utils"

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
 * Reading it is the slow part of opening a ticket — the server asks Notion for
 * every block — and the package asks for the record again every time the
 * stream moves the board, so one opening sent the same request two or three
 * times. The read is kept, promise and all, for as long as the page is open:
 * asked again for the same ticket it is the same read, unless the board says
 * the ticket was edited since. Leaving the page lets go of it, so the next
 * opening reads a brief changed in Notion. */
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
      () => {
        // A failed read is not kept: "Try again" has to try.
        if (held === reading) held = null
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
  priority?: string
  type?: string
  model?: string
  subtype?: string
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

/* The four a board may or may not have a column for: priority, type,
 * sub-type, model. Drawn only where it has one — a value for a missing column
 * would be dropped on its way in — and always optional. The options are the
 * board's (see `Api._choices`): read from the board the console already holds,
 * which is there before a dialog over it can open. The empty one comes first,
 * and says in its tooltip what empty means. */
function choiceInput(
  key: "priority" | "type" | "model" | "subtype",
  empty: string,
  meaning: string,
  controller: InputControllerComponentInterface
) {
  return {
    label: { type: "Type", priority: "Priority", model: "Model", subtype: "Sub-type" }[key],
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
        : // The type and the priority in the console's language (`choiceWord`),
          // their values the board's.
          (currentBoard()?.choices?.[key] ?? []).map((choice) =>
            key === "model" ? choice : { ...choice, label: choiceWord(choice.label) }
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
      getValueOptions: async () => {
        const { projects } = await api.projects().catch(() => ({ projects: [] }))
        return [
          { value: "", label: "no project — a document" },
          // The kind said the way the rest of the console says it: the list of
          // projects says "code work", and this said "code".
          // Behind the project's mark, as the list draws it: the label is
          // drawn as it is given, an element as well as a sentence.
          ...projects.map((project) => ({
            value: project.id,
            label: (
              <span className="inline-flex min-w-0 items-center gap-2">
                <ProjectThumb project={project} className="size-5 rounded" />
                {`${project.name} — ${project.kind === "code" ? t("code work") : t("document work")}`}
              </span>
            ),
          })),
        ]
      },
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
    priority: choiceInput(
      "priority",
      "None",
      "Which ready ticket goes first. Empty, it waits its turn.",
      SegmentedInputController
    ),
    // On one line: label, then the select.
    model: {
      ...choiceInput("model", "the runner's model", "", SelectInputController),
      // Empty is the runner's model, and the select says so rather than "Select…".
      get placeholder() {
        return t("the runner's model")
      },
      className:
        "[&>[data-slot=field]]:grid [&>[data-slot=field]]:grid-cols-[auto_minmax(0,1fr)] [&>[data-slot=field]]:items-center [&>[data-slot=field]]:gap-3 [&_[data-slot=field-label]]:mb-0 [&_[data-slot=select-trigger]]:h-8 [&_[data-slot=select-trigger]]:w-full",
    },
    // Said by the button that sends the form: "Draft" or "Launch the ticket".
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

/** A priority, in the console's words rather than the board's: see `choiceWord`. */
const PriorityCell: InputControllerComponentInterface = ({ formInput }) => (
  <>{choiceWord(String(formInput.value ?? ""))}</>
)

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
 */
function TicketCard({ row }: RowComponentPropsInterface) {
  const ticket = row?.data as TicketItem | undefined
  // The words of a search, marked where the card says them.
  const words = useSearchWords()
  // The ticket's window over the list, under a project's page as on the board.
  const open = useOpensOverTheList(tickets, "read", ticket?.id ?? "")
  if (!ticket) return null
  const href = ticketHref(ticket.id)

  return (
    <div
      data-ticket-card={ticket.id}
      className="-m-4 flex min-w-0 flex-col gap-2 rounded-2xl p-3 [contain-intrinsic-size:auto_9rem] [content-visibility:auto]"
    >
      {/* Given up on: still read, struck through, the way a list crosses out
          what it no longer means to do. */}
      <Link
        to={href}
        onClick={open}
        className={cn(
          "text-[0.93rem] leading-snug font-semibold break-words hover:underline",
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

      <TicketActions ticket={ticket} className="-mx-1" answer={{ href, onClick: open }} />
      <TicketFoot ticket={ticket} />
    </div>
  )
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
 * shows is that wait — as long as Notion takes to answer. The robot, thinking,
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
  // The figures are the board's: a ticket's page is drawn under the same
  // `top`, and has its own column to say what it is doing.
  if (!loading)
    return listing ? (
      <>
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
 * many of them it kept, out of how many: "3 / 12". */
function heading(key: string, name: string, count?: number, total?: number) {
  return (
    <span className="flex items-center gap-2">
      <span className={cn("size-1.5 shrink-0 rounded-full", SEED[key] ?? "bg-muted-foreground")} />
      <span className="truncate">{capital(name)}</span>
      {count === undefined ? null : (
        <span className="bg-background text-muted-foreground ms-auto shrink-0 rounded-full px-2 py-0.5 text-xs font-normal tabular-nums">
          {total === undefined ? count : `${count} / ${total}`}
        </span>
      )}
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
 * when it got there — and a button under it draws that many more. Every other
 * column is work in flight, and is drawn whole.
 *
 * What a search keeps is what is counted: the rows are the ones it left, so a
 * search that finds an old ticket finds it among thirty, not behind three
 * hundred. */
const TERMINAL = new Set<string>(["done", "cancelled"])
export const TERMINAL_PAGE = 30

/* How far each terminal column was opened, for as long as the tab lives: going
 * to a ticket and back to the board is not starting again from thirty. */
const opened = new Map<string, number>()

const touched = (row: RowInterface) => Date.parse(String(row.data?.edited ?? "")) || 0

/** One column of the board, as the package draws it — terminal ones cut short, with the way to the rest. */
function BoardColumn({
  column,
  label,
  rows,
  total,
  dragging,
  onDragging,
}: {
  column: string
  label: string
  rows: RowInterface[]
  /** How many the column holds, search or not — said only while one is on. */
  total?: number
  dragging: boolean
  onDragging: (dragging: boolean) => void
}) {
  const [shown, setShown] = React.useState(() => opened.get(column) ?? TERMINAL_PAGE)
  const mine = React.useMemo(() => {
    const own = rows.filter((row) => row.data?.column === column)
    return TERMINAL.has(column) ? own.sort((a, b) => touched(b) - touched(a)) : own
  }, [rows, column])
  const drawn = TERMINAL.has(column) ? mine.slice(0, shown) : mine
  const left = mine.length - drawn.length

  const more = () => {
    const next = shown + TERMINAL_PAGE
    opened.set(column, next)
    setShown(next)
  }

  // The package draws its column 18rem wide and rigid; the wrapper is what
  // shares the width, and the column fills it — no wider: left at
  // `min-width: auto`, its widest card would widen it. Its own count is
  // hidden: it counts what it was handed, and the heading says the column's.
  return (
    <div
      className={cn(
        "flex flex-1 basis-0 snap-start flex-col gap-2 *:w-auto *:min-w-0 [&_header>p]:flex-1 [&_header>span]:hidden",
        COLUMN_MIN
      )}
    >
      <RowWrapperColumnComponent
        identifierKey="column"
        valueIdentifier={{ value: column, label: heading(column, label, mine.length, total) }}
        isDragging={dragging}
        handleDragging={onDragging}
        rows={drawn}
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
  const { resource } = useCurrentViewResourceContext()
  const [dragging, setDragging] = React.useState(false)
  const [emptyShown, setEmptyShown] = useEmptyColumnsShown()
  const strip = React.useRef<HTMLDivElement>(null)
  const [more, setMore] = React.useState({ left: false, right: false })

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

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <TicketSearch
        tickets={all.map((row) => row.data as Ticket)}
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
      <div className={cn("relative", filtering && !rows.length && "hidden")}>
        <div
          ref={strip}
          onScroll={measure}
          className="scroll-thin flex snap-x snap-mandatory items-start gap-3 overflow-x-auto scroll-smooth pb-2"
        >
          {columns.map((column) => {
            const name = columnTitle(column.key, column.name)
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
    </div>
  )
}

/* The table, under the same search bar as the board: the package's own table,
 * handed the rows the search keeps. */
function TicketTable({ rows: all = [] }: ListComponentPropsInterface) {
  const { kept, filtering } = useTicketFilter(all)
  const { resource } = useCurrentViewResourceContext()
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <TicketSearch
        tickets={all.map((row) => row.data as Ticket)}
        shown={kept.length}
        projects={resource["@id"] !== PROJECT_TICKETS}
      />
      {filtering && !kept.length ? <NoMatch /> : <ListTable rows={kept} />}
    </div>
  )
}

/** A new ticket, written to the board and put on the one the console holds, so it is drawn at once. */
export async function createTicket(fresh: TicketWrite): Promise<TicketItem> {
  const title = String(fresh.title ?? "").trim()
  // Said under the field it is about, not only in a toast in the corner.
  if (!title) throw new FieldProblem("title", t("A ticket needs a title."))
  const made = await api.createTicket({
    title,
    body: String(fresh.body ?? ""),
    project: String(fresh.project ?? ""),
    ready: fresh.ready !== false,
    priority: String(fresh.priority ?? ""),
    type: String(fresh.type ?? ""),
    model: String(fresh.model ?? ""),
    subtype: String(fresh.subtype ?? ""),
  })
  const projects = await api.projects().catch(() => ({ projects: [] }))
  const project = projects.projects.find((candidate) => candidate.id === fresh.project)
  // A draft lands among the drafts, with the status the board keeps them
  // under, or none on a board that names no such option.
  const drafts = currentBoard()?.columns.find((candidate) => candidate.key === "draft")
  const column = fresh.ready === false ? "draft" : "ready"
  const card: Ticket = {
    id: made.id.replace(/-/g, ""),
    short: made.id.replace(/-/g, "").slice(-8),
    title: made.title,
    url: "",
    status: column === "draft" ? drafts?.name ?? "" : "",
    column,
    project: project?.name ?? "",
    kind: project?.kind ?? "",
    // The key was sent; the card says it as the board spells it.
    type: currentBoard()?.choices?.type?.find((choice) => choice.value === fresh.type)?.label ?? "",
    subtype: String(fresh.subtype ?? ""),
    priority: String(fresh.priority ?? ""),
    model: String(fresh.model ?? ""),
    progress: "",
    runner: "",
    pull_request: "",
    session: "",
    session_link: "",
    cost: null,
    duration: null,
    scheduled: "",
    created: new Date().toISOString(),
    edited: new Date().toISOString(),
  }
  addTicket(card)
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
const viewsOf = (form: FormInterface, empty: React.FC): ResourceDefinition<TicketItem, TicketWrite>["views"] => ({
  list: {
    // The resource's name and the line under it are what the list's own header
    // says, next to its icon: the board opens on its own words. What the board
    // is, without naming where it is kept: the same console
    // draws a Notion workspace and a directory of Markdown files, and a
    // sentence that names one of them is wrong half the time.
    description: "Your board, live. Drop a card in another column and the runner is told.",
    form,
    /* The two tabs over the list. Their labels go through the dictionary as
     * the tabs are drawn, and their address is their type: `board`, `table`,
     * in every language. */
    layouts: [
      layout.board({
        label: "board",
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
      layout.table({ label: "table", fullWidth: true, components: { list: TicketTable } }),
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
  // A card dropped in a column is written through the list itself (see
  // `DropZone`), not through a form: nothing of a ticket is edited here, and
  // nothing is deleted — Notion keeps it.
  permissions: { update: false, delete: false, export: false },

  repository: {
    // The rows are the stream's; asking Notion again here would be asking it
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
    // waiting for Notion. The brief is the page's to read (see `readTicket`).
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
      if (column) await moveTicket(id, column)
      const after = currentBoard()?.tickets.find((ticket) => ticket.id === id) ?? before
      return { data: after ? item(after) : (patch as unknown as TicketItem) }
    },
    createItem: async (fresh) => ({ data: await createTicket(fresh) }),
    removeItem: async () => {
      throw new Error("a ticket is not deleted from the console; Notion keeps it")
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
