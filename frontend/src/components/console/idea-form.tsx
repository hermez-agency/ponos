import * as React from "react"
import { ChevronDown, Folder, FolderPlus, Plus, XIcon } from "lucide-react"
import {
  ActionList,
  InputControllerProvider,
  getFormInputsFromForm,
  useFormContext,
  type FormDecoratorPropsInterface,
  type InputControllerComponentInterface,
  type ViolationInterface,
  type ValueOptionInterface,
} from "react-data-form"
import { useCurrentViewResourceContext, type OpenFrameProps } from "react-resource-view"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { isMac } from "@/lib/hotkeys"
import { t, useT } from "@/lib/i18n"
import { bare } from "@/lib/idea-search"
import { cn } from "@/lib/utils"
import { isAPage, projectsOnce, useProjects } from "@/resources/projects"

/* "New idea", as a quick entry rather than a form to fill in.
 *
 * It was the package's column of fields in a drawer the height of the screen:
 * three selects all saying "Choose…", a sentence under the category about one
 * category only, one under the type about the project, and a title no louder
 * than the rest. The fields are still react-data-form's, declared in
 * `resources/ideas` and sent to `createItem` as they always were: only how
 * each one is drawn changed. The title is the largest thing in the window and
 * has the cursor; whom the idea is for is a menu in the window's header; the
 * category is a row of chips all in view; and the window is as tall as what
 * is in it — a sheet coming up from the bottom on a phone.
 *
 * The type is not a field any more: a new project is only ever the
 * workspace's, so "Propose a new project" is the last entry of the project
 * menu — the workspace and the type in one choice, the one the old sentence
 * under the type explained.
 *
 * The form draws its own <form> (`IdeaForm`, its `formDecorator`): the
 * package's swaps the fields for a loader while the idea is sent, and "Create
 * another" wants the title to be there, empty, once it is written. The
 * package's view leaves the window open after a creation (`afterSave:
 * "stay"`), and the form closes it, or empties itself, once the resource says
 * the idea exists.
 */

/** What the window keeps across the form, which is drawn again whenever its data is replaced. */
interface IdeaWindowState {
  close: () => void
  another: boolean
  setAnother: (another: boolean) => void
}

const IdeaWindowContext = React.createContext<IdeaWindowState | null>(null)

/** The window, as the `open` of the create view. */
export function IdeaWindow({ close, children }: OpenFrameProps) {
  useT()
  const [another, setAnother] = React.useState(false)
  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent
        data-idea-window
        showCloseButton={false}
        aria-modal="true"
        aria-describedby={undefined}
        className="max-sm:data-[state=closed]:slide-out-to-bottom max-sm:data-[state=open]:slide-in-from-bottom max-h-[calc(100dvh-2rem)] gap-0 overflow-y-auto p-0 max-sm:data-[state=closed]:zoom-out-100 max-sm:data-[state=open]:zoom-in-100 sm:max-w-[560px] sm:rounded-2xl"
      >
        <IdeaWindowContext value={{ close, another, setAnother }}>{children}</IdeaWindowContext>
      </DialogContent>
    </Dialog>
  )
}

const useIdeaWindow = () => React.use(IdeaWindowContext)

/* -- the form -------------------------------------------------------------- */

/* Sends the idea, then closes the window or empties the form for the next
 * one. The package's own submission says nothing of how it went — a refusal
 * is a toast, and the form is handed back either way — so a creation is known
 * by the resource announcing it. Ctrl+Enter (⌘+Enter on a Mac) sends from any
 * field, the description included, where Enter alone is a new line. */
export function IdeaForm({ children }: FormDecoratorPropsInterface) {
  const context = useFormContext()
  const { resource } = useCurrentViewResourceContext()
  const frame = useIdeaWindow()
  const [busy, setBusy] = React.useState(false)
  const latest = React.useRef(context)
  latest.current = context

  const submit = async () => {
    if (busy || !String(context.form.data?.title ?? "").trim()) return
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
    if (!frame?.another) return frame?.close()
    // Emptied, but still for the same project: the next idea is most often its neighbour's.
    const data = latest.current.form.data ?? {}
    latest.current.updateData({ title: "", description: "", category: "", project: data.project ?? "", kind: data.kind ?? "ticket" }, false)
  }

  return (
    <form
      noValidate
      data-idea-form
      aria-busy={busy || undefined}
      onSubmit={(event) => {
        event.preventDefault()
        void submit()
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey) || event.nativeEvent.isComposing) return
        event.preventDefault()
        event.currentTarget.requestSubmit()
      }}
    >
      <BusyContext value={busy}>{children}</BusyContext>
    </form>
  )
}

/** Whether the idea is on its way: the button waits for it. */
const BusyContext = React.createContext(false)

/* -- the header ------------------------------------------------------------ */

const WORKSPACE = "__workspace__"
const NEW_PROJECT = "__new_project__"

/* Whom the idea is for: the workspace, one of its projects, or a project that
 * does not exist yet. Written in one go, since the two fields move together. */
function ProjectMenu() {
  const context = useFormContext()
  const projects = useProjects()
  React.useEffect(() => {
    void projectsOnce().catch(() => undefined)
  }, [])
  const data = (context.form.data ?? {}) as Record<string, unknown>
  const project = String(data.project ?? "")
  const value = project || (data.kind === "project" ? NEW_PROJECT : WORKSPACE)
  const named = (projects?.projects ?? [])
    // An archived project is proposed nothing — but an idea already its keeps its name.
    .filter((row) => isAPage(row.id) && (!row.shelved || bare(row.id) === project))
    .map((row) => ({ id: bare(row.id), name: row.name }))
    .sort((a, b) => a.name.localeCompare(b.name))
  const name =
    value === NEW_PROJECT
      ? t("New project")
      : value === WORKSPACE
        ? t("Workspace")
        : (named.find((one) => one.id === project)?.name ?? t("Project"))

  const choose = (chosen: string) =>
    context.updateData(
      chosen === NEW_PROJECT
        ? { project: "", kind: "project" }
        : { project: chosen === WORKSPACE ? "" : chosen, kind: "ticket" }
    )

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          data-slot="idea-project"
          aria-label={t("Project: {{name}}", { name })}
          className="-ml-2 h-11 max-w-[60%] min-w-0 gap-1.5 px-2 font-medium sm:h-8"
        >
          {value === NEW_PROJECT ? <FolderPlus /> : <Folder />}
          <span className="truncate">{name}</span>
          <ChevronDown className="text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-80 w-72">
        <DropdownMenuRadioGroup value={value} onValueChange={choose}>
          <DropdownMenuRadioItem value={WORKSPACE} className="min-h-11 sm:min-h-8">
            {t("Workspace")}
          </DropdownMenuRadioItem>
          {named.map((one) => (
            <DropdownMenuRadioItem key={one.id} value={one.id} className="min-h-11 sm:min-h-8">
              <span className="truncate">{one.name}</span>
            </DropdownMenuRadioItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuRadioItem value={NEW_PROJECT} data-slot="idea-new-project" className="items-start">
            <Plus className="mt-0.5" />
            <span className="flex flex-col gap-0.5">
              <span className="font-medium">{t("Propose a new project")}</span>
              <span className="text-muted-foreground text-xs">
                {t("The idea becomes a project-creation ticket.")}
              </span>
            </span>
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/* -- the controllers ------------------------------------------------------- */

/* The title: the largest thing in the window, with no box around it, and the
 * cursor in it as the window opens — and again once "Create another" has
 * emptied it. Its label is for a screen reader; the greyed line says enough. */
export const IdeaTitleInputController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const invalid = Boolean(formInput.violations?.length)
  const id = formInput.id ?? "field-title"
  return (
    <>
      <input
        id={id}
        name={formInput.name}
        value={String(formInput.value ?? "")}
        onChange={(event) => onChange({ ...formInput, value: event.target.value, violations: [] })}
        placeholder={formInput.placeholder}
        required
        autoComplete="off"
        autoFocus
        aria-invalid={invalid || undefined}
        aria-errormessage={invalid ? `${id}-problem` : undefined}
        className="placeholder:text-muted-foreground w-full bg-transparent text-2xl leading-tight font-semibold outline-none"
      />
      {invalid ? (
        <span id={`${id}-problem`} role="alert" className="text-destructive text-sm">
          {formInput.violations?.map((violation: ViolationInterface) => violation.message).join(" ")}
        </span>
      ) : null}
    </>
  )
}

/** The lines under it, with no box either. */
export const IdeaTextInputController: InputControllerComponentInterface = ({ formInput, onChange }) => (
  <textarea
    id={formInput.id ?? "field-description"}
    name={formInput.name}
    rows={4}
    value={String(formInput.value ?? "")}
    onChange={(event) => onChange({ ...formInput, value: event.target.value, violations: [] })}
    placeholder={formInput.placeholder}
    className="placeholder:text-muted-foreground w-full resize-none bg-transparent text-[15px] leading-relaxed outline-none"
  />
)

/* A choice among a handful, as chips all in view. Pressed again, a chip lets
 * go: an idea may stay unsorted, and Ponos sorts it when it is reworded. */
export const ChipsInputController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const value = String(formInput.value ?? "")
  return (
    <div role="group" aria-label={t(String(formInput.label ?? ""))} className="flex flex-wrap gap-1.5">
      {(formInput.valueOptions ?? []).map((option: ValueOptionInterface) => {
        const key = String(option.value ?? "")
        const chosen = key === value
        return (
          <button
            key={key}
            type="button"
            aria-pressed={chosen}
            data-slot="idea-chip"
            onClick={() => onChange({ ...formInput, value: chosen ? "" : key, violations: [] })}
            className={cn(
              "bg-field text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 inline-flex min-h-11 items-center rounded-full border px-3 text-sm font-medium transition-colors outline-none focus-visible:ring-[3px] sm:min-h-8",
              chosen && "border-primary bg-primary/16 text-foreground"
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

/* -- the body -------------------------------------------------------------- */

export function IdeaFields() {
  const { form } = useFormContext()
  const frame = useIdeaWindow()
  const inputs = getFormInputsFromForm(form)
  const field = (name: string) => {
    const input = inputs.find((candidate) => candidate.name === name)
    return input ? (
      <InputControllerProvider key={`${input.id}${input.name}${form.version}`} formInput={input} />
    ) : null
  }
  const category = String(form.data?.category ?? "")

  return (
    <>
      <header className="bg-background sticky top-0 z-10 flex items-center gap-1 px-5 pt-3 pb-1">
        <ProjectMenu />
        <span aria-hidden className="text-muted-foreground">
          /
        </span>
        <DialogTitle className="text-muted-foreground shrink-0 text-sm font-normal">{t("New idea")}</DialogTitle>
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
        {field("title")}
        {field("description")}
      </div>
      <div className="flex flex-col gap-2 border-t px-5 py-4">
        <div className="flex items-start gap-4 [&_[data-slot=field]]:my-0 [&_[data-slot=field-label]]:sr-only">
          <span aria-hidden className="text-muted-foreground w-20 shrink-0 pt-3 text-sm sm:pt-1.5">
            {t("Category")}
          </span>
          {field("category")}
        </div>
        {category === "technical" ? (
          <p data-slot="idea-tech-help" aria-live="polite" className="text-muted-foreground pl-24 text-sm">
            {t("Refactoring, performance, technical debt — not a new feature.")}
          </p>
        ) : null}
      </div>
    </>
  )
}

/* -- the foot -------------------------------------------------------------- */

/* "Create another" on the left, the shortcut and the button on the right —
 * the button the whole width of a phone, under the box. Greyed while there is
 * no title: there is nothing to create yet. */
export function IdeaFoot() {
  const { form } = useFormContext()
  const frame = useIdeaWindow()
  const busy = React.use(BusyContext)
  const mac = typeof navigator !== "undefined" && isMac(navigator.platform || navigator.userAgent)
  const empty = !String(form.data?.title ?? "").trim()
  const id = "idea-another"

  return (
    <div className="bg-background sticky bottom-0 z-10 flex flex-col gap-2 border-t px-5 py-3 sm:flex-row sm:items-center">
      {frame ? (
        <label htmlFor={id} className="flex min-h-11 cursor-pointer items-center gap-2 text-sm sm:min-h-8">
          <Checkbox id={id} checked={frame.another} onCheckedChange={(checked) => frame.setAnother(checked === true)} />
          {t("Create another")}
        </label>
      ) : null}
      <span className="flex-1" />
      <span aria-hidden className="text-muted-foreground pointer-coarse:hidden hidden text-xs sm:inline">
        {mac ? t("⌘ + Enter") : t("Ctrl + Enter")}
      </span>
      <Button
        type="submit"
        disabled={empty || busy}
        aria-keyshortcuts={mac ? "Meta+Enter" : "Control+Enter"}
        data-slot="idea-create"
        className="h-11 w-full sm:h-9 sm:w-auto"
      >
        {t("Create the idea")}
      </Button>
    </div>
  )
}
