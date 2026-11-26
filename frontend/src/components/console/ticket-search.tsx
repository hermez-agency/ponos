import * as React from "react"
import { useLocation, useRouter } from "@tanstack/react-router"
import { Search, SearchX, SlidersHorizontal, X } from "lucide-react"

import { blockSaid, capital, choiceWord, columnTitle, SubtypeDot } from "@/components/console/ticket-bits"
import { EmptyState } from "@/components/console/empty-state"
import { FilterButton } from "@/components/console/filter-bar"
import { PriorityBadge } from "@/components/console/priority"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { hotkeyLabel, useHotkeys } from "@/hooks/use-hotkeys"
import { useBoardWith } from "@/lib/board-store"
import { useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import {
  COSTS,
  EMPTY,
  FLAGS,
  PERIODS,
  active,
  among,
  isEmpty,
  marked,
  marks,
  matchesQuery,
  readQuery,
  scoreOf,
  toggled,
  writeQuery,
  type Choice,
  type Facet,
  type Flag,
  type Period,
  type TicketQuery,
} from "@/lib/ticket-search"
import type { Board, Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"
import { projectsOnce, useProjects } from "@/resources/projects"

/* The search over the tickets: one bar, for the board and for a project's page.
 *
 * What it decides is in `lib/ticket-search.ts`; this is how it is drawn and
 * where it is kept. Kept in the address, nowhere else: the board and a
 * project's page each read their own, a filtered board is a link somebody can
 * send, and a reload comes back to it. Written with `history.replace`, as the
 * project's tabs write theirs — narrowing a search is not a step anybody goes
 * back through, and the page does not scroll to the top under the person
 * typing.
 *
 * It hides nothing itself. A list asks `useTicketFilter` which of its rows the
 * query keeps, and draws those: the board's columns stay where they are with
 * fewer cards in them, so a card dragged while a search is on is dragged as
 * it always is.
 */

/** The query the address carries, and the way to write another. */
export function useTicketQuery(): [TicketQuery, (change: (query: TicketQuery) => TicketQuery) => void] {
  const { searchStr } = useLocation()
  const router = useRouter()
  const query = React.useMemo(() => readQuery(searchStr), [searchStr])
  const update = React.useCallback(
    (change: (query: TicketQuery) => TicketQuery) => {
      // Read again from the window rather than from this render: the words are
      // written a moment after they are typed, and a filter picked meanwhile
      // must not be undone by them.
      const search = window.location.search
      const next = writeQuery(search, change(readQuery(search)))
      if (next !== search) router.history.replace(`${window.location.pathname}${next}`)
    },
    [router]
  )
  return [query, update]
}

/** The words a card marks, from what the address says.
 *
 * The same array for as long as the words are the same: a ticket's window is
 * written in the address too, and a card is drawn again only when what it is
 * handed changes (see `TicketCard`). */
export function useSearchWords(): string[] {
  const text = useLocation({ select: (location) => readQuery(location.searchStr).text })
  return React.useMemo(() => marked(text), [text])
}

/* What the search reads of the board besides its tickets, each its own
 * subscription: the moves of the board leave them as they were, and the bar is
 * not drawn again for a ticket that changed its step. */
const choicesOf = (board: Board) => board.choices
const subtypesOf = (board: Board) => board.subtypes
const columnsOf = (board: Board) => board.columns
const validates = (board: Board) => board.validate
const cancels = (board: Board) => board.cancel

/** Which of a list's rows the query keeps, and whether it is asking for anything. */
export function useTicketFilter<Row extends { data?: unknown }>(rows: Row[]) {
  const [query] = useTicketQuery()
  const choices = useBoardWith(choicesOf)
  const filtering = !isEmpty(query)
  const kept = React.useMemo(() => {
    if (!filtering) return rows
    const context = { now: Date.now(), choices }
    return rows.filter((row) => row.data && matchesQuery(row.data as Ticket, query, context))
  }, [rows, query, filtering, choices])
  return { query, kept, filtering }
}

/** A text with the words of the search marked in it. */
export function Marked({ text, words }: { text: string; words: string[] }) {
  const ranges = React.useMemo(() => marks(text, words), [text, words])
  if (!ranges.length) return <>{text}</>
  const pieces: React.ReactNode[] = []
  let at = 0
  for (const [start, end] of ranges) {
    if (start > at) pieces.push(text.slice(at, start))
    pieces.push(
      <mark key={start} data-slot="search-mark" className="bg-primary/20 text-foreground rounded-sm px-px">
        {text.slice(start, end)}
      </mark>
    )
    at = end
  }
  pieces.push(text.slice(at))
  return <>{pieces}</>
}

/** What the list says when the search keeps none of its tickets. */
export function NoMatch() {
  const t = useT()
  const [, update] = useTicketQuery()
  return (
    <EmptyState
      icon={SearchX}
      title={t("No ticket matches")}
      action={
        <Button variant="outline" size="sm" onClick={() => update(() => EMPTY)}>
          <X />
          {t("Clear the filters")}
        </Button>
      }
    >
      {t("Other words, or fewer filters, and they will be back.")}
    </EmptyState>
  )
}

/* -- the bar -------------------------------------------------------------- */

interface Option {
  value: string
  label: string
  count: number
  /** A sub-type's dot before the label, in the colour it has everywhere else. */
  subtype?: string
  /** A priority score, drawn as the badge a card wears rather than as its digits. */
  score?: number
}

/* The values a list offers: the board's own choices first, in its order, then
 * whatever a ticket carries that they do not name — a model typed by hand, a
 * type since removed from the column's options. Each with the number of
 * tickets of this list it would keep, and none at all when nothing has one. */
function offered(
  tickets: Ticket[],
  read: (ticket: Ticket) => string,
  choices: Choice[] = [],
  name: (value: string, ticket?: Ticket) => string = (value) => value
): Option[] {
  const options: Option[] = choices.map((choice) => ({ ...choice, count: 0 }))
  // Each value is compared with the options once, however many tickets carry
  // it: `among` folds case and accents letter by letter, and doing it for
  // every ticket of a 2 000-ticket board, against every option, was 200 ms of
  // every move of the board.
  const seen = new Map<string, Option>()
  for (const ticket of tickets) {
    const value = read(ticket)
    if (!value) continue
    let known = seen.get(value)
    if (!known) {
      known = options.find((option) => among(value, [option.value], choices))
      if (!known) {
        known = { value, label: name(value, ticket), count: 0 }
        options.push(known)
      }
      seen.set(value, known)
    }
    known.count += 1
  }
  return options.some((option) => option.count) ? options : []
}

/** The board's choices, labelled in the console's language: see `choiceWord`. */
const said = (choices: Choice[] = []): Choice[] =>
  choices.map((choice) => ({ ...choice, label: choiceWord(choice.label) }))

/** One property, as a button and the list of its values, any number of them ticked.
 *
 * Memoised, and handed the facet and the bar's `update` rather than a function
 * made at each draw: the list over it is drawn again at every move of the
 * board, and its eight menus with it, for values that had not changed. */
const FacetFilter = React.memo(function FacetFilter({
  facet,
  label,
  options,
  selected,
  update,
}: {
  facet: Facet
  label: string
  options: Option[]
  selected: string[]
  update: (change: (query: TicketQuery) => TicketQuery) => void
}) {
  const t = useT()
  const onChange = (next: string[]) => update((current) => ({ ...current, [facet]: next }))
  if (!options.length) return null
  const one = selected.length === 1 ? options.find((option) => option.value === selected[0]) : undefined
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <FilterButton label={label} on={selected.length > 0}>
          {selected.length ? (one ? one.label : String(selected.length)) : null}
        </FilterButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-80 min-w-48 overflow-y-auto">
        {options.map((option) => (
          <DropdownMenuCheckboxItem
            key={option.value}
            checked={selected.includes(option.value)}
            // Ticking a value keeps the list open: the next one is often wanted too.
            onSelect={(event) => event.preventDefault()}
            onCheckedChange={() => onChange(toggled(selected, option.value))}
          >
            {option.subtype ? <SubtypeDot subtype={option.subtype} /> : null}
            <span className="min-w-0 flex-1 truncate">
              {option.score === undefined ? option.label : <PriorityBadge score={option.score} />}
            </span>
            <span className="text-muted-foreground ms-3 font-mono text-xs tabular-nums">{option.count}</span>
          </DropdownMenuCheckboxItem>
        ))}
        {selected.length ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onChange([])}>{t("Clear")}</DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  )
})

type Say = ReturnType<typeof useT>

/* What a period and a switch are called: in their menu, and on the pill that
 * says they are on. */
export const periodWords = (t: Say): Record<Period, string> => ({
  "": t("Any time"),
  today: t("Today"),
  "7d": t("Last 7 days"),
  "30d": t("Last 30 days"),
})

export const flagWords = (t: Say): Record<Flag, string> => ({
  pr: t("With a pull request"),
  credits: t("Waiting for credits"),
  sync: t("Move not synced"),
  scheduled: t("Scheduled"),
})

/** When a ticket last moved: one choice, or none. */
function PeriodFilter({ value, onChange }: { value: Period; onChange: (next: Period) => void }) {
  const t = useT()
  const words = periodWords(t)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <FilterButton label={t("Period")} on={Boolean(value)}>
          {value ? words[value] : null}
        </FilterButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">
          {t("Created or changed")}
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup value={value} onValueChange={(next) => onChange(next as Period)}>
          {(["", ...PERIODS] as Period[]).map((period) => (
            <DropdownMenuRadioItem key={period || "any"} value={period}>
              {words[period]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** The switches that are no column of their own, and what a ticket cost. */
function MoreFilter({
  only,
  cost,
  onOnly,
  onCost,
}: {
  only: Flag[]
  cost: number
  onOnly: (next: Flag[]) => void
  onCost: (next: number) => void
}) {
  const t = useT()
  const words = flagWords(t)
  const on = only.length + (cost > 0 ? 1 : 0)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <FilterButton label={t("Other")} on={on > 0}>
          {on ? String(on) : null}
        </FilterButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-52">
        {FLAGS.map((flag) => (
          <DropdownMenuCheckboxItem
            key={flag}
            checked={only.includes(flag)}
            onSelect={(event) => event.preventDefault()}
            onCheckedChange={() => onOnly(toggled(only, flag) as Flag[])}
          >
            {words[flag]}
          </DropdownMenuCheckboxItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">{t("Cost")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={String(cost)} onValueChange={(next) => onCost(Number(next))}>
          <DropdownMenuRadioItem value="0">{t("Any cost")}</DropdownMenuRadioItem>
          {COSTS.map((threshold) => (
            <DropdownMenuRadioItem key={threshold} value={String(threshold)}>
              {t("More than {{amount}}", { amount: money(threshold, 0) })}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/* The pills of the filters on, fetched once one is: see `filter-pills.tsx`. */
const FilterPills = React.lazy(() => import("@/components/console/filter-pills"))

/* The filters in sight beside the field, where the bar is `@4xl` wide: the ones
 * a board is most often narrowed by. Every other one — and these too, on a
 * narrow bar, where the same list holds them and the line beside the field is
 * hidden — is behind "Filters". */
const DIRECT: Facet[] = ["project", "status", "priority"]

/**
 * The bar over a list of tickets: the words, then the filters.
 *
 * Ten menus of the same weight in a row overflowed a 1440 px board ("Other" was
 * cut), and said nothing of what they asked for unless one read each button.
 * So the bar is the phone's at every width: the field, a "Filters" button that
 * counts the ones on and opens the one list of them on a line of its own, and
 * the filters that are on as pills under it, each with its cross. Where the bar
 * is wide enough, the project, the status and the priority are beside the
 * field, out of the list. Measured on the bar's own width, not the screen's,
 * since the same bar sits on pages of different widths.
 */
export function TicketSearch({
  tickets,
  shown,
  projects = true,
}: {
  /** Every ticket of the list, whatever the query: what the filters offer, and the total. */
  tickets: Ticket[]
  /** How many the query keeps. */
  shown: number
  /** Whether to offer the project: not on a project's own page. */
  projects?: boolean
}) {
  const t = useT()
  const choices = useBoardWith(choicesOf)
  const subtypes = useBoardWith(subtypesOf)
  const columns = useBoardWith(columnsOf)
  const validate = useBoardWith(validates)
  const cancel = useBoardWith(cancels)
  const [query, update] = useTicketQuery()
  const [unfolded, setUnfolded] = React.useState(false)
  const field = React.useRef<HTMLInputElement>(null)

  // The words as typed, written into the address a moment after the last key:
  // a list filtered at every letter of a long word is a list that stutters.
  const [draft, setDraft] = React.useState(query.text)
  const written = React.useRef(query.text)
  React.useEffect(() => {
    // Changed from elsewhere — "Clear the filters", the way back, a link — the field follows.
    if (query.text.trim() !== written.current.trim()) {
      written.current = query.text
      setDraft(query.text)
    }
  }, [query.text])
  React.useEffect(() => {
    if (draft === written.current) return
    const timer = window.setTimeout(() => {
      written.current = draft
      update((current) => ({ ...current, text: draft }))
    }, 150)
    return () => window.clearTimeout(timer)
  }, [draft, update])

  useHotkeys({
    search: () => {
      // Under a window, the field is not where anybody is looking.
      if (document.querySelector('[role="dialog"]')) return
      field.current?.focus()
      field.current?.select()
    },
  })

  const set = <K extends keyof TicketQuery>(key: K) => (value: TicketQuery[K]) =>
    update((current) => ({ ...current, [key]: value }))

  // Counted again only when the tickets or the board change: the bar is drawn
  // again at every change of the address, a ticket's window opened over the
  // board among them, and on 1 800 tickets the counting was 50 ms of the click.
  // `t` is there for the language the labels are said in.
  // The archived projects, by name — what a ticket carries: offered no more
  // as a filter, unless the address already asks for one.
  const listed = useProjects()
  React.useEffect(() => {
    if (projects) void projectsOnce().catch(() => undefined)
  }, [projects])
  const shelved = React.useMemo(
    () => new Set((listed?.projects ?? []).filter((project) => project.shelved).map((project) => project.name)),
    [listed]
  )
  const chosenProjects = query.project
  const facets = React.useMemo((): Record<Facet, Option[]> => {
    return {
      type: offered(tickets, (ticket) => ticket.type, said(choices?.type), choiceWord),
      // In the table's order, each behind its dot, in the developers' word.
      subtype: offered(
        tickets,
        (ticket) => ticket.subtype ?? "",
        (subtypes ?? []).map((subtype) => ({
          value: subtype.key,
          label: subtype.label,
          subtype: subtype.key,
        }))
      ),
      status: columns
        .filter(
          (column) => (column.key !== "validated" || validate) && (column.key !== "cancelled" || cancel)
        )
        .map((column) => ({
          value: column.key,
          label: capital(columnTitle(column.key, column.name)),
          count: tickets.filter((ticket) => ticket.column === column.key).length,
        })),
      // The scores the board's tickets carry, the highest first, each in its badge's colour.
      priority: offered(tickets, scoreOf)
        .map((option) => ({ ...option, score: Number(option.value) }))
        .sort((a, b) => b.score - a.score),
      model: offered(
        tickets,
        (ticket) => ticket.model,
        choices?.model,
        (value, ticket) => ticket?.model_label || value
      ),
      project: projects
        ? offered(tickets, (ticket) => ticket.project)
            .filter((option) => !shelved.has(option.value) || chosenProjects.includes(option.value))
            .sort((a, b) => a.label.localeCompare(b.label))
        : [],
      // The goal by its id, said by its name: the one on the card.
      goal: offered(
        tickets,
        (ticket) => ticket.goal_id ?? "",
        [],
        (value, ticket) => ticket?.goal || value
      ).sort((a, b) => a.label.localeCompare(b.label)),
      // Why the stopped ones stopped, the commonest cause first.
      block: offered(
        tickets,
        (ticket) => ticket.block?.code ?? "",
        [],
        (value, ticket) => (ticket?.block ? blockSaid(ticket.block.label) : value)
      ).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)),
    }
    // `t` is not read here, but changes with the language that `blockSaid` and
    // `choiceWord` read: switching it says the labels again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickets, choices, subtypes, columns, validate, cancel, projects, shelved, chosenProjects, t])
  const names: Record<Facet, string> = {
    type: t("Type"),
    subtype: t("Sub-type"),
    status: t("Status"),
    priority: t("Priority"),
    model: t("Model"),
    project: t("Project"),
    goal: t("Goal"),
    block: t("Cause"),
  }
  const on = active(query)
  const filtering = on > 0 || Boolean(query.text.trim())
  const shortcut = hotkeyLabel("search")

  const facetFilter = (facet: Facet) => (
    <FacetFilter
      key={facet}
      facet={facet}
      label={names[facet]}
      options={facets[facet]}
      selected={query[facet]}
      update={update}
    />
  )

  return (
    <div data-slot="ticket-search" className="@container flex min-w-0 flex-col gap-2">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <div className="relative min-w-48 flex-1 @4xl:max-w-sm @4xl:min-w-56">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
          <Input
            ref={field}
            type="search"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== "Escape") return
              // Escape empties the field; on an empty one, it leaves it.
              event.preventDefault()
              event.stopPropagation()
              if (!draft) return event.currentTarget.blur()
              written.current = ""
              setDraft("")
              update((current) => ({ ...current, text: "" }))
            }}
            placeholder={t("Search tickets: title, id, result, pull request…")}
            aria-label={t("Search tickets")}
            aria-keyshortcuts={shortcut.aria}
            autoComplete="off"
            spellCheck={false}
            className="h-8 ps-8 pe-8 [&::-webkit-search-cancel-button]:hidden"
          />
          {draft ? (
            <button
              type="button"
              onClick={() => {
                written.current = ""
                setDraft("")
                update((current) => ({ ...current, text: "" }))
                field.current?.focus()
              }}
              className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2 -translate-y-1/2"
              aria-label={t("Clear the search")}
            >
              <X className="size-3.5" />
            </button>
          ) : (
            <kbd className="text-muted-foreground bg-muted pointer-events-none absolute top-1/2 right-2 hidden -translate-y-1/2 rounded border px-1.5 font-mono text-[0.65rem] sm:inline">
              {shortcut.label}
            </kbd>
          )}
        </div>

        <div className="hidden items-center gap-1.5 @4xl:flex">{DIRECT.map(facetFilter)}</div>

        <Button
          variant="outline"
          size="sm"
          data-slot="filters-button"
          className={cn("shrink-0", on > 0 && "border-primary/50")}
          aria-expanded={unfolded}
          onClick={() => setUnfolded(!unfolded)}
        >
          <SlidersHorizontal />
          {t("Filters")}
          {on ? (
            <span className="bg-primary text-primary-foreground rounded-full px-1.5 text-xs tabular-nums">{on}</span>
          ) : null}
        </Button>

        {filtering ? (
          <span
            className="text-muted-foreground ms-auto shrink-0 font-mono text-xs whitespace-nowrap tabular-nums"
            data-slot="search-count"
          >
            {shown} / {tickets.length}
          </span>
        ) : null}

        <div
          data-slot="ticket-filters"
          className={cn("basis-full flex-wrap items-center gap-1.5", unfolded ? "flex" : "hidden")}
        >
          {(Object.keys(facets) as Facet[]).map((facet) =>
            DIRECT.includes(facet) ? (
              <div key={facet} className="contents @4xl:hidden">
                {facetFilter(facet)}
              </div>
            ) : (
              facetFilter(facet)
            )
          )}
          <PeriodFilter value={query.since} onChange={set("since")} />
          <MoreFilter only={query.only} cost={query.cost} onOnly={set("only")} onCost={set("cost")} />
        </div>
      </div>

      {on ? (
        <React.Suspense fallback={null}>
          <FilterPills query={query} labels={facets} names={names} update={update} />
        </React.Suspense>
      ) : null}
    </div>
  )
}
