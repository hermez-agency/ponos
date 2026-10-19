import * as React from "react"
import { Folder, XIcon } from "lucide-react"
import {
  ActionList,
  InputControllerProvider,
  getFormInputsFromForm,
  useFormContext,
  type FormDecoratorPropsInterface,
  type InputControllerComponentInterface,
} from "react-data-form"
import { Link, useCurrentViewResourceContext, useNavigate, useViewLink, type OpenFrameProps } from "react-resource-view"

import { ChipsInputController, IdeaTitleInputController } from "@/components/console/idea-form"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { api } from "@/lib/api"
import { isMac } from "@/lib/hotkeys"
import { t, useT } from "@/lib/i18n"
import { carrying } from "@/lib/resource-view"
import type { ProjectCheck } from "@/lib/types"
import { cn } from "@/lib/utils"
import { idOf, lastCreated, projectHref, projectsOnce, useProjects } from "@/resources/projects"
import { tickets } from "@/resources/tickets"

/* "New project", drawn as "New idea" is: a window as tall as what is in it —
 * a sheet coming up from the bottom on a phone — the name the largest thing in
 * it, a line under it, then what decides how its tickets are worked, a row
 * each, and the button in a foot that stays in view.
 *
 * The fields are react-data-form's, declared in `resources/projects` and sent
 * to its `createItem`; only how each is drawn is said here, and with the idea
 * form's own pieces where they are the same thing — its title, its chips. Two
 * things are particular to a project. Its repository is said one of two ways,
 * GitHub or a folder on this machine, and the server says as it is typed what
 * either turns out to be (`api.checkProject`): cloned already, to be cloned at
 * the first ticket, or the GitHub repository a folder's `origin` names. And
 * "Create a first ticket" in the foot goes straight on to the ticket's form,
 * with the project already in it.
 */

/** Where a repository is said to be: on GitHub, or in a folder of this machine. */
type Source = "github" | "folder"

/** What the window keeps across the form, which is drawn again whenever its data is replaced —
 * a folder's `origin` written into GitHub, for one. */
interface ProjectWindowState {
  close: () => void
  ticket: boolean
  setTicket: (ticket: boolean) => void
  source: Source
  setSource: (source: Source) => void
}

const ProjectWindowContext = React.createContext<ProjectWindowState | null>(null)

/** The window, as the `open` of the create view. */
export function ProjectWindow({ close, children }: OpenFrameProps) {
  useT()
  const [ticket, setTicket] = React.useState(false)
  const [source, setSource] = React.useState<Source>("github")
  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent
        data-project-window
        showCloseButton={false}
        aria-modal="true"
        aria-describedby={undefined}
        className="max-sm:data-[state=closed]:slide-out-to-bottom max-sm:data-[state=open]:slide-in-from-bottom max-h-[calc(100dvh-2rem)] gap-0 overflow-y-auto p-0 max-sm:data-[state=closed]:zoom-out-100 max-sm:data-[state=open]:zoom-in-100 sm:max-w-[640px] sm:rounded-2xl"
      >
        <ProjectWindowContext value={{ close, ticket, setTicket, source, setSource }}>{children}</ProjectWindowContext>
      </DialogContent>
    </Dialog>
  )
}

const useProjectWindow = () => React.use(ProjectWindowContext)

/** Whether the project is on its way: the button waits for it. */
const BusyContext = React.createContext(false)

/** The project of that name, whatever its case — the one a new one may not be called. */
function useTaken(name: string) {
  const projects = useProjects()
  const wanted = name.trim().replace(/\s+/g, " ").toLocaleLowerCase()
  if (!wanted) return undefined
  return projects?.projects.find((project) => project.name.trim().toLocaleLowerCase() === wanted)
}

/* -- the form -------------------------------------------------------------- */

/* Sends the project, then closes the window — or goes on to its first ticket.
 * A creation is known by the resource announcing it, as the idea form knows
 * its own; a refusal is drawn under its field by the package. Escape is the
 * dialog's, as anywhere. Ctrl+Enter (⌘+Enter) sends from any field; from the brief it waits a moment, because
 * the editor tells the form what it holds a little after the last key. */
export function ProjectForm({ children }: FormDecoratorPropsInterface) {
  const context = useFormContext()
  const { resource } = useCurrentViewResourceContext()
  const frame = useProjectWindow()
  const navigate = useNavigate()
  const ticketLink = useViewLink({ resource: tickets, action: ActionList.create })
  const [busy, setBusy] = React.useState(false)
  const taken = useTaken(String(context.form.data?.name ?? ""))

  const submit = async () => {
    if (busy || taken || !String(context.form.data?.name ?? "").trim()) return
    setBusy(true)
    let made = false
    const watch = resource?.onChange.subscribe(({ action }) => {
      if (action === ActionList.create) made = true
    })
    try {
      await context.onSubmit()
    } finally {
      watch?.unsubscribe()
      setBusy(false)
    }
    if (!made) return
    const created = lastCreated()
    if (frame?.ticket && created) {
      // The ticket's form in place of this one, over the same list.
      void navigate({ to: carrying(ticketLink.to, { project: created }) })
      return
    }
    frame?.close()
  }

  return (
    <form
      noValidate
      data-project-new
      aria-busy={busy || undefined}
      onSubmit={(event) => {
        event.preventDefault()
        void submit()
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey) || event.nativeEvent.isComposing) return
        event.preventDefault()
        const form = event.currentTarget
        const editing = (event.target as Element | null)?.closest?.('[data-slot="markdown-editor"]')
        window.setTimeout(() => form.requestSubmit(), editing ? EDITOR_SETTLES : 0)
      }}
    >
      <BusyContext value={busy}>{children}</BusyContext>
    </form>
  )
}

/** How long the editor takes to tell the form what it holds — the ticket form's own wait. */
const EDITOR_SETTLES = 300

/* -- the controllers ------------------------------------------------------- */

/* The name, as large as an idea's title — and, when the workspace already has
 * a project of that name, the way to it rather than a second one. */
export const ProjectNameInputController: InputControllerComponentInterface = (props) => {
  const taken = useTaken(String(props.formInput.value ?? ""))
  return (
    <>
      <IdeaTitleInputController {...props} />
      {taken && !props.formInput.violations?.length ? (
        <p data-slot="project-name-taken" role="alert" className="text-destructive text-sm">
          {t("A project is already called “{{name}}”.", { name: taken.name })}{" "}
          {taken.id ? (
            <Link to={projectHref(idOf(taken))} className="underline underline-offset-2">
              {t("Open it")}
            </Link>
          ) : null}
        </p>
      ) : null}
    </>
  )
}

/** One line, with no box: the description under the name, as an idea's lines are under its title. */
export const LineInputController: InputControllerComponentInterface = ({ formInput, onChange }) => (
  <input
    id={formInput.id ?? `field-${formInput.name}`}
    name={formInput.name}
    value={String(formInput.value ?? "")}
    onChange={(event) => onChange({ ...formInput, value: event.target.value, violations: [] })}
    placeholder={formInput.placeholder}
    autoComplete="off"
    className="placeholder:text-muted-foreground w-full bg-transparent text-[15px] leading-relaxed outline-none"
  />
)

/* The type, as the idea's chips — but one of the two is always chosen: a
 * project is code or writing, never neither. */
export const KindInputController: InputControllerComponentInterface = (props) => (
  <ChipsInputController {...props} onChange={(input) => (input.value ? props.onChange(input) : undefined)} />
)

/** A field of a row: a box, since what is typed in it is an address, not prose. A refusal
 * is drawn under it by the package's field, as under any other. */
export const BoxInputController: InputControllerComponentInterface = ({ formInput, onChange }) => (
  <input
    id={formInput.id ?? `field-${formInput.name}`}
    name={formInput.name}
    type={formInput.name === "site" ? "url" : "text"}
    inputMode={formInput.name === "site" ? "url" : undefined}
    value={String(formInput.value ?? "")}
    onChange={(event) => onChange({ ...formInput, value: event.target.value, violations: [] })}
    placeholder={formInput.placeholder}
    autoComplete="off"
    spellCheck={false}
    aria-invalid={Boolean(formInput.violations?.length) || undefined}
    className="bg-field placeholder:text-muted-foreground focus-visible:ring-ring/50 aria-invalid:border-destructive h-11 w-full min-w-0 rounded-md border px-3 font-mono text-[13px] outline-none focus-visible:ring-[3px] sm:h-9"
  />
)

/* -- the body -------------------------------------------------------------- */

/** What the server says of a repository and a folder, asked a moment after the last key. */
function useChecked(repository: string, path: string, wanted: boolean): ProjectCheck | null {
  const [checked, setChecked] = React.useState<ProjectCheck | null>(null)
  React.useEffect(() => {
    if (!wanted || (!repository.trim() && !path.trim())) {
      setChecked(null)
      return
    }
    let alive = true
    const timer = window.setTimeout(() => {
      api
        .checkProject(repository, path)
        .then((said) => alive && setChecked(said))
        .catch(() => alive && setChecked(null))
    }, 400)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [repository, path, wanted])
  return checked
}

export function ProjectFields() {
  const context = useFormContext()
  const { form } = context
  const frame = useProjectWindow()
  const latest = React.useRef(context)
  latest.current = context
  const data = (form.data ?? {}) as Record<string, unknown>
  const code = data.kind !== "document"
  const repository = String(data.repository ?? "")
  const path = String(data.path ?? "")
  const [own, setOwn] = React.useState<Source>("github")
  const source = frame?.source ?? own
  const setSource = frame?.setSource ?? setOwn
  const checked = useChecked(source === "github" ? repository : "", source === "folder" ? path : "", code)

  // The projects, for a name already taken: the list may not have been read
  // yet, when the window was opened from the palette.
  React.useEffect(() => {
    void projectsOnce().catch(() => undefined)
  }, [])

  // A folder's `origin`, written into the GitHub field when that is empty:
  // the page names its repository, so another machine finds it too.
  const origin = checked?.origin ?? ""
  React.useEffect(() => {
    if (!origin.startsWith("https://github.com/")) return
    const now = latest.current.form.data ?? {}
    if (String(now.repository ?? "").trim()) return
    // The whole of it: what the package merges into may be older than the folder just typed.
    latest.current.updateData({ ...now, repository: origin })
  }, [origin])

  const inputs = getFormInputsFromForm(form)
  const field = (name: string) => {
    const input = inputs.find((candidate) => candidate.name === name)
    return input ? (
      <InputControllerProvider key={`${input.id}${input.name}${form.version}`} formInput={input} />
    ) : null
  }
  const row = (label: string, children: React.ReactNode, help?: React.ReactNode) => (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-start sm:gap-4">
      <span aria-hidden className="text-muted-foreground w-20 shrink-0 text-sm sm:pt-1.5">
        {t(label)}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        {children}
        {help ? <p className="text-muted-foreground text-xs">{help}</p> : null}
      </div>
    </div>
  )

  return (
    <>
      <header className="bg-background sticky top-0 z-10 flex items-center gap-1 px-5 pt-3 pb-1">
        <DialogTitle className="text-muted-foreground shrink-0 text-sm font-normal">{t("New project")}</DialogTitle>
        <span className="flex-1" />
        {frame ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("Close")}
            className="text-muted-foreground -mr-2 size-11 sm:size-8"
            onClick={frame.close}
          >
            <XIcon />
          </Button>
        ) : null}
      </header>
      <div className="flex flex-col gap-1 px-5 pt-2 pb-4 [&_[data-slot=field]]:my-0 [&_[data-slot=field]]:gap-1 [&_[data-slot=field-label]]:sr-only">
        {field("name")}
        {field("description")}
      </div>
      <div className="flex flex-col gap-4 border-t px-5 py-4 [&_[data-slot=field]]:my-0 [&_[data-slot=field]]:gap-1 [&_[data-slot=field-label]]:sr-only">
        {/* What the type chosen means — the sentence about writing was said
            under Code too, where it described the other button. */}
        {row(
          "Type",
          field("kind"),
          code
            ? t("Its tickets are worked in its repository, and come back as a pull request.")
            : t("Without a repository, its tickets come back as a document.")
        )}
        {code
          ? row(
              "Repository",
              <>
                <div role="group" aria-label={t("Where the repository is")} className="flex flex-wrap gap-1.5">
                  {(["github", "folder"] as const).map((one) => (
                    <button
                      key={one}
                      type="button"
                      aria-pressed={source === one}
                      data-slot="project-source"
                      onClick={() => setSource(one)}
                      className={cn(
                        "bg-field text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 inline-flex min-h-11 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition-colors outline-none focus-visible:ring-[3px] sm:min-h-8",
                        source === one && "border-primary bg-primary/16 text-foreground"
                      )}
                    >
                      {one === "folder" ? <Folder className="size-3.5" /> : null}
                      {one === "github" ? "GitHub" : t("Local folder")}
                    </button>
                  ))}
                </div>
                {source === "github" ? field("repository") : field("path")}
              </>,
              <Checked checked={checked} source={source} />
            )
          : null}
        {row("Site", field("site"), t("Its public address, if it has one. Optional."))}
      </div>
      <div className="flex flex-col gap-2 border-t px-5 py-4 [&_[data-slot=field]]:my-0 [&_[data-slot=field-label]]:sr-only">
        <span className="text-muted-foreground text-sm">{t("The brief")}</span>
        {field("content")}
        <p className="text-muted-foreground text-xs">
          {t("Optional, and written later just as well: from the project's page.")}
        </p>
      </div>
    </>
  )
}

/* The form a project is edited in, in the drawer: its fields in the groups
 * the declaration names (`groupOption` in `resources/projects`), each under a
 * heading and the sentence that says what the group is for — as the "New
 * project" window has its rows, and the recurrence window its sections. The
 * package's own grouped form draws each group as a card, which in a drawer
 * was a card in a card. */
export function ProjectEditFields() {
  const { form } = useFormContext()
  // A writing project has no code to say where it is: the group goes with the type.
  const writing = form.data?.kind === "document"
  const groups = [...(form.groupOption?.itemGroups ?? [])]
    .filter((group) => !(writing && group.group === "code"))
    .sort((a, b) => a.order - b.order)
  return (
    <div
      data-project-edit
      className="flex flex-col divide-y pt-3 [&_[data-slot=field]]:my-0 [&>section]:py-5 [&>section:first-child]:pt-0"
    >
      {groups.map((group) => (
        <section
          key={group.group}
          // A field named as its group — the brief — is not named twice.
          className={cn(
            "flex flex-col gap-4",
            group.group === "brief" && "[&_[data-slot=field-label]]:sr-only"
          )}
        >
          <header>
            <h3 className="text-sm font-semibold">{t(group.title ?? "")}</h3>
            {group.description ? <p className="text-muted-foreground mt-0.5 text-xs">{group.description}</p> : null}
          </header>
          {getFormInputsFromForm({ ...form, groups: [group.group] }).map((input) => (
            <InputControllerProvider key={`${input.id}${input.name}${form.version}`} formInput={input} />
          ))}
        </section>
      ))}
    </div>
  )
}

/** What the server said of what was typed, in a line: where the clone is, or why it will not do. */
function Checked({ checked, source }: { checked: ProjectCheck | null; source: Source }) {
  if (!checked) return null
  if (source === "github") {
    if (checked.repository_error) return <span className="text-destructive">{checked.repository_error}</span>
    if (!checked.repository) return null
    return (
      <span className="flex flex-col gap-0.5">
        <span className="font-mono">{checked.repository}</span>
        <span>
          {checked.cloned
            ? t("Already cloned on this machine, at {{path}}.", { path: checked.cloned })
            : t("Not cloned on this machine yet: it will be at the first ticket.")}
        </span>
      </span>
    )
  }
  if (checked.path_error) return <span className="text-destructive">{checked.path_error}</span>
  if (!checked.path) return null
  return checked.origin
    ? t("A git repository, whose origin is {{origin}}.", { origin: checked.origin })
    : t("A git repository, with no origin remote.")
}

/* -- the foot -------------------------------------------------------------- */

/* "Create a first ticket" on the left, the shortcut and the button on the
 * right — the button the whole width of a phone. Greyed while there is no
 * name, or one already taken. */
export function ProjectFoot() {
  const { form } = useFormContext()
  const frame = useProjectWindow()
  const busy = React.use(BusyContext)
  const mac = typeof navigator !== "undefined" && isMac(navigator.platform || navigator.userAgent)
  const name = String(form.data?.name ?? "")
  const taken = useTaken(name)
  const id = "project-first-ticket"

  return (
    <div className="bg-background sticky bottom-0 z-10 flex flex-col gap-2 border-t px-5 py-3 sm:flex-row sm:items-center">
      {frame ? (
        <label htmlFor={id} className="flex min-h-11 cursor-pointer items-center gap-2 text-sm sm:min-h-8">
          <Checkbox id={id} checked={frame.ticket} onCheckedChange={(checked) => frame.setTicket(checked === true)} />
          {t("Create a first ticket")}
        </label>
      ) : null}
      <span className="flex-1" />
      {/* Why the button is greyed, rather than a button that does nothing. */}
      {!name.trim() ? (
        <span data-slot="project-name-needed" className="text-muted-foreground text-xs">
          {t("A name is all it takes.")}
        </span>
      ) : null}
      <span aria-hidden className="text-muted-foreground pointer-coarse:hidden hidden text-xs sm:inline">
        {mac ? t("⌘ + Enter") : t("Ctrl + Enter")}
      </span>
      <Button
        type="submit"
        disabled={!name.trim() || Boolean(taken) || busy}
        aria-keyshortcuts={mac ? "Meta+Enter" : "Control+Enter"}
        data-slot="project-create"
        className="h-11 w-full sm:h-9 sm:w-auto"
      >
        {t("Create the project")}
      </Button>
    </div>
  )
}
