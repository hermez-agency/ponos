import * as React from "react"
import { Target } from "lucide-react"
import { ActionList, type FormInterface, type InputControllerComponentInterface } from "react-data-form"
import {
  createResourceCollection,
  createViewResource,
  generateLinkByResource,
  layout,
} from "react-resource-view"

import { FilterSelect, listFilters } from "@/components/console/filter-bar"
import { api, why } from "@/lib/api"
import { keeps, valuesOf } from "@/lib/goal-search"
import { t } from "@/lib/i18n"
import type { Goal } from "@/lib/types"

/* The goals, declared for react-resource-view as the ideas are.
 *
 * Read only: the goals database is written in Notion, and the console lists
 * what it holds — a card per goal, how many of its tickets are done, and the
 * page of one in a drawer over the list. The progress is the server's count of
 * the tickets the board lists (see `Api.goals`), so it is the same on a board
 * of Markdown files as on Notion's.
 *
 * The rows are every goal, read once for whoever asks while the request is
 * out, and filtered here: a workspace has a handful of them, and the filters
 * offer the values the last read found.
 */

export const GOALS = "goals"

/** A goal as the views hold it: the row and an IRI. */
export type GoalItem = Goal & { "@id": string; "@type": string }

const item = (goal: Goal): GoalItem => ({ ...goal, "@id": `/api/goals/${goal.id}`, "@type": GOALS })

/* -- what the list last read ---------------------------------------------- */

/* Kept outside the rows the package holds, because the filter bar reads it
 * too: the statuses and the projects it offers are every goal's. */
interface LastRead {
  goals: Goal[] | null
  configured: boolean
  problem: string
}

let read: LastRead = { goals: null, configured: true, problem: "" }
const listeners = new Set<() => void>()

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** What the list last read, redrawn with it. */
export function useGoals(): LastRead {
  return React.useSyncExternalStore(subscribe, () => read)
}

let asked: Promise<Goal[]> | null = null

function readAgain(): Promise<Goal[]> {
  asked ??= api
    .goals()
    .then((fresh) => {
      read = { goals: fresh.goals, configured: fresh.configured, problem: "" }
      listeners.forEach((listener) => listener())
      return fresh.goals
    })
    .catch((error) => {
      read = { ...read, problem: why(error) }
      listeners.forEach((listener) => listener())
      throw error
    })
    .finally(() => {
      asked = null
    })
  return asked
}

/* -- the filter bar ------------------------------------------------------- */

/* A goal's status and one of its projects, each a button of the bar whose
 * options are the ones the last read found: the goals database names its own
 * statuses, and the console has no word list of them. */
const valueFilter = (field: "status" | "projects", label: string, all: string): InputControllerComponentInterface =>
  function GoalFilter({ formInput, onChange }) {
    const known = useGoals().goals ?? []
    return (
      <FilterSelect
        label={t(label)}
        data-slot={`goals-${field}-filter`}
        value={String(formInput.value ?? "")}
        onChange={(value) => onChange({ ...formInput, value })}
        options={[{ value: "", label: t(all) }, ...valuesOf(known, field).map((value) => ({ value, label: value }))]}
      />
    )
  }

/* In the address as `status` and `project`; "" is "all" for both. */
const filters: FormInterface = {
  components: { formInputs: listFilters({ lead: "status" }) },
  inputs: {
    status: { label: "Status", controller: valueFilter("status", "Status", "All statuses") },
    project: { label: "Project", controller: valueFilter("projects", "Project", "All projects") },
  },
}

/* -- the declaration ------------------------------------------------------ */

/* The cards and the page, kept out of the first load: a page opened now and then. */
const Cards = React.lazy(() => import("@/components/console/goal-cards").then((module) => ({ default: module.GoalCards })))
const Page = React.lazy(() => import("@/components/console/goal-cards").then((module) => ({ default: module.GoalPage })))
const Empty = React.lazy(() => import("@/components/console/goal-cards").then((module) => ({ default: module.NoGoal })))

const LazyCards = (props: React.ComponentProps<typeof Cards>) => (
  <React.Suspense fallback={null}>
    <Cards {...props} />
  </React.Suspense>
)
const LazyPage = () => (
  <React.Suspense fallback={null}>
    <Page />
  </React.Suspense>
)
const LazyEmpty = () => (
  <React.Suspense fallback={null}>
    <Empty />
  </React.Suspense>
)

/* Written in Notion, never here: a form to create one is another ticket. */
const refused = async (): Promise<never> => {
  throw new Error("a goal is written in Notion")
}

export const goals = createViewResource<GoalItem>(GOALS, {
  name: "Goals",
  path: "/api/goals",
  icon: Target,
  titleField: "name",
  permissions: ["list", "read"],
  repository: {
    getCollection: async (filter) => {
      const every = await readAgain()
      return {
        data: createResourceCollection({
          id: "/api/goals",
          items: every.filter((goal) => keeps(goal, filter)).map(item),
        }),
      } as never
    },
    getItem: async ({ id }) => {
      const every = await readAgain()
      const found = every.find((goal) => goal.id === String(id))
      if (!found) throw new Error(t("This goal is no longer there."))
      return { data: item(found) }
    },
    createItem: refused,
    updateItem: refused,
    removeItem: refused,
  },
  views: {
    list: {
      description: "What the tickets are for, and how many of them are done.",
      layouts: [layout.cards({ label: "Cards", fullWidth: true, components: { list: LazyCards } })],
      rowActions: [],
      filters,
      components: { empty: LazyEmpty },
    },
    read: {
      title: "Goal",
      components: { view: LazyPage },
      open: "drawer",
    },
  },
})

/** Where the goals are listed. */
export const goalsHref = () => generateLinkByResource({ resource: goals, resourceAction: ActionList.list })

/** One goal's page. */
export const goalHref = (id: string) => generateLinkByResource({ resource: goals, resourceAction: ActionList.read, id })
