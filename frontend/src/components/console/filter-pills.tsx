import { X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Worded, useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import { EMPTY, type Facet, type Period, type TicketQuery } from "@/lib/ticket-search"
import { flagWords, periodWords } from "@/components/console/ticket-search"

/* The filters that are on, as pills under the board's search bar: what each
 * asks for, and its cross. Fetched once a filter is on (see `TicketSearch`):
 * the first load of the board is held to a budget, and a board nobody narrowed
 * draws none of this. */

/* Their words in French, fetched with them: see `pills-french.ts`. */
const words = () => import("@/lib/pills-french").then((module) => module.PILLS_FRENCH)

interface Pill {
  key: string
  label: string
  remove: (query: TicketQuery) => TicketQuery
}

export default function FilterPills(props: Parameters<typeof Pills>[0]) {
  return (
    <Worded words={words}>
      <Pills {...props} />
    </Worded>
  )
}

function Pills({
  query,
  labels,
  names,
  update,
}: {
  query: TicketQuery
  /** What each value of a list is called, as its menu says it. */
  labels: Record<Facet, { value: string; label: string }[]>
  names: Record<Facet, string>
  update: (change: (query: TicketQuery) => TicketQuery) => void
}) {
  const t = useT()
  const periods = periodWords(t)
  const flags = flagWords(t)
  // Each value asked for, a pill of its own: a status among three is taken off alone.
  const pills: Pill[] = [
    ...(Object.keys(labels) as Facet[]).flatMap((facet) =>
      query[facet].map((value) => ({
        key: `${facet}:${value}`,
        label: `${names[facet]}: ${labels[facet].find((option) => option.value === value)?.label ?? value}`,
        remove: (current: TicketQuery) => ({ ...current, [facet]: current[facet].filter((one) => one !== value) }),
      }))
    ),
    ...(query.since
      ? [
          {
            key: "since",
            label: `${t("Period")}: ${periods[query.since]}`,
            remove: (current: TicketQuery) => ({ ...current, since: "" as Period }),
          },
        ]
      : []),
    ...query.only.map((flag) => ({
      key: `only:${flag}`,
      label: flags[flag],
      remove: (current: TicketQuery) => ({ ...current, only: current.only.filter((one) => one !== flag) }),
    })),
    ...(query.cost > 0
      ? [
          {
            key: "cost",
            label: t("More than {{amount}}", { amount: money(query.cost, 0) }),
            remove: (current: TicketQuery) => ({ ...current, cost: 0 }),
          },
        ]
      : []),
  ]
  if (!pills.length) return null

  return (
    <ul data-slot="filter-pills" className="flex min-w-0 flex-wrap items-center gap-1.5" aria-label={t("Filters on")}>
      {pills.map((pill) => (
        <li
          key={pill.key}
          data-slot="filter-pill"
          className="bg-primary/10 text-primary flex h-6 max-w-64 min-w-0 items-center gap-1 rounded-full ps-2.5 pe-1 text-xs font-medium"
        >
          <span className="min-w-0 truncate">{pill.label}</span>
          <button
            type="button"
            onClick={() => update(pill.remove)}
            className="hover:bg-primary/15 shrink-0 rounded-full p-0.5"
            aria-label={t("Remove the filter {{name}}", { name: pill.label })}
          >
            <X className="size-3" />
          </button>
        </li>
      ))}
      {pills.length > 1 ? (
        <li>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs"
            // The filters, not the words: those have their own cross, in the field.
            onClick={() => update((current) => ({ ...EMPTY, text: current.text }))}
          >
            {t("Clear all")}
          </Button>
        </li>
      ) : null}
    </ul>
  )
}
