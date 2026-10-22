import * as React from "react"
import { ListChecks, Trash2 } from "lucide-react"
import { ActionList } from "react-data-form"
import { ViewResourceContextProvider, generateLink } from "react-resource-view"

import { LanguagePicker } from "@/components/console/language-picker"
import type { SaveNote } from "@/components/console/settings-bits"
import { Rich } from "@/components/console/text"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useConsole } from "@/hooks/use-console"
import { api } from "@/lib/api"
import { counted, useT } from "@/lib/i18n"
import { SCOPE } from "@/lib/resource-view"
import {
  cardId,
  currentSettings,
  inputName,
  sectionsIn,
  takeAsked,
  useAsked,
  useSettingsRevision,
} from "@/lib/settings-store"
import type { Disk, SettingSection } from "@/lib/types"
import { pairResources, type PairTable } from "@/resources/pairs"
import { settingsHref } from "@/resources/settings"

/* The pages of the settings: the state card, the cards of each group and the
 * lists of rows. Drawn when a settings page is opened — `resources/settings`
 * keeps the declaration, and this, being most of its weight, is fetched
 * with the page rather than with the console, whose first load has a budget.
 */

/* -- the general page's state ------------------------------------------------ */

/** A size the way the runner's `doctor` says it: 25 GB, 764 MB, 12 kB. */
function bytes(size: number): string {
  const units = ["B", "kB", "MB", "GB"]
  let unit = 0
  while (size >= 1000 && unit < units.length - 1) {
    size /= 1000
    unit += 1
  }
  return `${unit === 0 || size >= 10 ? Math.round(size) : size.toFixed(1)} ${units[unit]}`
}

/* The room the runner takes, and the button that applies its retention now.
 * A run tidies once a day on its own — the button is for the day you would
 * rather not wait. */
function DiskLine() {
  const t = useT()
  const [disk, setDisk] = React.useState<Disk | null>(null)
  const [cleaning, setCleaning] = React.useState(false)
  const [said, setSaid] = React.useState<{ text: string; bad: boolean } | null>(null)

  React.useEffect(() => {
    let live = true
    api.disk().then(
      (read) => live && setDisk(read),
      () => undefined
    )
    return () => {
      live = false
    }
  }, [])

  if (!disk) return <span className="text-muted-foreground">…</span>

  const clean = async () => {
    setCleaning(true)
    setSaid(null)
    try {
      const done = await api.clean()
      setDisk(done)
      setSaid({
        text: t("{{removed}} folder(s) and {{logs}} log(s) removed, {{freed}} freed.", {
          removed: String(done.removed),
          logs: String(done.logs),
          freed: bytes(done.freed),
        }),
        bad: false,
      })
    } catch (error) {
      setSaid({ text: error instanceof Error ? error.message : String(error), bad: true })
    } finally {
      setCleaning(false)
    }
  }

  const rule =
    disk.retention_days <= 0
      ? t("Nothing is tidied on its own: logs are kept forever.")
      : disk.clean_done_worktrees
        ? counted(
            disk.retention_days,
            "Tidied once a day: logs, and done tickets’ folders, older than {{count}} day.",
            "Tidied once a day: logs, and done tickets’ folders, older than {{count}} days."
          )
        : counted(
            disk.retention_days,
            "Logs older than {{count}} day are dropped once a day.",
            "Logs older than {{count}} days are dropped once a day."
          )

  return (
    <div className="flex flex-col gap-1.5" data-testid="disk">
      <span>
        <span className="font-medium">{bytes(disk.total)}</span>
        <span className="text-muted-foreground">
          {" — "}
          {t("worktrees {{worktrees}} · logs {{logs}} · scratch {{scratch}}", {
            worktrees: bytes(disk.sizes.worktrees),
            logs: bytes(disk.sizes.logs),
            scratch: bytes(disk.sizes.scratch),
          })}
        </span>
      </span>
      {disk.free_mb !== null && disk.disk_mb !== null ? (
        <span className="text-muted-foreground text-xs" data-testid="disk-free">
          {t("{{free}} free of {{total}} on this disk", {
            free: bytes(disk.free_mb * 1_000_000),
            total: bytes(disk.disk_mb * 1_000_000),
          })}
        </span>
      ) : null}
      {disk.short ? (
        <span className="text-destructive text-xs font-medium" role="alert" data-testid="disk-short">
          {t("Low disk space: under {{minimum}} free — no ticket is started until room is back.", {
            minimum: bytes(disk.min_free_disk_mb * 1_000_000),
          })}
        </span>
      ) : null}
      <span className="text-muted-foreground text-xs">{rule}</span>
      {disk.worktrees.length ? (
        <span className="text-muted-foreground text-xs" data-testid="disk-worktrees">
          {t("Heaviest working copies: {{list}}", {
            list: disk.worktrees
              .slice(0, 5)
              .map((entry) => `${entry.name} ${bytes(entry.size)}`)
              .join(" · "),
          })}
        </span>
      ) : null}
      <span className="flex flex-wrap items-center gap-2">
        <Button size="xs" variant="outline" onClick={() => void clean()} disabled={cleaning}>
          <Trash2 />
          {cleaning ? t("Cleaning up…") : t("Clean up")}
        </Button>
        {said ? (
          <span className={said.bad ? "text-destructive text-xs" : "text-muted-foreground text-xs"}>
            {said.text}
          </span>
        ) : null}
      </span>
    </div>
  )
}

/* What the first connection ended on, kept: the provider, the board, GitHub,
 * the projects, the channels and where this runs, each with its state and a
 * link to the card that changes it. Folded by default — it asks the CLI and
 * GitHub who they are, which is a second or two nobody needs on every visit. */
function Overview() {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  return (
    <div data-testid="settings-overview">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="xs" variant="outline" onClick={() => setOpen(!open)} aria-expanded={open}>
          <ListChecks />
          {open ? t("Hide the summary") : t("What this console runs on")}
        </Button>
        <a href="/setup" className="text-muted-foreground text-xs underline underline-offset-2">
          {t("Go through the first connection again")}
        </a>
      </div>
      {open ? (
        <div className="mt-3 flex flex-col gap-4">
          <React.Suspense fallback={null}>
            <LazySetupSummary change={(row) => <a href={settingsHref(row.section)}>{t("Change")}</a>} />
            <LazyDiagnosis />
            <LazyServiceLog />
          </React.Suspense>
        </div>
      ) : null}
    </div>
  )
}

/* The top of the general page: which version runs, which file this page
 * writes, the room the runner takes — what used to crowd the head of every
 * page, said once, where somebody looking at the runner itself looks. */
function StateCard() {
  const t = useT()
  const { runner } = useConsole()
  const drawn = currentSettings()
  const line = (label: string, value: React.ReactNode) => (
    <div className="grid gap-1 py-3 first:pt-0 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-4">
      <dt className="font-semibold">{label}</dt>
      <dd className="min-w-0">{value}</dd>
    </div>
  )
  return (
    <Card data-card="state" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
        <CardTitle className="text-base">{t("State")}</CardTitle>
        <CardDescription className="text-[13px]">
          {t("The runner as it stands on this machine.")}
        </CardDescription>
      </CardHeader>
      <CardContent className="px-5 pb-5 text-sm sm:px-6">
        <dl className="divide-y">
          {line(t("Version"), runner ? <span className="font-mono">v{runner.version}</span> : "…")}
          {line(
            t("Configuration file"),
            <span className="font-mono text-[13px] break-all" data-testid="settings-path">
              {drawn?.path}
            </span>
          )}
          {line(t("Disk space"), <DiskLine />)}
          {line(t("First connection"), <Overview />)}
        </dl>
      </CardContent>
    </Card>
  )
}

/* -- one page ------------------------------------------------------------- */

/** Whether a field or a card the search asked for is on this page. */
function onPage(group: string, target: string): boolean {
  return sectionsIn(group).some(
    (section) => section.key === target || section.fields.some((field) => field.name === target)
  )
}

/* The page's own extras to its cards: the browser's language on the languages
 * card — it is the browser's rather than the file's, so it is not a field of
 * the form, but it is a setting, and this is where somebody looks for one —
 * and the two cards that are lists of rows, each a resource of its own, drawn
 * as a resource is drawn: the package's table, its own dialogs. */
const extra = (section: SettingSection) =>
  section.key === "languages" ? <LanguagePicker /> : section.key === "validation" ? <OwnValidation /> : null

/* Above the four switches of the validation card: that they are not the whole
 * story, since a project may decide for itself — and which ones do, each a
 * link to the tab where it does. */
function OwnValidation() {
  const t = useT()
  useSettingsRevision()
  const owning = currentSettings()?.own_validation ?? []
  return (
    <p className="text-muted-foreground pt-1 pb-2 text-[13px] leading-relaxed" data-slot="own-validation">
      {t("A project can have its own automatic validation, in the Settings tab of its page.")}{" "}
      {owning.length ? (
        <>
          {t("Projects with their own, whatever these switches say:")}{" "}
          {owning.map((project, index) => (
            <React.Fragment key={project.id}>
              {index ? ", " : null}
              <a href={projectSettingsHref(project.id)} className="text-foreground underline underline-offset-2">
                {project.name || project.id}
              </a>
            </React.Fragment>
          ))}
          .
        </>
      ) : (
        t("None does today.")
      )}
    </p>
  )
}

/** A project's settings tab, written out rather than imported: projects.tsx imports this file. */
const projectSettingsHref = (id: string) =>
  `${generateLink({ scope: SCOPE, resourceId: "projects", resourceAction: ActionList.read, id })}&tab=settings`

function pairs(section: SettingSection) {
  if (!(section.pairs in pairResources)) return null
  return (
    <ViewResourceContextProvider
      resource={pairResources[section.pairs as PairTable]}
      resourceAction={ActionList.list}
    />
  )
}

export function GroupPage({ group }: { group: string }) {
  const revision = useSettingsRevision()
  const target = useAsked()
  const [note, setNote] = React.useState<SaveNote | null>(null)

  React.useEffect(() => {
    // A problem stays until it is read; a confirmation has been read by then.
    if (!note || note.bad) return
    const timer = window.setTimeout(() => setNote(null), 8000)
    return () => window.clearTimeout(timer)
  }, [note])

  React.useEffect(() => {
    // What a search or an old link asked for, once its block has unfolded —
    // which the blocks do in their own effects, before this one runs.
    if (!target || !onPage(group, target)) return
    const timer = window.setTimeout(() => {
      takeAsked()
      const found =
        document.querySelector<HTMLElement>(`[data-field="${inputName(target)}"]`) ??
        document.getElementById(cardId(target))
      if (!found) return
      found.scrollIntoView({ block: "center", behavior: "smooth" })
      found.querySelector<HTMLElement>("input, button[role=switch], button[role=combobox]")?.focus({
        preventScroll: true,
      })
      found.setAttribute("data-found", "")
      window.setTimeout(() => found.removeAttribute("data-found"), 1800)
    }, 80)
    return () => window.clearTimeout(timer)
  }, [group, target])

  return (
    <div className="flex max-w-5xl min-w-0 flex-col gap-5">
      {group === "general" ? <StateCard /> : null}
      {note ? (
        <Alert variant={note.bad ? "destructive" : "success"}>
          <AlertDescription>
            <Rich text={note.text} />
          </AlertDescription>
        </Alert>
      ) : null}
      {/* Keyed by the revision: a save reads the file again, and the fields of
          every page are redrawn from what it now says. */}
      <React.Suspense fallback={null}>
        <GroupForm
          key={revision}
          group={group}
          extra={extra}
          pairs={pairs}
          note={note}
          onSaved={setNote}
        />
      </React.Suspense>
    </div>
  )
}

/* The fields of the settings and what the console runs on: fetched with the page,
 * not with the console, whose first load has a budget. */
const GroupForm = React.lazy(() =>
  import("@/components/console/settings-bits").then((module) => ({ default: module.GroupForm }))
)
const LazySetupSummary = React.lazy(() =>
  import("@/components/console/setup").then((module) => ({ default: module.SetupSummary }))
)
const LazyDiagnosis = React.lazy(() =>
  import("@/components/console/setup").then((module) => ({ default: module.Diagnosis }))
)
const LazyServiceLog = React.lazy(() =>
  import("@/components/console/setup").then((module) => ({ default: module.ServiceLog }))
)
