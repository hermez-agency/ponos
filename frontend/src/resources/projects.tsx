import * as React from "react"
import { Check, Clock, Columns2, Copy, FileText, Folder, FolderGit2, LayoutGrid, Plus, SearchX, X } from "lucide-react"
import {
  ActionList,
  type FormInterface,
  type InputControllerComponentInterface,
} from "react-data-form"
import {
  Link,
  ListPagination,
  createResourceCollection,
  createViewResource,
  generateLink,
  generateLinkByResource,
  layout,
  open,
  useCurrentViewResourceContext,
  useListViewContext,
  useViewLink,
  type ListComponentPropsInterface,
} from "react-resource-view"

import { ContextBlock } from "@/components/console/context-block"
import { EmptyState } from "@/components/console/empty-state"
import { FilterSelect, listFilters } from "@/components/console/filter-bar"
import { MarkdownInputController } from "@/components/console/markdown-editor"
import { ProjectThumb } from "@/components/console/project-picture"
import { ProjectMenu } from "@/components/console/project-delete"
import { ProjectHead, ProjectPage } from "@/components/console/project-page"
import {
  BoxInputController,
  KindInputController,
  ProjectEditFields,
  LineInputController,
  ProjectFields,
  ProjectFoot,
  ProjectForm,
  ProjectNameInputController,
  ProjectWindow,
} from "@/components/console/project-form-lazy"
import { Chip, LABEL, SEED, ago } from "@/components/console/ticket-bits"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { useTicketTallies, type Tally } from "@/lib/board-store"
import { counted, t, useT } from "@/lib/i18n"
import { repositoryName, shortPath } from "@/lib/places"
import { KINDS, filtering, keeps } from "@/lib/project-search"
import { carrying, layoutOf, useLayoutInTheAddress } from "@/lib/resource-view"
import { useRoute } from "@/lib/router"
import type { Project, Projects } from "@/lib/types"
import { cn } from "@/lib/utils"
import { settingsHref } from "@/resources/settings"
import { tickets } from "@/resources/tickets"

/* The projects, declared once for react-resource-view.
 *
 * They were a pane that only read: a list of what this installation knows of,
 * and a link out to Notion for anything you wanted to change. But a project is
 * where every ticket of that project starts from — its repository, and the
 * brief that gives an answer your voice rather than nobody's — so it is worth
 * opening, and worth changing without leaving the console.
 *
 * Which makes it a resource like the board: a list, a page per record, a form
 * that writes it back. It is drawn in two layouts, and the pair is the point —
 * **cards** to look at a workspace you half remember, since a project is
 * recognised by its name and its shape rather than read; **a table** to compare
 * them, because "which of these eleven has no repository" is a question a grid
 * of cards will not answer. The package holds both and the address carries
 * which one you are on, so the layout you work in is the one that comes back.
 *
 * Three sources still, as the pane had them: the board's own database, the
 * `[projects]` table of the configuration, and where the repository turned out
 * to be. A project the file names and the board has never heard of has no page
 * to open — it is a line in `config.toml` — so it is addressed here by its name
 * under a `config:` prefix, and its page says where it is really edited. Every
 * project is clickable; only the ones that are a page are written from here.
 */

// A chunk of its own: only the split view shows it, and it imports this file.
const ProjectAside = React.lazy(() =>
  import("@/components/console/project-panel").then((module) => ({ default: module.ProjectAside }))
)

export const PROJECTS = "projects"

/** A project as the views hold it: the row, an IRI, and the two cells a table reads. */
export type ProjectItem = Project & {
  "@id": string
  "@type": string
  /** The brief, on the page of the ones that have a page. */
  content?: string
  /** `kind`, in the words the console says it in. */
  work: string
  /** The path this machine finds it at, whoever declared it. */
  where: string
}

/** What the console writes about a project: the page's columns, and the brief. */
export interface ProjectWrite {
  id?: string
  name?: string
  repository?: string
  path?: string
  content?: string
  /** What it does, its kind and its public address. */
  description?: string
  kind?: string
  site?: string
}

/** A project the configuration names and the board has never heard of. */
const FILE = "config:"

/** How a row is addressed: its page, or its name where there is no page. */
export const idOf = (project: Project): string => project.id || `${FILE}${project.name}`

/** Whether that address is a page — the only kind this console writes to. */
export const isAPage = (id: string): boolean => Boolean(id) && !id.startsWith(FILE)

const item = (project: Project & { content?: string }): ProjectItem => ({
  ...project,
  id: idOf(project),
  "@id": `/api/projects/${idOf(project)}`,
  "@type": PROJECTS,
  work: project.kind === "code" ? t("code work") : t("document work"),
  where: project.located ?? (project.configured || project.path || ""),
})

/* -- what the list last read ---------------------------------------------- */

/* The payload says two things a row does not: where repositories are looked
 * for, and what a project the file alone names is. Both are read outside the
 * row that carries them — the foot of the list, and the page of a project with
 * no page — so what the server last said is kept here, the way the settings
 * keep their description. */

let drawn: Projects | null = null
const listeners = new Set<() => void>()

function publish(fresh: Projects) {
  drawn = fresh
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** What the list last read, redrawn with it. */
export function useProjects(): Projects | null {
  return React.useSyncExternalStore(subscribe, () => drawn)
}

/** What was last read, for what reads it outside a component: the schedules' search. */
export const projectsRead = (): Projects | null => drawn

let asked: Promise<Projects> | null = null

/** The list, for a page that only wants the names: what was last read, or one
 * request shared by whoever asks while it is out. */
export function projectsOnce(): Promise<Projects> {
  return drawn ? Promise.resolve(drawn) : readAgain()
}

/* The list, read again — but once for everybody who asks while it is out: the
 * list itself, the names a schedule's row waits for, the palette, a project
 * written to and the list reading itself again after it, in the same instant. */
function readAgain(): Promise<Projects> {
  asked ??= api
    .projects()
    .then((fresh) => {
      publish(fresh)
      return fresh
    })
    .finally(() => {
      asked = null
    })
  return asked
}

/* What the tickets of a project come to, counted on the board the console
 * holds rather than asked of the server with the list. The list is drawn as
 * soon as it is read; until the first board arrives, the count is a skeleton
 * in its place. */
const NONE: Tally = { count: 0, ready: 0, running: 0, review: 0, edited: "" }

export function useTally(name: string): Tally | null {
  const tallies = useTicketTallies()
  return tallies ? (tallies.get(name) ?? NONE) : null
}

/** How many tickets point at a project. */
export function useTicketCount(name: string): number | null {
  return useTally(name)?.count ?? null
}

/* -- the one just created -------------------------------------------------- */

/* A project created a moment ago is drawn first, and marked, for as long as
 * the page is open: it is the card somebody is about to use — its "+ Ticket" most of all —
 * and in its alphabetical place it may well be below the fold. */
let created = ""
const createdListeners = new Set<() => void>()

/** The project the console created last, by its page. */
export const lastCreated = () => created

export function useLastCreated(): string {
  return React.useSyncExternalStore(
    (listener) => {
      createdListeners.add(listener)
      return () => {
        createdListeners.delete(listener)
      }
    },
    () => created
  )
}

function markCreated(id: string) {
  created = id
  createdListeners.forEach((listener) => listener())
  // And open in the panel beside the list, where it has its "+ Ticket" ready.
  pick(id)
}

/** The list, the project just created first. */
const createdFirst = (rows: Project[]) => {
  const first = rows.find((project) => project.id === created)
  return first ? [first, ...rows.filter((project) => project !== first)] : rows
}

/** One project, from wherever it is held: its page, or the line that names it. */
export async function readProject(id: string): Promise<ProjectItem> {
  if (isAPage(id)) return item(await api.project(id))
  // No page to read: the row is a line in the file, and the list is where it
  // was read from. Read again rather than taken from what is held, so a link
  // opened cold — a tab that has never listed anything — answers too.
  const read = await api.projects()
  publish(read)
  const found = read.projects.find((project) => idOf(project) === id)
  if (!found) throw new Error(t("No project called “{{name}}”.", { name: id.slice(FILE.length) }))
  return item(found)
}

/* -- the forms ------------------------------------------------------------ */

/* What a project page holds, as a form.
 *
 * A label and the button are translated by the package as it draws them; the
 * sentence under a field and the greyed example in it are not — they are used
 * as they are given. Those are read from the dictionary as the field is drawn,
 * which is what the getters are for: the declaration is built once, and the
 * language can change after it.
 */
/* In three groups, in the words the "New project" window uses for the same
 * fields — "Name", "GitHub", "Local folder" — where it said "Project" over the
 * name and "Where it is" over the folder: the project — its description, its
 * type and its site with it, which the window asks for too and a page is
 * corrected in as often — where its code is, and the brief. A repository and a
 * site are checked as they are typed, rather than by the server once the
 * drawer is sent. */
const REPOSITORY = /^([\w.-]+\/[\w.-]+|https?:\/\/\S+|git@\S+:\S+|ssh:\/\/\S+)$/
/** A public address, as the server takes it: http or https, a host, no space. */
const SITE = /^https?:\/\/[^\s/?#]+\S*$/

const editForm: FormInterface = {
  label: { submit: "Save" },
  components: { formInputs: ProjectEditFields },
  groupOption: {
    itemGroups: [
      { group: "project", title: "The project", order: 1 },
      {
        group: "code",
        title: "Where its code is",
        get description() {
          return t("One of the two is enough. A writing project has neither: its tickets come back as a document.")
        },
        order: 2,
      },
      { group: "brief", title: "The brief", order: 3 },
    ],
  },
  inputs: {
    name: {
      label: "Name",
      groups: ["project"],
      get description() {
        return t("What the board calls it. A ticket points at this page, not at this name.")
      },
      required: true,
      validator: (value: unknown) => {
        if (!String(value ?? "").trim()) throw new Error(t("A project needs a name."))
        return value
      },
    },
    description: {
      label: "Description",
      groups: ["project"],
      get placeholder() {
        return t("What the project does, in one sentence")
      },
    },
    kind: {
      label: "Type",
      groups: ["project"],
      controller: KindInputController,
      get valueOptions() {
        return [
          { value: "code", label: t("Code") },
          { value: "document", label: t("Writing") },
        ]
      },
    },
    site: {
      label: "Site",
      groups: ["project"],
      placeholder: "https://",
      validator: (value: unknown) => {
        const said = String(value ?? "").trim()
        if (said && !SITE.test(said)) throw new Error(t("Write the whole address, from https://."))
        return value
      },
    },
    repository: {
      label: "GitHub",
      groups: ["code"],
      get description() {
        return t("owner/repo, or the clone URL.")
      },
      placeholder: "owner/repo",
      validator: (value: unknown) => {
        const said = String(value ?? "").trim()
        if (said && !REPOSITORY.test(said)) throw new Error(t("Write it as owner/repo, or paste the clone URL."))
        return value
      },
    },
    path: {
      label: "Local folder",
      groups: ["code"],
      get description() {
        return t(
          "Only needed where the repository cannot be found on its own. Worktrees are made beside it, never in it."
        )
      },
      get placeholder() {
        return t("~/workspace/that-repository")
      },
    },
    content: {
      label: "The brief",
      groups: ["brief"],
      get description() {
        return t(
          "The audience, the voice, the conventions, the things never to do. Every ticket of this project is told it before it is told the ticket."
        )
      },
      // Shown in the empty editor: a page of standing instructions, which is
      // not the same thing as a message.
      get placeholder() {
        return t("Write it as you would brief somebody joining the project.")
      },
      controller: MarkdownInputController,
    },
  },
}

/* A new project: drawn as a new idea is (see `project-form.tsx`), with the
 * columns of the projects database in the order its page has them — name,
 * description, then where its code is, its public address, and the brief that
 * is its body. Only one of the repository and the folder is in view at a time;
 * either is enough. */
const createForm: FormInterface = {
  components: { formDecorator: ProjectForm, formInputs: ProjectFields, formSubmitAction: ProjectFoot },
  label: {
    get success() {
      return t("Project created")
    },
  },
  inputs: {
    name: {
      label: "Name",
      required: true,
      controller: ProjectNameInputController,
      get placeholder() {
        return t("Project name")
      },
    },
    description: {
      label: "Description",
      controller: LineInputController,
      get placeholder() {
        return t("What the project does, in one sentence")
      },
    },
    kind: {
      label: "Type",
      controller: KindInputController,
      defaultValue: "code",
      get valueOptions() {
        return [
          { value: "code", label: t("Code") },
          { value: "document", label: t("Writing") },
        ]
      },
    },
    repository: {
      label: "GitHub",
      controller: BoxInputController,
      placeholder: "owner/repo",
    },
    path: {
      label: "Local folder",
      controller: BoxInputController,
      get placeholder() {
        return t("~/workspace/that-repository")
      },
    },
    site: {
      label: "Site",
      controller: BoxInputController,
      placeholder: "https://",
    },
    content: {
      label: "The brief",
      get placeholder() {
        return t("Conventions, context, instructions — what every ticket of this project is told first.")
      },
      controller: MarkdownInputController,
    },
  },
}

/* Over the form opened anywhere but on its page — at its own address, say — the
 * way to that page: the pictures, the brief as it reads and the way to Notion
 * are there and nowhere else. Not over the form opened from that page, which
 * would be a link to where you are.
 *
 * The attribute is how the stylesheet knows the drawer holds a project's
 * form, to give it the whole screen on a phone: see `index.css`. */
function ToThePage() {
  const context = useCurrentViewResourceContext()
  const { params } = useRoute()
  const id = String(context.id ?? "")
  const here = params.resourceAction === ActionList.read && String(params.id ?? "") === id
  return (
    <div data-project-form>
      {id && !here ? (
        // Clear of the drawer's close button, drawn over the top right corner.
        <p className="text-muted-foreground mb-4 pr-10 text-xs">
          <Link
            to={generateLinkByResource({ resource: context.resource, resourceAction: ActionList.read, id })}
            className="underline underline-offset-2"
          >
            {t("Open the project's page")}
          </Link>{" "}
          — {t("its pictures, the brief as it reads, and the way to Notion.")}
        </p>
      ) : null}
    </div>
  )
}

/* -- one card, one row --------------------------------------------------- */

/* A project in the list is one link, to its page.
 *
 * It was a card with a name to click and a button under it to open, then a
 * name that opened the form in a drawer — and between the two, a card most of
 * which did nothing. The whole card is now an `<a>` to the project's page, so
 * a click anywhere goes there, a middle click or Ctrl+click opens it in a
 * tab, and Tab then Enter reaches it from the keyboard. The form is the page's
 * edit button away.
 *
 * Which leaves no room for a link inside it: the repository is said, not
 * linked — the page links it. The cards are drawn here rather than in the
 * package's frame, which adds a row of buttons under each and lets a card
 * stop at its own height; these fill the row they are in, and keep what
 * varies (a path, a status) to a line that is there or not. */

/** The two kinds of work, said as a badge: code in the accent, writing quieter. */
export function KindBadge({ project }: { project: ProjectItem }) {
  const code = project.kind === "code"
  return (
    <Badge
      variant="outline"
      className={cn(
        "rounded-full px-1.5 py-0 text-[0.65rem] font-medium",
        code ? "border-primary/40 text-primary" : "text-muted-foreground"
      )}
    >
      {code ? t("Code") : t("Writing")}
    </Badge>
  )
}

/* GitHub's mark, which lucide no longer draws: a repository on GitHub is
 * recognised by it before its name is read. */
function GitHubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden className={className}>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  )
}

/** Where the work happens, in one line each: the repository, and the path only where one is set. */
export function Whereabouts({ project }: { project: ProjectItem }) {
  const repository = repositoryName(project.repository ?? "")
  return (
    <div className="text-muted-foreground flex min-w-0 flex-col gap-1 text-xs">
      {repository ? (
        <span className="flex min-w-0 items-center gap-1.5" title={project.repository}>
          {repository.href.startsWith("https://github.com/") ? (
            <GitHubMark className="size-3.5 shrink-0" />
          ) : (
            <FolderGit2 className="size-3.5 shrink-0" />
          )}
          <span className="truncate font-mono">{repository.name}</span>
        </span>
      ) : project.kind !== "code" ? (
        <span className="flex min-w-0 items-center gap-1.5">
          <FileText className="size-3.5 shrink-0" />
          <span className="truncate">{t("Produces documents")}</span>
        </span>
      ) : null}
      {project.where ? (
        <span className="flex min-w-0 items-center gap-1.5" title={project.where}>
          <Folder className="size-3.5 shrink-0" />
          <span className="truncate font-mono">{shortPath(project.where)}</span>
        </span>
      ) : null}
    </div>
  )
}

/** The three columns a card counts, in the few words it has room for. */
const STATUS = {
  ready: "{{count}} ready",
  running: "{{count}} running",
  review: "{{count}} in review",
} as const

/** How many tickets, always; and, where there are any, how many wait, run and wait for a review. */
export function TicketTally({ project, withStatuses = true }: { project: ProjectItem; withStatuses?: boolean }) {
  const tally = useTally(project.name)
  if (!tally) return <Skeleton className="h-3 w-16" />
  return (
    <span className="text-muted-foreground inline-flex min-w-0 items-center gap-3 text-xs tabular-nums">
      <span className="text-foreground/80 whitespace-nowrap">
        {counted(tally.count, "{{count}} ticket", "{{count}} tickets")}
      </span>
      {withStatuses
        ? (["ready", "running", "review"] as const).map((key) =>
            tally[key] ? (
              <span key={key} className="inline-flex items-center gap-1 whitespace-nowrap" title={t(LABEL[key])}>
                <span className={cn("size-1.5 rounded-full", SEED[key])} />
                {t(STATUS[key], { count: String(tally[key]) })}
              </span>
            ) : null
          )
        : null}
    </span>
  )
}

/** When the last of its tickets moved, said the way a card says it. */
export function LastActivity({ project }: { project: ProjectItem }) {
  const edited = useTally(project.name)?.edited ?? ""
  const said = edited ? ago(edited) : ""
  if (!said) return null
  return (
    <span className="text-muted-foreground inline-flex items-center gap-1 text-xs whitespace-nowrap" title={edited}>
      <Clock className="size-3" />
      {said}
    </span>
  )
}

/** What the hover and the keyboard's focus look like on a link that is a whole card or row. */
const REACHABLE =
  "outline-none transition-colors focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:border-ring"

/** The “…” of a card or a row, beside its link and not inside it: a menu in an `<a>` is a link click.
 * Only for a project that is a page — a line of `config.toml` is not deleted from here. */
export function RowMenu({ project, onDeleted, className }: { project: ProjectItem; onDeleted: () => void; className?: string }) {
  const tickets = useTicketCount(project.name)
  if (!isAPage(project.id)) return null
  return <ProjectMenu project={project} tickets={tickets} onDeleted={onDeleted} className={className} />
}

/** “+ Ticket”, beside the link of a card or a row and not inside it: the dialog is the dashboard's
 * “New ticket”, with the project already in its field — and none to point at for a line of `config.toml`. */
export function NewTicket({ project, className }: { project: ProjectItem; className?: string }) {
  const link = useViewLink({ resource: tickets, action: "create" })
  if (!isAPage(project.id)) return null
  return (
    <div className={className}>
      <Link
        to={carrying(link.to, { project: project.id })}
        onClick={link.onOpen}
        data-project-new-ticket
        className={cn(buttonVariants({ variant: "outline", size: "xs" }), "bg-card whitespace-nowrap")}
      >
        <Plus />
        {t("Ticket")}
      </Link>
    </div>
  )
}

function ProjectCard({ project, onDeleted }: { project: ProjectItem; onDeleted: () => void }) {
  const fresh = useLastCreated() === project.id
  const card = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    if (fresh) card.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [fresh])
  return (
    <div ref={card} className="relative h-full">
      <Link
        to={projectHref(project.id)}
        data-project-card
        data-fresh={fresh || undefined}
        className={cn(
          "group bg-card flex h-full min-w-0 flex-col gap-3 rounded-2xl border p-4",
          "hover:border-primary/50 hover:bg-accent/40",
          fresh && "border-primary ring-primary/30 ring-[3px]",
          REACHABLE
        )}
      >
        <div className={cn("flex min-w-0 items-center gap-3", isAPage(project.id) && "pr-24")}>
          <ProjectThumb project={project} className="size-10" />
          <div className="flex min-w-0 flex-1 flex-col items-start gap-1">
            <span className="w-full truncate text-[0.95rem] leading-snug font-semibold" title={project.name}>
              {project.name}
            </span>
            <span className="flex flex-wrap items-center gap-1.5">
              <KindBadge project={project} />
              {project.source === "config" ? (
                <Chip className="rounded-full px-1.5 py-0 text-[0.65rem]">{t("from the configuration")}</Chip>
              ) : null}
            </span>
          </div>
        </div>

        <Whereabouts project={project} />

        <div className="mt-auto flex min-w-0 items-center justify-between gap-3 border-t pt-3">
          <TicketTally project={project} />
          <LastActivity project={project} />
        </div>
      </Link>
      <NewTicket project={project} className="absolute top-3 right-11" />
      <RowMenu project={project} onDeleted={onDeleted} className="absolute top-2.5 right-2.5" />
    </div>
  )
}

/** The card layout: every card of a row as tall as the tallest, and nothing under them. */
function ProjectCards({ rows = [] }: ListComponentPropsInterface) {
  const { fetchData } = useCurrentViewResourceContext()
  return (
    <div className="w-full">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
        {rows.map((row) => {
          const project = row.data as ProjectItem | undefined
          return project ? <ProjectCard key={project.id} project={project} onDeleted={() => void fetchData?.()} /> : null
        })}
      </div>
      <div className="mt-5">
        <ListPagination />
      </div>
    </div>
  )
}

/** The columns of a row, shared by the heading and every row so they line up. */
const COLUMNS =
  "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 px-4 md:grid-cols-[minmax(0,2fr)_6rem_minmax(0,1.5fr)_minmax(0,1.5fr)_7rem]"

/* The table layout: to compare projects rather than to look at them. Each row
 * is a link too, for the same reasons as a card — which a `<table>` cannot
 * have, so the rows are a list laid out as one. */
function ProjectRows({ rows = [] }: ListComponentPropsInterface) {
  const { fetchData } = useCurrentViewResourceContext()
  return (
    <div className="w-full">
      <div className="overflow-hidden rounded-md border">
        <div className={cn(COLUMNS, "text-muted-foreground border-b py-2 text-xs font-medium")} aria-hidden>
          <span>{t("Project")}</span>
          <span className="hidden md:block">{t("Type")}</span>
          <span className="hidden md:block">{t("Repository")}</span>
          <span className="hidden md:block">{t("On this machine")}</span>
          <span className="text-right">{t("Tickets")}</span>
        </div>
        <ul>
          {rows.map((row) => {
            const project = row.data as ProjectItem | undefined
            if (!project) return null
            const repository = repositoryName(project.repository ?? "")
            return (
              <li
                key={project.id}
                data-fresh={project.id === created || undefined}
                className={cn("relative border-b last:border-b-0", project.id === created && "bg-primary/10")}
              >
                <Link
                  to={projectHref(project.id)}
                  data-project-row
                  className={cn(COLUMNS, "hover:bg-accent/40 py-2.5 pr-28 text-sm", REACHABLE)}
                >
                  <span className="flex min-w-0 items-center gap-2.5">
                    <ProjectThumb project={project} className="size-8 rounded-md" />
                    <span className="truncate font-medium">{project.name}</span>
                  </span>
                  <span className="hidden md:block">
                    <KindBadge project={project} />
                  </span>
                  <span className="text-muted-foreground hidden truncate font-mono text-xs md:block">
                    {repository ? repository.name : "—"}
                  </span>
                  <span
                    className="text-muted-foreground hidden truncate font-mono text-xs md:block"
                    title={project.where || undefined}
                  >
                    {project.where ? shortPath(project.where) : "—"}
                  </span>
                  <span className="text-right">
                    <TicketTally project={project} withStatuses={false} />
                  </span>
                </Link>
                <NewTicket project={project} className="absolute top-1/2 right-11 -translate-y-1/2" />
                <RowMenu
                  project={project}
                  onDeleted={() => void fetchData?.()}
                  className="absolute top-1/2 right-2 -translate-y-1/2"
                />
              </li>
            )
          })}
        </ul>
      </div>
      <div className="mt-5">
        <ListPagination />
      </div>
    </div>
  )
}

/* -- the list beside its panel ----------------------------------------------- */

/* The third layout, and the one the list opens on: the projects on the left, one
 * line each, and on the right what the page around them holds — the global
 * context folded, and the project picked, with its repository, its folder, its
 * brief and its actions. Picking is not navigating: the page of a project is a
 * click further, from the panel, and the list stays where it was.
 *
 * Which project is picked is kept here, like the one just created, because the
 * list and the panel are two components of the package's frame that share
 * nothing else. */
let picked = ""
const pickedListeners = new Set<() => void>()

/** The project picked in the list, by its address; empty when none is. */
export function usePicked(): string {
  return React.useSyncExternalStore(
    (listener) => {
      pickedListeners.add(listener)
      return () => {
        pickedListeners.delete(listener)
      }
    },
    () => picked
  )
}

export function pick(id: string) {
  picked = id
  pickedListeners.forEach((listener) => listener())
}

/** The split layout's name in the address and in the switch. */
export const SPLIT = "split"

/** The list on the left: compact rows, each one a button that fills the panel. */
function ProjectMaster({ rows = [] }: ListComponentPropsInterface) {
  const chosen = usePicked()
  const fresh = useLastCreated()
  return (
    <div className="w-full">
      <ul className="flex flex-col gap-1.5">
        {rows.map((row) => {
          const project = row.data as ProjectItem | undefined
          if (!project) return null
          const on = chosen === project.id
          return (
            <li key={project.id}>
              <button
                type="button"
                data-project-item
                data-selected={on || undefined}
                data-fresh={fresh === project.id || undefined}
                aria-pressed={on}
                onClick={() => pick(on ? "" : project.id)}
                className={cn(
                  "bg-card flex w-full min-w-0 items-center gap-3 rounded-xl border px-3 py-2.5 text-left",
                  "hover:border-primary/50 hover:bg-accent/40",
                  on && "border-primary bg-accent/40 ring-primary/30 ring-[3px]",
                  REACHABLE
                )}
              >
                <ProjectThumb project={project} className="size-9" />
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-sm font-semibold" title={project.name}>
                      {project.name}
                    </span>
                    <KindBadge project={project} />
                  </span>
                  <span className="flex min-w-0 items-center justify-between gap-3">
                    <TicketTally project={project} withStatuses={false} />
                    <LastActivity project={project} />
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      <div className="mt-5">
        <ListPagination />
      </div>
    </div>
  )
}

/** A project's repository, by its owner and name, and a link to it where it has an address. */
export function Repository({ declared }: { declared?: string }) {
  const repository = repositoryName(declared ?? "")
  if (!repository) return <span className="font-mono text-xs">—</span>
  const name = (
    <span className="font-mono text-xs" title={declared}>
      {repository.name}
    </span>
  )
  if (!repository.href) return name
  return (
    <a href={repository.href} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
      {name}
    </a>
  )
}

/** Where this machine finds a project: whole, or cut from the left with the whole in its title.
 * Nowhere is said in words, and which words depends on whether it was ever to be cloned. */
export function Where({ path, kind }: { path?: string; kind?: string }) {
  if (!path)
    return (
      <span className="text-muted-foreground text-sm">
        {kind === "document" ? t("No repository: this project is a document") : t("Not cloned on this machine yet")}
      </span>
    )
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span className="min-w-0 font-mono text-xs break-all" title={path}>
        {path}
      </span>
      <CopyPath path={path} />
    </span>
  )
}

/** The path, on the clipboard. */
function CopyPath({ path }: { path: string }) {
  const [copied, setCopied] = React.useState(false)
  return (
    <Button
      variant="ghost"
      size="icon-xs"
      className="shrink-0"
      aria-label={t("Copy the path")}
      onClick={() => {
        void navigator.clipboard?.writeText(path).then(() => {
          setCopied(true)
          window.setTimeout(() => setCopied(false), 1500)
        })
      }}
    >
      {copied ? <Check /> : <Copy />}
    </Button>
  )
}

/* -- what sits around the list -------------------------------------------- */

/* What sits around the list depends on the layout.
 *
 * Beside it, in the split layout, the panel holds the standing context and the
 * project picked: see `ProjectAside`. The other two have no room on their side,
 * and the context used to be drawn over the list — a block as wide as the page,
 * most of it an empty state, between the menu and the projects the page is
 * named after. It is under them now: the projects first, then what covers all
 * of them. */
function ProjectsTop() {
  useLayoutInTheAddress(PROJECTS)
  const { viewVariant } = useCurrentViewResourceContext()
  if (viewVariant !== SPLIT) return null
  return (
    <React.Suspense fallback={null}>
      <ProjectAside />
    </React.Suspense>
  )
}

/** Under the list: how many are worked on in git and where their repositories are
 * looked for — then, in the two layouts with no panel, the standing context. */
function ProjectsBottom() {
  const { viewVariant } = useCurrentViewResourceContext()
  return (
    <>
      <ProjectsFoot />
      {viewVariant === SPLIT ? null : (
        <div className="mt-8">
          <ContextBlock />
        </div>
      )}
    </>
  )
}

/* How many of them are worked on in git, and where a repository is looked for —
 * which is the answer to half of "why was it not found". One line of small
 * print under the list: the count floated over the page's title, and the
 * folder was said by its configuration key. The key is still there, on hover,
 * for whoever wants to change it. */
function ProjectsFoot() {
  const read = useProjects()
  if (!read) return null
  const code = read.projects.filter((project) => project.kind === "code").length
  const counted = { count: String(code), total: String(read.projects.length) }
  return (
    <div className="text-muted-foreground mt-4 flex flex-col gap-1.5 text-xs sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4">
      <span className="inline-flex items-center gap-1.5">
        <FolderGit2 className="size-3.5 shrink-0" />
        {read.projects.length
          ? code > 1
            ? t("{{count}} of {{total}} projects have a repository", counted)
            : t("{{count}} of {{total}} projects has a repository", counted)
          : t("nothing yet")}
      </span>
      <span className="inline-flex min-w-0 items-center gap-1.5" title="runner.workspace_root">
        <Folder className="size-3.5 shrink-0" />
        <span className="min-w-0">
          {t("Repositories are looked for in {{path}}, and cloned there when they are nowhere.", {
            path: shortPath(read.workspace_root),
          })}
        </span>
      </span>
    </div>
  )
}

/** The list's own empty line: a board with no projects is not a broken board.
 *
 * With the one gesture this console has for it: a project is a page on the
 * board, or a name mapped to a path in the settings — and the second is here. */
function NoProject() {
  const { filterContext } = useListViewContext()
  if (filtering(filterContext.filter))
    return (
      <EmptyState
        icon={SearchX}
        title={t("No project matches")}
        action={
          <Button variant="outline" size="sm" onClick={() => filterContext.resetFilter({})}>
            <X />
            {t("Clear the search")}
          </Button>
        }
      >
        {t("Other words, or another type, and they will be back.")}
      </EmptyState>
    )
  return (
    <EmptyState
      robot="sleep"
      action={
        <Link to={settingsHref("projects")} className={buttonVariants({ variant: "outline", size: "sm" })}>
          {t("Map a project to a folder")}
        </Link>
      }
    >
      {t("No project yet — a ticket without one comes back as a document.")}
    </EmptyState>
  )
}

/* -- the declaration ------------------------------------------------------ */

/* The search over the list: the words of a name (or of a type), and one of the
 * two types. The labels are read from the dictionary as the bar is drawn, for
 * a screen reader: the box and the button say what they are, as the board's
 * search bar does, and a row of two labels over two fields was the tallest
 * thing on the page. The type is one of the board's filter buttons (see
 * `filter-bar.tsx`), beside the box, under it on a phone. */
const TypeFilter: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const t = useT()
  return (
    <FilterSelect
      label={t("Type")}
      data-slot="projects-type-filter"
      value={String(formInput.value ?? "")}
      onChange={(value) => onChange({ ...formInput, value })}
      options={[
        { value: "", label: t("All types") },
        ...KINDS.map((kind) => ({ value: kind, label: kind === "code" ? t("code work") : t("document work") })),
      ]}
    />
  )
}

const formFilter: FormInterface = {
  components: { formInputs: listFilters({ lead: "q", grow: true }) },
  inputs: {
    q: {
      label: "Search",
      get placeholder() {
        return t("Search a project")
      },
    },
    type: { label: "Type", controller: TypeFilter },
  },
}

export const projects = createViewResource<ProjectItem, ProjectWrite>(PROJECTS, {
  name: "Projects",
  path: "/api/projects",
  icon: FolderGit2,
  // A project page is made here, in Notion, or by a line in `config.toml`.
  // Deleting one has a dialog of its own (see `project-delete.tsx`).
  permissions: { delete: false, export: false },

  repository: {
    getCollection: async (filter) => {
      const read = await readAgain()
      return {
        data: createResourceCollection({
          id: "/api/projects",
          items: createdFirst(read.projects)
            .map((project) => item(project))
            .filter((row) => keeps(row, filter)),
        }),
      } as never
    },
    // What the server says when it fails is the page's to say (`loadError`):
    // "no such route" and "no project with id …" are two different afternoons.
    getItem: async ({ id }) => ({ data: await readProject(String(id)) }),
    updateItem: async (patch) => {
      const id = String(patch.id ?? "")
      if (!isAPage(id))
        throw new Error(
          t("This project is a line in config.toml; it is changed in the settings.")
        )
      const kind = patch.kind === "document" ? "document" : "code"
      const written = await api.saveProject(id, {
        name: patch.name ?? "",
        description: patch.description ?? "",
        kind,
        // A writing project has neither, whatever the drawer still holds.
        repository: kind === "code" ? (patch.repository ?? "") : "",
        path: kind === "code" ? (patch.path ?? "") : "",
        site: patch.site ?? "",
        content: patch.content ?? "",
      })
      // The list is drawn from what was last read, and a rename that only showed
      // on the page you renamed it on would be a rename made twice.
      await api.projects().then(publish)
      return { data: item(written) }
    },
    createItem: async (fresh) => {
      const kind = fresh.kind === "document" ? "document" : "code"
      const written = await api.createProject({
        name: String(fresh.name ?? ""),
        description: String(fresh.description ?? ""),
        kind,
        // A writing project has neither, whatever the form still holds.
        repository: kind === "code" ? String(fresh.repository ?? "") : "",
        path: kind === "code" ? String(fresh.path ?? "") : "",
        site: String(fresh.site ?? ""),
        content: String(fresh.content ?? ""),
      })
      markCreated(written.id)
      // Read again, for the count over the list and the names everywhere else.
      await readAgain().catch(() => undefined)
      return { data: item(written) }
    },
    removeItem: async () => {
      // Deleting asks for more than an id — the project's name, and what becomes
      // of its tickets — so it has a dialog of its own: see `project-delete.tsx`.
      throw new Error("a project is deleted through its confirmation dialog")
    },
  },

  views: {
    list: {
      description:
        "What the tickets are about: where the work happens, and what conventions hold there. One with no repository is not a mistake — its tickets come back as a document.",
      /* The three layouts, each at the width of the page. Their labels go through the dictionary as the tabs
       * are drawn, and their address is their type: `cards`, `table`, in
       * every language. */
      layouts: [
        layout.cards({ id: SPLIT, label: "split", icon: Columns2, fullWidth: true, components: { list: ProjectMaster } }),
        layout.cards({ label: "cards", icon: LayoutGrid, fullWidth: true, components: { list: ProjectCards } }),
        layout.table({ label: "table", fullWidth: true, components: { list: ProjectRows } }),
      ],
      // A card, or a row, is a link to the project's page: no button under it.
      rowActions: [],
      // The search is the package's own: it lives in the address (`q`, `type`),
      // and the rows are kept by `keeps`, as the list is read.
      filters: formFilter,
      components: { top: ProjectsTop, bottom: ProjectsBottom, empty: NoProject },
    },
    create: {
      title: "New project",
      buttonLabel: "New project",
      form: createForm,
      // In the middle of the list, as tall as what it holds — a sheet from the
      // bottom on a phone — and closed by the form once the project exists, or
      // replaced by the first ticket's (see `ProjectForm`).
      open: open.custom({ type: "project-new", component: ProjectWindow }),
      afterSave: "stay",
      // No card before the server's: the id is the page's, and the repository
      // the server's own spelling of it.
      optimistic: false,
    },
    read: {
      title: "Project",
      // The dashboard's width and margins: the page is a header, figures and a
      // board, not a form to keep in a column.
      fullWidth: true,
      // The layout's header, in the same shapes but written for a project: its
      // short id, and what only a project has in it.
      components: { view: ProjectPage, navigation: ProjectHead },
    },
    update: {
      title: "Edit the project",
      // What the button that opens this form says. Left to the package it is
      // the action's own name, which reads as a lower-case "update".
      buttonLabel: "Edit",
      form: editForm,
      // Against the edge and at full height: the brief is the field that is
      // actually written here, and it is a page of text.
      open: "drawer",
      // The page worth opening from here is the project's, not this form's
      // own: `ToThePage` is the link to it.
      expandable: false,
      components: { top: ToThePage },
    },
  },
})

/** Where the projects are, in the layout they were last worked in. */
export const projectsHref = () =>
  generateLinkByResource({
    resource: projects,
    resourceAction: ActionList.list,
    viewVariantId: layoutOf(PROJECTS),
  })

/** "New project", over the list of projects — the one place its window is drawn in. */
export const newProjectHref = () =>
  generateLink({
    resource: projects,
    resourceAction: ActionList.list,
    scope: projects.scope,
    viewVariantId: layoutOf(PROJECTS),
    childViewResource: { resource: projects, resourceAction: ActionList.create },
  })

/** Where one project is. */
export const projectHref = (id: string) =>
  generateLinkByResource({ resource: projects, resourceAction: ActionList.read, id })
