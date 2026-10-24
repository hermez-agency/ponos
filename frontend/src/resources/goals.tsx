import * as React from "react"
import { Target } from "lucide-react"
import {
  ActionList,
  DateInputController,
  MultiSelectInputController,
  SelectInputController,
  TextAreaInputController,
  type FormInterface,
  type InputControllerComponentInterface,
} from "react-data-form"
import {
  createResourceCollection,
  createViewResource,
  generateLink,
  generateLinkByResource,
  layout,
} from "react-resource-view"

import { FilterSelect, listFilters } from "@/components/console/filter-bar"
import { PriorityInputController } from "@/components/console/priority"
import { api, why } from "@/lib/api"
import { boardOnce, titleOf } from "@/lib/board-store"
import { EVERY_STATUS, keeps, valuesOf } from "@/lib/goal-search"
import { onGoalsMoved } from "@/lib/goals-store"
import { t } from "@/lib/i18n"
import { readScore } from "@/lib/priority"
import type { Goal } from "@/lib/types"
import { projectsOnce } from "@/resources/projects"

/* The goals, declared for react-resource-view as the ideas are.
 *
 * Listed and written: a card per goal, how many of its tickets are done, and
 * the page of one in a drawer over the list — and the forms that create one,
 * change any of its columns, tie tickets to it and delete it, which is Notion's
 * trash — a goal met or given up is closed by its status instead, and kept. The progress is the server's count of the tickets the board lists (see
 * `Api.goals`), so it is the same on a board of Markdown files as on Notion's,
 * and it is read again after every write.
 *
 * The rows are every goal, read once for whoever asks while the request is
 * out, and filtered here: a workspace has a handful of them, and the filters
 * offer the values the last read found.
 */

export const GOALS = "goals"

/** A goal as the views hold it: the row and an IRI. */
export type GoalItem = Goal & { "@id": string; "@type": string }

/** What the console writes about a goal: the columns a row is written in, and its tickets. */
export interface GoalWrite {
  id?: string
  name?: string
  description?: string
  criterion?: string
  due?: string
  status?: string
  /** A score from 0 to 100, as typed: empty leaves the column as it is. */
  priority?: string | number | null
  projects?: string[]
  tickets?: string[]
}

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

/** The goals, read once for whoever asks while the request is out. */
export const goalsOnce = (): Promise<Goal[]> => readAgain()

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
 * statuses, and the console has no word list of them. The status rests on the
 * active goals, and offers every one besides. */
const valueFilter = (field: "status" | "projects", label: string, all: string): InputControllerComponentInterface =>
  function GoalFilter({ formInput, onChange }) {
    const known = useGoals().goals ?? []
    const resting =
      field === "status"
        ? [
            { value: "", label: t("Active goals") },
            { value: EVERY_STATUS, label: t(all) },
          ]
        : [{ value: "", label: t(all) }]
    return (
      <FilterSelect
        label={t(label)}
        data-slot={`goals-${field}-filter`}
        value={String(formInput.value ?? "")}
        onChange={(value) => onChange({ ...formInput, value })}
        always={field === "status"}
        options={[...resting, ...valuesOf(known, field).map((value) => ({ value, label: value }))]}
      />
    )
  }

/* In the address as `status` and `project`; "" is "all" for the project, and
 * the active goals for the status — "all" is every one. */
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

/* -- the forms ------------------------------------------------------------- */

/* The columns of the Objectifs database, in the order they are read; the
 * server writes the ones it finds under their names there. The statuses are
 * the database's own options, and the projects and tickets are those the
 * console already holds — a goal is tied to tickets from either side. */
const STATUSES = ["actif", "en pause", "atteint", "abandonné"]

const fields: FormInterface["inputs"] = {
  name: {
    label: "Name",
    required: true,
    get placeholder() {
      return t("Launch v1")
    },
    validator: (value: unknown) => {
      if (!String(value ?? "").trim()) throw new Error(t("A goal needs a name"))
      return value
    },
  },
  description: {
    label: "Description",
    controller: TextAreaInputController,
    get description() {
      return t("One line: what this goal means.")
    },
  },
  criterion: {
    label: "Done when",
    controller: TextAreaInputController,
    get description() {
      return t("How we know it is met. Observable, not an intention.")
    },
  },
  due: { label: "Due", controller: DateInputController },
  status: {
    label: "Status",
    controller: SelectInputController,
    getValueOptions: async () => [
      { value: "", label: t("No status") },
      ...STATUSES.map((value) => ({ value, label: value })),
    ],
  },
  priority: {
    label: "Priority",
    controller: PriorityInputController,
    validator: (value: unknown) => {
      if (readScore(value) === undefined) throw new Error(t("A priority is a number from 0 to 100."))
      return value
    },
  },
  projects: {
    label: "Projects",
    controller: MultiSelectInputController,
    getValueOptions: async () => {
      const every = await projectsOnce()
      return every.projects
        .filter((project) => project.id)
        .map((project) => ({ value: project.id, label: project.name }))
    },
  },
  tickets: {
    label: "Tickets",
    controller: MultiSelectInputController,
    get description() {
      return t("The tickets that serve this goal; its progress is counted from them.")
    },
    getValueOptions: async () => {
      const board = await boardOnce()
      return board.tickets.map((ticket) => ({ value: ticket.id, label: `#${ticket.short} ${titleOf(ticket)}` }))
    },
  },
}

const form: FormInterface = { label: { submit: "Save" }, inputs: fields }

/** The row as the form holds it: the tickets and projects by id, the priority as typed. */
const withIds = (goal: Goal): GoalItem => ({
  ...item(goal),
  // The form's multi-selects hold ids, where the row names them.
  projects: goal.project_ids ?? [],
  // @ts-expect-error the row counts its tickets by column; the form lists them
  tickets: (goal.linked ?? []).map((ticket) => ticket.id),
})

const written = (goal: GoalWrite) => ({
  name: goal.name ?? "",
  description: goal.description ?? "",
  criterion: goal.criterion ?? "",
  // The date field hands over a moment; the column holds a day.
  due: (goal.due ?? "").slice(0, 10),
  status: goal.status ?? "",
  priority: readScore(goal.priority) ?? "",
  projects: goal.projects ?? [],
  tickets: goal.tickets ?? [],
})

export const goals = createViewResource<GoalItem, GoalWrite>(GOALS, {
  name: "Goals",
  path: "/api/goals",
  icon: Target,
  titleField: "name",
  permissions: {
    export: false,
    // Nothing to write a goal in without a Goals database: no "New goal" then.
    create: () => Boolean(read.goals) && read.configured,
  },
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
      return { data: withIds(found) as never }
    },
    updateItem: async (patch) => {
      const id = String(patch.id ?? "")
      await api.saveGoal(id, written(patch))
      const found = (await readAgain()).find((goal) => goal.id === id)
      return { data: (found ? item(found) : patch) as never }
    },
    createItem: async (fresh) => {
      const made = await api.createGoal(written(fresh))
      const found = (await readAgain()).find((goal) => goal.id === made.id)
      return { data: (found ? item(found) : { ...fresh, ...made }) as never }
    },
    removeItem: async ({ id }) => {
      await api.deleteGoal(String(id))
      await readAgain().catch(() => null)
    },
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
    create: {
      title: "New goal",
      buttonLabel: "New goal",
      form,
      open: "drawer",
    },
    update: {
      title: "Edit the goal",
      buttonLabel: "Edit",
      form,
      open: "drawer",
    },
  },
})

/** Where the goals are listed. */
export const goalsHref = () => generateLinkByResource({ resource: goals, resourceAction: ActionList.list })

/** "New goal", in its drawer over the list of goals. */
export const newGoalHref = () =>
  generateLink({
    resource: goals,
    resourceAction: ActionList.list,
    scope: goals.scope,
    childViewResource: { resource: goals, resourceAction: ActionList.create },
  })

/** One goal's page. */
export const goalHref = (id: string) => generateLinkByResource({ resource: goals, resourceAction: ActionList.read, id })

/* Something moved a goal outside the package's forms — another tab, the
 * assistant, a card of one dropped in Done: read again, and said the way the
 * package says it after a form, so every list of them and a goal opened over
 * one read themselves again from that same request. */
onGoalsMoved(() => {
  void readAgain().catch(() => null)
  goals.onChange.publish({ data: {} as GoalItem, action: ActionList.update })
})
