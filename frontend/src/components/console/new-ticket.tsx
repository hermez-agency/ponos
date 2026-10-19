import * as React from "react"
import { GitBranch, Plus } from "lucide-react"
import {
  InputControllerProvider,
  getFormInputsFromForm,
  useFormContext,
  type InputControllerComponentInterface,
} from "react-data-form"

import { EDITOR_SETTLES } from "@/components/console/new-ticket-lazy"
import { ComboboxInputController } from "@/components/console/combobox"
import { Kbd } from "@/components/console/confirm-dialog"
import { every } from "@/components/console/runner-strip"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useConsole } from "@/hooks/use-console"
import { api } from "@/lib/api"
import { enterLabel } from "@/lib/confirm"
import { isMac } from "@/lib/hotkeys"
import { t } from "@/lib/i18n"
import type { Project } from "@/lib/types"
import { cn } from "@/lib/utils"

/* The "New ticket" dialog, in two columns: what the ticket says on the left,
 * how it is run on the right.
 *
 * It used to be eight fields of the same weight down one column, each with its
 * sentence under it, and the brief — the ticket itself — squeezed between the
 * title and the selects. The fields are still react-data-form's, declared in
 * `resources/tickets` and submitted the way they always were: only where each
 * one is drawn changed (`NewTicketFields`, the form's `formInputs`), and the
 * single "Create" with a "Ready to run" box above it became two buttons
 * (`NewTicketFoot`, its `formSubmitAction`).
 */

/** The board's projects, read once per dialog: for the badge beside the field and for the card. */
const Projects = React.createContext<Project[]>([])

function useProjects(): Project[] {
  const [projects, setProjects] = React.useState<Project[]>([])
  React.useEffect(() => {
    let alive = true
    api
      .projects()
      .then((read) => alive && setProjects(read.projects))
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [])
  return projects
}

const hasRepository = (project?: Project) => project?.kind === "code"

/* -- the fields ------------------------------------------------------------- */

/* A choice among a handful, all in view: the type. Four options hidden
 * behind a select were four options nobody saw. The empty one comes first and
 * says what empty means in its tooltip. */
export const SegmentedInputController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const value = String(formInput.value ?? "")
  return (
    <div
      role="group"
      aria-label={t(String(formInput.label ?? ""))}
      data-slot="segmented"
      className="bg-field flex flex-wrap gap-0.5 rounded-lg border p-0.5"
    >
      {(formInput.valueOptions ?? []).map((option) => {
        const key = String(option.value ?? "")
        const chosen = key === value
        return (
          <button
            key={key || "empty"}
            type="button"
            aria-pressed={chosen}
            title={option.description}
            onClick={() => onChange({ ...formInput, value: key, violations: [] })}
            className={cn(
              "text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring/50 min-w-0 flex-auto rounded-md px-2.5 py-1 text-xs font-medium transition-colors outline-none focus-visible:ring-[3px]",
              chosen && "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground"
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

/* A code ticket's sub-type, as pills. Pressed again, a pill lets go: empty is
 * a choice too — the runner deduces it. */
export const PillsInputController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const value = String(formInput.value ?? "")
  return (
    <div role="group" aria-label={t(String(formInput.label ?? ""))} className="flex flex-wrap gap-1.5">
      {(formInput.valueOptions ?? [])
        .filter((option) => option.value)
        .map((option) => {
          const key = String(option.value)
          const chosen = key === value
          return (
            <button
              key={key}
              type="button"
              aria-pressed={chosen}
              onClick={() => onChange({ ...formInput, value: chosen ? "" : key, violations: [] })}
              className={cn(
                "bg-field text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 rounded-full border px-2.5 py-0.5 text-xs transition-colors outline-none focus-visible:ring-[3px]",
                chosen && "border-primary bg-primary/15 text-foreground"
              )}
            >
              {option.label}
            </button>
          )
        })}
    </div>
  )
}

/* The project, typed into as before, with what decides the most beside it:
 * whether it has a repository to open a pull request on. */
export const ProjectInputController: InputControllerComponentInterface = (props) => {
  const projects = React.use(Projects)
  const project = projects.find((candidate) => candidate.id === props.formInput.value)
  return (
    <div className="flex min-w-0 items-center gap-2">
      <div className="min-w-0 flex-1">
        <ComboboxInputController {...props} />
      </div>
      {project ? (
        hasRepository(project) ? (
          <Badge variant="outline" data-slot="project-repository" title={t("A git repository: the ticket comes back as a pull request.")}>
            <GitBranch />
            git
          </Badge>
        ) : (
          <Badge variant="secondary" data-slot="project-repository" title={t("No repository: the ticket comes back as a document.")}>
            {t("no git")}
          </Badge>
        )
      ) : null}
    </div>
  )
}

/* -- the dialog's two columns ------------------------------------------------ */

/* What the buttons under the brief add to it: the two things a brief most
 * often forgets. Added at its end, a heading and a line to fill in. */
const TEMPLATES = [
  {
    button: "Done criterion",
    block: () => `## ${t("It is done when")}\n\n- [ ] ${t("what you will see once it is done")}`,
  },
  {
    button: "File concerned",
    block: () => `## ${t("Files concerned")}\n\n- \`${t("path/to/the/file")}\``,
  },
]

export function NewTicketFields() {
  const context = useFormContext()
  const { form } = context
  const projects = useProjects()
  const latest = React.useRef(context)
  latest.current = context

  const inputs = getFormInputsFromForm(form)
  const data = (form.data ?? {}) as Record<string, unknown>
  const type = String(data.type ?? "")
  const subtype = String(data.subtype ?? "")
  const code = type === "code"

  const inputOf = (name: string) => inputs.find((input) => input.name === name)
  const field = (name: string) => {
    const input = inputOf(name)
    return input ? (
      <InputControllerProvider key={`${input.id}${input.name}${form.version}`} formInput={input} />
    ) : null
  }

  // A sub-type is a code ticket's: another type, or none, takes it away — it
  // would otherwise leave with a ticket that no longer shows it.
  React.useEffect(() => {
    if (code || !subtype) return
    const input = getFormInputsFromForm(latest.current.form).find((candidate) => candidate.name === "subtype")
    if (input) latest.current.onChange({ ...input, value: "" })
  }, [code, subtype])

  // Read from the form as it is once the editor has told it its last words,
  // not as it was when the button was pressed.
  const add = (block: string) =>
    window.setTimeout(() => {
      const now = latest.current
      const input = getFormInputsFromForm(now.form).find((candidate) => candidate.name === "body")
      if (!input) return
      const body = String(now.form.data?.body ?? "").trimEnd()
      now.onChange({ ...input, value: body ? `${body}\n\n${block}\n` : `${block}\n` })
    }, EDITOR_SETTLES)

  return (
    <Projects value={projects}>
      <div
        data-new-ticket
        className="grid gap-5 min-[760px]:min-h-[26rem] min-[760px]:grid-cols-[minmax(0,1fr)_21.25rem] [&_[data-slot=field]]:my-0"
      >
        <div className="flex min-w-0 flex-col gap-3">
          {field("title")}
          <div className="relative flex min-h-0 flex-1 flex-col">
            <span className="text-muted-foreground absolute top-0.5 right-0 text-xs">
              {t("Markdown · read by the runner on the ticket's page")}
            </span>
            {field("body")}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {TEMPLATES.map((template) => (
              <Button
                key={template.button}
                type="button"
                variant="outline"
                size="xs"
                className="rounded-full"
                onClick={() => add(template.block())}
              >
                <Plus />
                {t(template.button)}
              </Button>
            ))}
          </div>
        </div>

        <aside className="bg-muted/50 flex min-w-0 flex-col gap-3.5 rounded-2xl p-4 [&_[data-slot=field-label]]:text-muted-foreground [&_[data-slot=field-label]]:text-xs">
          {field("project")}
          {field("type")}
          {code ? field("subtype") : null}
          {field("priority")}
          {field("model")}
        </aside>
      </div>
    </Projects>
  )
}

/* -- the foot ---------------------------------------------------------------- */

/* Two ways out instead of a box to tick and one button: a draft the runner
 * leaves alone, or a ticket launched at its next pass. Both are the same
 * submission, with `ready` said first — and said in the form, so it is sent
 * the way it always was. The submission waits for the form to hold it: a
 * change and a submission in the same click would send what the form held
 * before. Ctrl+Enter (⌘+Enter) is this launch button pressed. */
export function NewTicketFoot() {
  const context = useFormContext()
  const { runner } = useConsole()
  const seconds = runner?.timer === "enabled" ? (runner.interval_seconds ?? 0) : 0
  const mac = typeof navigator !== "undefined" && isMac(navigator.platform || navigator.userAgent)
  const [asked, setAsked] = React.useState<boolean | null>(null)
  const ready = context.form.data?.ready !== false

  React.useEffect(() => {
    if (asked === null || asked !== ready) return
    setAsked(null)
    void context.onSubmit()
  }, [asked, ready, context])

  const ask = (launch: boolean) => {
    const input = getFormInputsFromForm(context.form).find((candidate) => candidate.name === "ready")
    if (input) context.onChange({ ...input, value: launch })
    setAsked(launch)
  }
  const busy = Boolean(context.form.loading) || asked !== null

  return (
    <div className="mt-5 flex flex-col-reverse gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-muted-foreground text-xs">
        {seconds
          ? t("Launched, the ticket starts at the next pass, within {{every}}.", { every: every(seconds) })
          : t("Launched, the ticket starts at the next pass.")}
      </p>
      <div className="flex shrink-0 justify-end gap-2">
        <Button type="button" variant="secondary" disabled={busy} onClick={() => ask(false)}>
          {t("Draft")}
        </Button>
        <Button
          type="button"
          data-launch
          disabled={busy}
          aria-keyshortcuts={mac ? "Meta+Enter" : "Control+Enter"}
          onClick={() => ask(true)}
        >
          {t("Launch the ticket")}
          <Kbd>{enterLabel(true, mac)}</Kbd>
        </Button>
      </div>
    </div>
  )
}
