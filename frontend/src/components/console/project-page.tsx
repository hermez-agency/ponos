import * as React from "react"
import { useLocation, useRouter } from "@tanstack/react-router"
import { ArrowLeft, ArrowUpRight, CopyIcon } from "lucide-react"
import { ActionList } from "react-data-form"
import { Link, ResourceViewButton, useCurrentViewResourceContext, useNavigate } from "react-resource-view"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { why } from "@/lib/api"
import { counted, useT } from "@/lib/i18n"
import { useRoute } from "@/lib/router"
import { cn } from "@/lib/utils"
import {
  NewTicket,
  Repository,
  Where,
  isAPage,
  pick,
  projectHref,
  projectsHref,
  useTicketCount,
  type ProjectItem,
} from "@/resources/projects"
import { settingsHref } from "@/resources/settings"

import { CONTEXT_ANCHOR } from "./context-block"
import { Eyebrow, Fact, Facts } from "./frame"
import { IdeasButton } from "./ideas-deck"
import { ProjectBrief } from "./project-brief"
import { ProjectMenu } from "./project-delete"
import { ProjectCover } from "./project-picture"
import { ProjectTickets } from "./project-tickets"
import { Robot } from "./robot"
import { ScopedIdeas } from "./scoped-ideas"
import { StatisticsBand } from "./statistics"
import { Away, Chip, reachable } from "./ticket-bits"

/* A project's own switches, a tab opened now and then: kept out of the first
 * load, which has a budget. */
const ProjectSettingsTab = React.lazy(() =>
  import("./project-settings").then((module) => ({ default: module.ProjectSettingsTab }))
)

/* Where the page of a project finds its project.
 *
 * On its own address, in the context the package gives the `read` view: the
 * record, or why it could not be read. Beside the list of projects, in the
 * panel — which is the same page, drawn in a column of the list's frame, where
 * the context is the list's: so the panel says it here instead, with the tab
 * it is on, which is kept from one project to the next rather than written in
 * an address that is the list's. */
interface Shown {
  project?: ProjectItem
  error?: boolean
  loadError?: unknown
  /** The tab, and the hand that changes it — beside the list only. */
  panel?: { tab: string; onTab: (tab: string) => void }
}

const ShownProject = React.createContext<Shown | null>(null)

/** The project to draw, and whether it is drawn in the panel. */
function useShown(): Shown & { resource: ReturnType<typeof useCurrentViewResourceContext>["resource"] } {
  const shown = React.useContext(ShownProject)
  const context = useCurrentViewResourceContext()
  if (shown) return { ...shown, resource: context.resource }
  return {
    project: context.data as ProjectItem | undefined,
    error: Boolean(context.error),
    loadError: context.loadError,
    resource: context.resource,
  }
}

/** The page of a project, beside the list: its header, then the page itself. */
export function ProjectInPanel({
  project,
  tab,
  onTab,
}: {
  project?: ProjectItem
  tab: string
  onTab: (tab: string) => void
}) {
  const shown = React.useMemo(() => ({ project, panel: { tab, onTab } }), [project, tab, onTab])
  return (
    <ShownProject.Provider value={shown}>
      <section data-project-panel className="bg-card flex min-w-0 flex-col gap-5 rounded-xl border p-4">
        <ProjectHead />
        <ProjectPage />
      </section>
    </ShownProject.Provider>
  )
}

/* One project, as a page.
 *
 * The `read` view of the projects resource: the page's cover and icon, what
 * the card said, and then the thing a card has no room for — the brief. Which is the reason to open a
 * project at all: it is not a description of the project, it is what every
 * ticket of that project is told before it is told the ticket.
 *
 * What sits above it — the way back, the name, the edit button — is the
 * layout's header, written for a project: see `ProjectHead` below.
 */

export function ProjectPage() {
  const context = useShown()
  const project = context.project
  const t = useT()
  const page = project ? isAPage(project.id) : false

  return (
    <div className="min-w-0">
      {!project ? (
        context.error ? (
          <div className="flex flex-col gap-1.5">
            <Robot state="error" size={56} className="mb-2" />
            <p className="text-destructive text-sm">{t("This project could not be read.")}</p>
            {/* And what the server answered, as it answered it: "no such route"
                and "no project with id …" are two different afternoons, and the
                sentence above alone tells neither. */}
            {context.loadError ? (
              <p className="text-muted-foreground font-mono text-xs">{why(context.loadError)}</p>
            ) : null}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <Robot state="thinking" size={56} className="mb-2" />
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="mt-2 h-20 w-full" />
            <Skeleton className="h-3 w-full" />
          </div>
        )
      ) : (
        <>
          {/* A project with a page has its pictures; one the configuration
              alone names has neither page nor pictures to show. */}
          {page ? <ProjectCover project={project} editable compact={Boolean(context.panel)} /> : null}

          {project.source === "config" || project.configured ? (
            <div className="flex flex-wrap items-center gap-1.5">
              {project.source === "config" ? <Chip>{t("from the configuration")}</Chip> : null}
              {project.configured && project.source === "board" ? (
                <Chip>{t("path set in the configuration")}</Chip>
              ) : null}
            </div>
          ) : null}

          <Facts className="mt-4 first:mt-0">
            <Fact label={t("repository")}>
              <Repository declared={project.repository} />
            </Fact>
            <Fact label={t("on this machine")}>
              <Where path={project.where} kind={project.kind} />
            </Fact>
          </Facts>

          <StatisticsBand project={project.name} />

          <ProjectTabs project={project}>
            {page ? (
              <ProjectBrief project={project} />
            ) : (
              <p className="text-muted-foreground max-w-prose text-sm leading-relaxed">
                {t(
                  "This project is a line in config.toml and has no page: the board has never heard of it, so there is nothing here to write a brief on."
                )}{" "}
                <Link to={settingsHref("projects")} className="underline underline-offset-2">
                  {t("Change its path in the settings.")}
                </Link>
              </p>
            )}
          </ProjectTabs>
        </>
      )}
    </div>
  )
}

/* The tabs of a project: its tickets, its ideas, its brief and its settings.
 *
 * The tickets come first, because a project is opened more often to see what is
 * being done on it than to reread what every ticket is told; the ideas next, as
 * what could be done on it — every one of them, thrown away included. The
 * settings last: what this project decides for itself against the runner's
 * settings, opened the day it should not be treated like the others. A project
 * the configuration alone names has no page for an idea to point at, and no
 * ideas tab; nor a page for its settings to be kept under, and no settings tab
 * either — no ticket points at it to be validated anyway. The one picked is written in the address (`&tab=brief`), so a
 * reload or a pasted link comes back to it; the tickets are the tab of an
 * address that says nothing, and of one that says something else. Beside the
 * list, the panel holds the tab instead (see `ProjectInPanel`), and a project
 * with no such tab is shown on its tickets without forgetting the one picked.
 * The facts and the statistics stay above the tabs.
 */
const TABS = ["tickets", "ideas", "brief", "settings"] as const
type Tab = (typeof TABS)[number]

function ProjectTabs({ project, children }: { project: ProjectItem; children: React.ReactNode }) {
  const t = useT()
  const { pathname, searchStr } = useLocation()
  const router = useRouter()
  const { params } = useRoute()
  const { panel } = useShown()
  const mine = params.resourceAction === ActionList.read && String(params.id ?? "") === project.id
  const named = panel ? panel.tab : mine ? new URLSearchParams(searchStr).get("tab") : null
  const ideas = isAPage(project.id)
  const tab: Tab =
    TABS.includes(named as Tab) && ((named !== "ideas" && named !== "settings") || ideas)
      ? (named as Tab)
      : "tickets"
  const pick = (value: string) => {
    if (panel) return panel.onTab(value)
    if (!mine) return
    const rest = searchStr
      .replace(/^\?/, "")
      .split("&")
      .filter((part) => part && !part.startsWith("tab="))
    router.history.replace(`${pathname}?${[...rest, `tab=${value}`].join("&")}`)
  }
  return (
    <Tabs value={tab} onValueChange={pick} className={cn("gap-4", panel ? "mt-4" : "mt-6")}>
      <TabsList className="w-full sm:w-fit">
        <TabsTrigger value="tickets" data-slot="project-tickets-tab">
          {t("Tickets")}
        </TabsTrigger>
        {ideas ? (
          <TabsTrigger value="ideas" data-slot="project-ideas-tab">
            {t("Ideas")}
          </TabsTrigger>
        ) : null}
        <TabsTrigger value="brief" data-slot="project-brief-tab">
          {t("Brief")}
        </TabsTrigger>
        {ideas ? (
          <TabsTrigger value="settings" data-slot="project-settings-tab">
            {t("Settings")}
          </TabsTrigger>
        ) : null}
      </TabsList>
      <TabsContent value="tickets">
        <ProjectTickets project={project} />
      </TabsContent>
      {ideas ? (
        <TabsContent value="ideas">
          <ScopedIdeas project={project.id.replace(/-/g, "")} name={project.name} find />
        </TabsContent>
      ) : null}
      <TabsContent value="brief">{children}</TabsContent>
      {ideas ? (
        <TabsContent value="settings">
          <React.Suspense fallback={null}>
            <ProjectSettingsTab project={project.id} />
          </React.Suspense>
        </TabsContent>
      ) : null}
    </Tabs>
  )
}

/* The top of the page is the layout's: the way back, the title, the line under
 * it and the actions, in the shapes react-resource-view draws them in on
 * every page of the console. The page drew its own on top of it — two ways
 * back, two titles, two edit buttons — so what only a project has is said in
 * that header instead: the kind of work above the name, and on the right the
 * page in Notion, how many tickets point at it, and the edit button.
 *
 * Written here rather than told to the package's, as the ticket's is (see
 * `TicketHead`): the package says the whole page id under the title —
 * `#0000000000000000000000000000cafe` — and a view replaces that line only
 * with the whole header. So this is the whole header: the short id, as the
 * ticket's, with a button that copies the long one.
 */
export function ProjectHead() {
  const { project, panel } = useShown()
  const t = useT()
  const page = project && isAPage(project.id) ? project.id.replace(/-/g, "") : ""
  const copy = () => {
    if (!page) return
    void navigator.clipboard
      ?.writeText(page)
      .then(() => toast.success(t("Copied"), { description: page }))
      .catch(() => {})
  }
  return (
    <header data-slot="admin-header" className="w-full">
      <div
        className={cn(
          "border-border flex flex-wrap items-end gap-x-6 border-b",
          panel ? "gap-y-3 pb-4" : "gap-y-4 pb-5"
        )}
      >
        <div className="min-w-0 flex-1">
          {/* Beside the list, the way back is the list itself: the panel
              offers the page alone instead, on the tab it is on. */}
          {panel ? null : (
            <Link
              to={projectsHref()}
              className="text-muted-foreground hover:text-foreground mb-1.5 inline-flex items-center gap-1 text-sm transition-colors"
            >
              <ArrowLeft className="size-4" />
              {t("Projects")}
            </Link>
          )}
          <ProjectTitle />
          {page ? (
            <p data-slot="project-id" className="text-muted-foreground mt-1 flex items-center gap-1 text-sm">
              {t("Project")} · <span className="font-mono">#{page.slice(-8)}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                onClick={copy}
                title={t("Copy the full id")}
                aria-label={t("Copy the full id")}
              >
                <CopyIcon />
              </Button>
            </p>
          ) : null}
          {panel && project ? (
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
              <Link
                to={projectHref(project.id, panel.tab)}
                data-project-open
                className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline-offset-2 hover:underline"
              >
                {t("Open the project's page")}
                <ArrowUpRight className="size-3.5" />
              </Link>
              {/* The panel's one header: the global context is a link back to
                  it, not a second one drawn over this. */}
              <Link
                to={`${projectsHref()}#${CONTEXT_ANCHOR}`}
                onClick={() => pick("")}
                data-slot="context-link"
                className="text-muted-foreground hover:text-foreground text-xs underline-offset-2 hover:underline"
              >
                {t("Inherits the global context ↑")}
              </Link>
            </div>
          ) : null}
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 md:w-auto">
          <ProjectActions />
        </div>
      </div>
    </header>
  )
}

/** The name, under the kind of work it is. */
export function ProjectTitle() {
  const { project, panel } = useShown()
  const t = useT()
  return (
    <div className="min-w-0">
      {project ? <Eyebrow>{project.work}</Eyebrow> : null}
      <h2 className={cn("truncate font-semibold tracking-tight", panel ? "text-xl" : "text-2xl")} title={project?.name}>
        {project ? project.name : t("Project")}
      </h2>
    </div>
  )
}

/**
 * What the header offers besides the way back.
 *
 * The edit button is the package's own, as the header would have drawn it:
 * the same form, the same drawer and the same toast as everywhere else. A
 * project the configuration alone names has no page to write to, so it gets
 * none — the page says where it is changed instead.
 */
export function ProjectActions() {
  const context = useShown()
  const project = context.project
  useT()
  const count = useTicketCount(project?.name ?? "")
  const navigate = useNavigate()
  if (!project) return null
  /** Where the project is really written, when that is somewhere a browser can go. */
  const away = reachable(project.url) ? project.url : ""
  return (
    <>
      <NewTicket project={project} />
      {away ? <Away label="Notion" href={away} /> : null}
      {isAPage(project.id) ? <IdeasButton project={project.id} name={project.name} /> : null}
      {count === null ? (
        <Skeleton className="h-5 w-16 rounded-full" />
      ) : count ? (
        <Chip>{counted(count, "{{count}} ticket", "{{count}} tickets")}</Chip>
      ) : null}
      {isAPage(project.id) ? (
        // One piece, so that on a phone the "…" wraps with the edit button
        // rather than alone on a line under it.
        <span className="flex items-center gap-2">
          <ResourceViewButton
            action={ActionList.update}
            resource={context.resource}
            id={project.id}
            data={project}
          />
          <ProjectMenu
            project={project}
            tickets={count}
            // Beside the list, the list is already there: the panel empties.
            onDeleted={() => (context.panel ? pick("") : void navigate({ to: projectsHref() }))}
          />
        </span>
      ) : null}
    </>
  )
}
