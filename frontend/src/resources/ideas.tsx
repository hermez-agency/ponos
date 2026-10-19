import * as React from "react"
import { Gauge, Lightbulb } from "lucide-react"
import {
  ActionList,
  SelectInputController,
  TextAreaInputController,
  type FormInterface,
  type InputControllerComponentInterface,
} from "react-data-form"
import {
  createResourceCollection,
  createViewResource,
  generateLinkByResource,
  layout,
  open,
  useCurrentViewResourceContext,
  type ResourceDefinition,
} from "react-resource-view"
import { toast } from "sonner"

import {
  IdeaCards,
  IdeaPage,
  IdeaRows,
  NoIdea,
  CATEGORY_WORDS,
  useStatusWords,
  useToneWords,
} from "@/components/console/idea-cards"
import { ConfirmDialog } from "@/components/console/confirm-dialog"
import {
  ChipsInputController,
  IdeaFields,
  IdeaFoot,
  IdeaForm,
  IdeaTextInputController,
  IdeaTitleInputController,
  IdeaWindow,
} from "@/components/console/idea-form"
import { IdeasButton } from "@/components/console/ideas-deck"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { api, why } from "@/lib/api"
import { counted, t, useT } from "@/lib/i18n"
import {
  AUTHORS,
  CATEGORIES,
  ORDERS,
  STATUSES,
  TONES,
  WORKSPACE,
  bare,
  counts,
  keeps,
  orderOf,
  ordered,
  scopes,
} from "@/lib/idea-search"
import { onIdeasScored } from "@/lib/ideas-store"
import { money, number } from "@/lib/numbers"
import { layoutOf, useLayoutInTheAddress } from "@/lib/resource-view"
import type { Idea, Unscored } from "@/lib/types"
import { projectsOnce, useProjects } from "@/resources/projects"

/* The ideas, declared once for react-resource-view.
 *
 * They were a pane of their own — a list drawn by hand, its filters held in the
 * component's state, a form written beside it — while every other list of the
 * console is the package's. So an idea is a resource like a project: a list in
 * two layouts, a page that reads one, and the package's forms to write one or
 * reword it. The filters are the ones the pane had, now the package's own
 * filter bar, which writes them in the address: a list filtered on Website's
 * kept ideas is a link that opens on Website's kept ideas. The category is one
 * more of them, in the same shape: the reason ideas are sorted is to be able to
 * look at the security ones alone. And the score, by its colour, with the order
 * beside it: the new ideas rest on the most relevant first (see `orderOf`).
 *
 * Two layouts, as the projects have. **Cards** to go through them, each with
 * the one gesture it is waiting for — turning it into a ticket, or opening the
 * ticket it became — and the others in a menu; **a table** to compare a long
 * list of them in one screen.
 *
 * Two declarations, as the tickets have. `ideas` is the page of the menu, every
 * scope at once with a project filter; `scopedIdeas` is the same list under a
 * project's page and in the swipe's second tab, where the scope is given by
 * whoever draws it (see `ScopedIdeas`) and the bar has no project to choose.
 *
 * The rows are every idea the server holds, read once for whoever asks while
 * the request is out, and filtered here: the counts beside the statuses need
 * the ideas the status filter leaves out, and a page of ideas is a few dozen
 * rows of the local database.
 */

export const IDEAS = "ideas"
export const SCOPED_IDEAS = "scoped-ideas"

/** An idea as the views hold it: the row, its id as the address writes it, and an IRI. */
export type IdeaItem = Omit<Idea, "id"> & { id: string; "@id": string; "@type": string }

/** What the forms write: a new idea, or the words of one. */
export interface IdeaWrite {
  id?: number | string
  title?: string
  description?: string
  project?: string
  kind?: Idea["kind"]
  category?: Idea["category"]
}

const item = (idea: Idea): IdeaItem => ({
  ...idea,
  id: String(idea.id),
  "@id": `/api/ideas/${idea.id}`,
  "@type": IDEAS,
})

/** The row the views hold, as the API reads it again. */
export const ideaOf = (row: IdeaItem): Idea => ({ ...row, id: Number(row.id) })

/* -- what the list last read ---------------------------------------------- */

/* Kept outside the rows the package holds, because the filter bar reads it
 * too: the counts beside the statuses, and the projects the project filter
 * offers, are about every idea, not the ones the filters left. The refusal is
 * kept with it, for the page to say why nothing was read. */
interface LastRead {
  ideas: Idea[] | null
  problem: string
}

let read: LastRead = { ideas: null, problem: "" }
const listeners = new Set<() => void>()

function publish(fresh: LastRead) {
  read = fresh
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** What the list last read, redrawn with it. */
export function useIdeas(): LastRead {
  return React.useSyncExternalStore(subscribe, () => read)
}

let asked: Promise<Idea[]> | null = null

/* Every idea, read again — once for everybody who asks while it is out: the
 * lists of a page reading themselves again after a change, and the idea opened
 * over them. */
function readAgain(): Promise<Idea[]> {
  asked ??= api
    .allIdeas("", true)
    .then((fresh) => {
      publish({ ideas: fresh.ideas, problem: "" })
      return fresh.ideas
    })
    .catch((error) => {
      publish({ ideas: read.ideas, problem: why(error) })
      throw error
    })
    .finally(() => {
      asked = null
    })
  return asked
}

/* Something changed an idea outside the package's forms — a gesture on a card,
 * a decision in the swipe, a batch scored. Said on both declarations, the way
 * the package says it after a form: every list of them reads itself again,
 * with the filters it shows now, and an idea opened over one with it. */
export function ideasChanged(idea?: Idea) {
  for (const resource of [ideas, scopedIdeas])
    resource.onChange.publish({ data: (idea ? item(idea) : {}) as IdeaItem, action: ActionList.update })
}

/* -- the filter bar ------------------------------------------------------- */

/* The status: a row of buttons, each with how many ideas it would show, as the
 * pane had them. A select would hide the counts, which are what the row is
 * read for. The counts follow the two other filters (see `idea-search.ts`). */
const StatusFilter: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const { filter } = useCurrentViewResourceContext()
  const known = useIdeas().ideas ?? []
  const words = useStatusWords()
  const counted = counts(known, filter ?? {})
  const value = String(formInput.value ?? "")
  return (
    <div className="flex flex-nowrap gap-1" role="group" aria-label={t("Status")}>
      {(["", ...STATUSES] as const).map((key) => (
        <Button
          key={key || "all"}
          type="button"
          size="sm"
          variant={value === key ? "secondary" : "ghost"}
          aria-pressed={value === key}
          data-slot="ideas-filter"
          data-status={key || "all"}
          className="h-8 gap-1.5 px-2.5 text-xs"
          onClick={() => onChange({ ...formInput, value: key })}
        >
          {key ? words.many[key] : t("All")}
          <span className="text-muted-foreground tabular-nums" data-slot="ideas-count">
            {counted[key || "all"]}
          </span>
        </Button>
      ))}
    </div>
  )
}

/* A select of the bar, positioned: Radix draws a native select beside it,
 * absolutely, and one placed against the page rather than against the bar
 * escapes the bar's scrolling and widens a phone's screen. */
const Choice = ({ children }: { children: React.ReactNode }) => <div className="relative">{children}</div>

/* Whom an idea is for: every project an idea is for, by its name, and the
 * workspace. Drawn here rather than by the package's select, whose options are
 * asked for once: these are the ones the last read found. */
const ANY = "__any__"

const ProjectFilter: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const known = useIdeas().ideas ?? []
  const projects = useProjects()
  React.useEffect(() => {
    void projectsOnce().catch(() => undefined)
  }, [])
  const named = scopes(known)
    .map((id) => ({
      id,
      name: projects?.projects.find((one) => bare(one.id) === id)?.name ?? t("Project"),
    }))
    .sort((a, b) => a.name.localeCompare(b.name))
  return (
    <Choice>
      <Select
        value={String(formInput.value ?? "") || ANY}
        onValueChange={(value) => onChange({ ...formInput, value: value === ANY ? "" : value })}
      >
        <SelectTrigger size="sm" className="h-8 w-auto text-xs" data-slot="ideas-project-filter" aria-label={t("Project")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ANY}>{t("All projects")}</SelectItem>
          <SelectItem value={WORKSPACE}>{t("Workspace")}</SelectItem>
          {named.map((one) => (
            <SelectItem key={one.id} value={one.id}>
              {one.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Choice>
  )
}

/* Who wrote it, in the same shape as the project: two selects side by side
 * that do not look like two different things. */
const AuthorFilter: InputControllerComponentInterface = ({ formInput, onChange }) => (
  <Choice>
    <Select
      value={String(formInput.value ?? "") || ANY}
      onValueChange={(value) => onChange({ ...formInput, value: value === ANY ? "" : value })}
    >
      <SelectTrigger size="sm" className="h-8 w-auto text-xs" data-slot="ideas-author-filter" aria-label={t("Written by")}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ANY}>{t("Written by anyone")}</SelectItem>
        {AUTHORS.map((author) => (
          <SelectItem key={author} value={author}>
            {author === "ponos" ? t("Written by Ponos") : t("Written by us")}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  </Choice>
)

/* What an idea is about, in the same shape as the two others. */
const CategoryFilter: InputControllerComponentInterface = ({ formInput, onChange }) => {
  useT()
  return (
    <Choice>
      <Select
        value={String(formInput.value ?? "") || ANY}
        onValueChange={(value) => onChange({ ...formInput, value: value === ANY ? "" : value })}
      >
        <SelectTrigger size="sm" className="h-8 w-auto text-xs" data-slot="ideas-category-filter" aria-label={t("Category")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ANY}>{t("All categories")}</SelectItem>
          {CATEGORIES.map((category) => (
            <SelectItem key={category} value={category}>
              {CATEGORY_WORDS[category]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Choice>
  )
}

/* The colour of the score, in the same shape: green, orange, red, or not scored. */
const ScoreFilter: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const words = useToneWords()
  return (
    <Choice>
      <Select
        value={String(formInput.value ?? "") || ANY}
        onValueChange={(value) => onChange({ ...formInput, value: value === ANY ? "" : value })}
      >
        <SelectTrigger size="sm" className="h-8 w-auto text-xs" data-slot="ideas-score-filter" aria-label={t("Score")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ANY}>{t("All scores")}</SelectItem>
          {TONES.map((tone) => (
            <SelectItem key={tone} value={tone}>
              {words[tone]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Choice>
  )
}

/* The order: "" is the one the status rests on, and the select shows which
 * that is; choosing it again puts "" back, so the address says only a choice. */
const OrderFilter: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const { filter } = useCurrentViewResourceContext()
  const resting = orderOf({ status: filter?.status })
  const shown = orderOf({ status: filter?.status, sorted: formInput.value })
  return (
    <Choice>
      <Select
        value={shown}
        onValueChange={(value) => onChange({ ...formInput, value: value === resting ? "" : value })}
      >
        <SelectTrigger size="sm" className="h-8 w-auto text-xs" data-slot="ideas-order" aria-label={t("Order")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {ORDERS.map((order) => (
            <SelectItem key={order} value={order}>
              {order === "relevance" ? t("Most relevant first") : t("Newest first")}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Choice>
  )
}

/* The filters, in the address as `status`, `category`, `score`, `project`, `author` and `sorted`; ""
 * is "all" for each, which is where the list rests. The labels are read from
 * the dictionary as the bar is drawn. */
const statusFilter = { label: "Status", controller: StatusFilter }
const categoryFilter = { label: "Category", controller: CategoryFilter }
const authorFilter = { label: "Written by", controller: AuthorFilter }
const scoreFilter = { label: "Score", controller: ScoreFilter }
const orderFilter = { label: "Order", controller: OrderFilter }

const formFilter: FormInterface = {
  inputs: {
    status: statusFilter,
    category: categoryFilter,
    score: scoreFilter,
    project: { label: "Project", controller: ProjectFilter },
    author: authorFilter,
    sorted: orderFilter,
  },
}

/* Under a project, or in the swipe: the scope is the filter whoever draws the
 * list injects, and the package keeps an injected filter through a reset. */
const scopedFormFilter: FormInterface = {
  inputs: { status: statusFilter, category: categoryFilter, score: scoreFilter, author: authorFilter, sorted: orderFilter },
}

/* -- the forms ------------------------------------------------------------- */

const title = {
  label: "Title",
  required: true,
  get placeholder() {
    return t("The idea, in one line.")
  },
  validator: (value: unknown) => {
    const said = String(value ?? "").trim()
    if (!said) throw new Error(t("An idea needs a title"))
    if (said.length > 90) throw new Error(t("A title fits in 90 characters"))
    return value
  },
}

const description = {
  label: "Description",
  controller: TextAreaInputController,
  get placeholder() {
    return t("Why it is worth doing.")
  },
}

/* One of the four, or none yet: an idea is sorted by hand as well as by Ponos,
 * and one Ponos left unsorted is sorted when it is reworded. The options are
 * read from the dictionary as the form is drawn. */
const category = {
  label: "Category",
  controller: SelectInputController,
  get description() {
    return t("Tech is refactoring, performance and debt — not a new feature.")
  },
  getValueOptions: async () => [
    { value: "", label: t("Not sorted") },
    ...CATEGORIES.map((value) => ({ value, label: CATEGORY_WORDS[value] })),
  ],
}

/* A new idea: its words, what it is about, and whom it is for — the project
 * whose list it was written from, unless changed — drawn as a quick entry in
 * its own window (see `idea-form.tsx`). The project and the type are both
 * written by the menu in the window's header: a new project is the
 * workspace's only, so it is one more entry of that menu rather than a field
 * of its own. The category is the edit form's, as chips, with the sentence
 * about Tech said only once Tech is chosen. */
const createForm: FormInterface = {
  components: { formDecorator: IdeaForm, formInputs: IdeaFields, formSubmitAction: IdeaFoot },
  inputs: {
    title: {
      ...title,
      controller: IdeaTitleInputController,
      get placeholder() {
        return t("The idea, in one line")
      },
    },
    description: {
      ...description,
      controller: IdeaTextInputController,
      get placeholder() {
        return t("Why it is worth it — context, link, example…")
      },
    },
    category: {
      label: "Category",
      controller: ChipsInputController,
      valueOptions: CATEGORIES.map((value) => ({ value, label: CATEGORY_WORDS[value] })),
    },
    project: { label: "Project", hidden: () => true },
    kind: { label: "Type", hidden: () => true, defaultValue: "ticket" },
  },
}

/* Rewording one: the title, the lines under it and its category. Whom it is for
 * is what it was proposed for, and the next batch is told about it as it is. */
const editForm: FormInterface = {
  label: { submit: "Save" },
  inputs: { title, description, category },
}

/* -- what sits around the list -------------------------------------------- */

/* Scoring the ideas that have none — those from before scores, those whose
 * session failed: how many, and the most it may cost, said before it starts.
 * Nothing at all while every idea has its score. */
function ScoreUnscored() {
  const { ideas: known } = useIdeas()
  const [told, setTold] = React.useState<Unscored | null>(null)
  const [open, setOpen] = React.useState(false)
  React.useEffect(() => {
    let alive = true
    api
      .unscoredIdeas(null)
      .then((fresh) => alive && setTold(fresh))
      .catch(() => alive && setTold(null))
    return () => {
      alive = false
    }
  }, [known])
  if (!told || (!told.count && !told.running)) return null
  const start = async () => {
    try {
      setTold(await api.scoreIdeas(null))
      toast.success(t("Scoring the ideas…"))
    } catch (error) {
      toast.error(t("The ideas could not be scored"), { description: why(error) })
      return false
    }
  }
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={setOpen}
      trigger={
        <Button size="sm" variant="outline" data-slot="ideas-score-all" disabled={told.running}>
          <Gauge />
          {told.running
            ? t("Scoring the ideas…")
            : t("Score the unscored ideas ({{count}})", { count: number(told.count) })}
        </Button>
      }
      title={t("Score the unscored ideas?")}
      description={t("{{ideas}} to score with {{model}} in {{calls}}: {{ceiling}} at most, each call stopped at its share.", {
        ideas: counted(told.count, "{{count}} idea", "{{count}} ideas"),
        model: told.model || t("the light model"),
        calls: counted(told.calls, "{{count}} call", "{{count}} calls"),
        ceiling: money(told.ceiling_usd),
      })}
      confirm={t("Score them")}
      onConfirm={start}
    />
  )
}

/** The swipe, for the project the filter is on — or the workspace's — and why nothing was read, where nothing was. */
function IdeasTop() {
  const { filter, fetchData } = useCurrentViewResourceContext()
  const { problem } = useIdeas()
  const projects = useProjects()
  useLayoutInTheAddress(IDEAS)
  const chosen = String(filter?.project ?? "")
  const project = chosen === WORKSPACE ? "" : chosen
  const name = projects?.projects.find((one) => bare(one.id) === project)?.name
  return (
    <div className="mb-2 flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <IdeasButton project={project} name={name} onClose={() => void fetchData?.()} />
        <ScoreUnscored />
      </div>
      {problem ? (
        <Alert variant="destructive">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  )
}

/* -- the declaration ------------------------------------------------------ */

const options: ResourceDefinition<IdeaItem, IdeaWrite> = {
  name: "Ideas",
  path: "/api/ideas",
  icon: Lightbulb,
  titleField: "title",
  // Nothing is ever deleted: an idea thrown away last month may be the right
  // one today, and the next batch is told about it so it is never proposed
  // twice. Throwing it away is the gesture, in the menu of its card.
  permissions: { delete: false, export: false },

  repository: {
    getCollection: async (filter) => {
      const every = await readAgain()
      return {
        data: createResourceCollection({
          id: "/api/ideas",
          items: ordered(
            every.filter((idea) => keeps(idea, filter)),
            filter
          ).map(item),
        }),
      } as never
    },
    getItem: async ({ id }) => {
      const every = await readAgain()
      const found = every.find((idea) => String(idea.id) === String(id))
      if (!found) throw new Error(t("This idea is no longer there."))
      return { data: item(found) }
    },
    updateItem: async (patch) => {
      // Field by field: a patch carries the whole row the form was built from.
      const written = await api.editIdea(Number(patch.id), {
        title: String(patch.title ?? ""),
        description: String(patch.description ?? ""),
        category: (patch.category ?? "") as Idea["category"],
      })
      await readAgain()
      return { data: item(written) }
    },
    createItem: async (fresh) => {
      const project = String(fresh.project ?? "")
      const written = await api.writeIdea({
        title: String(fresh.title ?? ""),
        description: String(fresh.description ?? ""),
        project,
        kind: project ? "ticket" : (fresh.kind ?? "ticket"),
        category: fresh.category ?? "",
      })
      toast.success(t("Idea saved: {{title}}", { title: written.title }))
      await readAgain()
      return { data: item(written) }
    },
    removeItem: async () => {
      throw new Error("an idea is not deleted; throwing it away is what keeps it out of the next batch")
    },
  },

  views: {
    list: {
      description: "What Ponos proposed, kept or thrown away, for the workspace and for each project.",
      /* The two layouts. Their labels go through the dictionary as the tabs
       * are drawn, and their address is their type: `cards`, `table`, in
       * every language. At the width of the page, as the board and the
       * projects are: in a column, the row of six filters ran past its edge
       * and cut the last one in two. */
      layouts: [
        layout.cards({ label: "cards", fullWidth: true, components: { list: IdeaCards } }),
        layout.table({ label: "table", fullWidth: true, components: { list: IdeaRows } }),
      ],
      // Every card carries its own gestures (see `idea-cards.tsx`).
      rowActions: [],
      // The filters are the package's: they live in the address (`status`,
      // `category`, `project`, `author`), and the rows are kept by `keeps`, as the list is read.
      filters: formFilter,
      components: { top: IdeasTop, empty: NoIdea },
    },
    read: {
      title: "Idea",
      components: { view: IdeaPage },
      // Over the list, which stays where it was: an idea is read to decide on it.
      open: "drawer",
    },
    create: {
      title: "New idea",
      buttonLabel: "New idea",
      form: createForm,
      // In the middle of the list, as tall as the few lines it holds; left
      // open once the idea is written, for the form to close it or empty
      // itself for the next one (see `IdeaForm`).
      open: open.custom({ type: "idea-new", component: IdeaWindow }),
      afterSave: "stay",
      // No card before the server's: one drawn from the form alone has no
      // author, and a card reads its author.
      optimistic: false,
    },
    update: {
      title: "Idea",
      buttonLabel: "Edit",
      form: editForm,
      open: "drawer",
    },
  },
}

export const ideas = createViewResource<IdeaItem, IdeaWrite>(IDEAS, options)

export const scopedIdeas = createViewResource<IdeaItem, IdeaWrite>(SCOPED_IDEAS, {
  ...options,
  views: {
    ...options.views,
    list: {
      ...options.views?.list,
      filters: scopedFormFilter,
      // No swipe over a list the swipe itself may be drawing, and nothing to
      // write in the address of a page that is somebody else's.
      components: { empty: NoIdea },
    },
  },
})

onIdeasScored(() => ideasChanged())

/** Where the ideas are listed, in the layout they were last worked in. */
export const ideasHref = () =>
  generateLinkByResource({ resource: ideas, resourceAction: ActionList.list, viewVariantId: layoutOf(IDEAS) })
