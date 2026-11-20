import * as React from "react"
import { toast } from "sonner"

import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { api, why } from "@/lib/api"
import { patchTicket, useBoardWith } from "@/lib/board-store"
import { useT } from "@/lib/i18n"
import { DEFAULT_SCORE, readScore } from "@/lib/priority"
import { canAct } from "@/lib/role"
import type { Board, Project, Ticket } from "@/lib/types"

import { PROJECT_STOPS } from "./ticket-project"

/* What a ticket's view lets you change about it, where its facts are listed.
 *
 * The rail of the view lists what a ticket is, each fact under its name, the
 * way an issue does on GitHub or Linear — and where one of them is a setting,
 * it is changed right there rather than in a form somewhere else: the
 * priority, the model its next session runs on, the project while it has not
 * run there yet. The goal is changed under the title, where it is said; Force
 * validated in its own row (`TicketValidation`, compact). Each one is written
 * at once, the card redrawn before the board is read again, and put back as it
 * was when the server refuses.
 *
 * Offered only to a role that can act, and only while it can still matter:
 * not on a ticket that is over, and a project not under a running session.
 * Elsewhere the fact is drawn as it is, read-only: what each is handed to draw.
 */

const priorityOn = (board: Board) => Boolean(board.priority)
const models = (board: Board) => board.choices?.model

/** Over: nothing a setting would change any more. */
const settled = (column: string) => column === "done" || column === "cancelled"

/** The score, typed; written when the field is left, or on Enter. */
export function PriorityField({ ticket, children }: { ticket: Ticket; children: React.ReactNode }) {
  const t = useT()
  const writable = useBoardWith(priorityOn) && canAct() && !settled(ticket.column)
  const saved = typeof ticket.priority === "number" ? String(ticket.priority) : ""
  const [text, setText] = React.useState(saved)
  React.useEffect(() => setText(saved), [saved])
  if (!writable) return children
  const score = readScore(text)
  const write = async () => {
    if (score === undefined || text === saved) {
      setText(saved)
      return
    }
    const before = ticket.priority
    // Empty is an answer: the middle score, as the server writes it.
    patchTicket(ticket.id, { priority: score ?? DEFAULT_SCORE })
    try {
      await api.setPriority(ticket.id, score ?? "")
    } catch (error) {
      patchTicket(ticket.id, { priority: before })
      setText(saved)
      toast.error(t("The priority could not be changed"), { description: why(error) })
    }
  }
  return (
    <span className="inline-flex items-center" data-slot="ticket-priority-field">
      <Input
        type="number"
        inputMode="numeric"
        min={0}
        max={100}
        step={1}
        aria-label={t("Priority, from 0 to 100")}
        aria-invalid={score === undefined || undefined}
        placeholder={String(DEFAULT_SCORE)}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => void write()}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur()
          if (event.key === "Escape") setText(saved)
        }}
        className="h-7 w-14 px-1.5 text-center text-xs tabular-nums"
      />
    </span>
  )
}

const RUNNER = "runner"

/** The model of its next session: one of the board's, or the runner's own. Fable only this way, by hand. */
export function ModelField({
  ticket,
  used,
  children,
}: {
  ticket: Ticket
  used?: { label: string; full: string }
  children: React.ReactNode
}) {
  const t = useT()
  const offered = useBoardWith(models)
  const [value, setValue] = React.useState(ticket.model ?? "")
  React.useEffect(() => setValue(ticket.model ?? ""), [ticket.model])
  if (!offered?.length || !canAct() || settled(ticket.column) || ticket.column === "validated") return children
  const choose = async (next: string) => {
    if (next === value) return
    const before = { model: ticket.model, model_label: ticket.model_label }
    setValue(next)
    try {
      const done = await api.setModel(ticket.id, next)
      patchTicket(ticket.id, { model: done.model, model_label: done.model_label })
    } catch (error) {
      setValue(before.model ?? "")
      patchTicket(ticket.id, before)
      toast.error(t("The model could not be changed"), { description: why(error) })
    }
  }
  // What the session runs on when the ticket names none: the runner's, said by its name when known.
  const runner = used && !value ? used.label.replace(/^claude\//, "") : ""
  return (
    <Select value={value || RUNNER} onValueChange={(next) => void choose(next === RUNNER ? "" : next)}>
      <SelectTrigger
        size="sm"
        className="h-7 max-w-44 gap-1 px-2 text-xs"
        aria-label={t("Change the model")}
        data-slot="ticket-model-select"
        title={used?.full}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {/* Said as the facts say it read-only: the model, and that it is the default. */}
        <SelectItem value={RUNNER}>
          {runner ? (
            <>
              {runner}
              <span className="text-muted-foreground font-normal"> · {t("default")}</span>
            </>
          ) : (
            t("The runner's model")
          )}
        </SelectItem>
        {/* The one it names, though the board no longer offers it: else the field would say nothing. */}
        {value && !offered.some((choice) => choice.value === value) ? (
          <SelectItem value={value}>{ticket.model_label || value}</SelectItem>
        ) : null}
        {offered
          .filter((choice) => choice.value)
          .map((choice) => (
            <SelectItem key={choice.value} value={choice.value}>
              {choice.label.replace(/^claude\//, "")}
            </SelectItem>
          ))}
      </SelectContent>
    </Select>
  )
}

/** Another project, while no session has worked in this one: drafts, tickets waiting, and blocked ones. */
export function ProjectField({ ticket, children }: { ticket: Ticket; children: React.ReactNode }) {
  const t = useT()
  const [projects, setProjects] = React.useState<Project[]>()
  const writable =
    canAct() &&
    ["draft", "ready", "blocked"].includes(ticket.column) &&
    // Stopped on its project: the choice that runs it again is with its status, not here too.
    !(ticket.column === "blocked" && PROJECT_STOPS.has(ticket.block?.code ?? ""))
  if (!writable) return children
  // Asked for once the list is opened: a view opened to be read needs none of them.
  const load = (open: boolean) => {
    if (!open || projects) return
    api.projects().then(
      (read) => setProjects(read.projects.filter((project) => project.id)),
      () => setProjects([])
    )
  }
  const choose = async (id: string) => {
    const project = projects?.find((one) => one.id === id)
    if (!project || project.id === ticket.project_id) return
    const before = { project: ticket.project, project_id: ticket.project_id }
    patchTicket(ticket.id, { project: project.name, project_id: project.id })
    try {
      await api.setTicketProject(ticket.id, project.id)
    } catch (error) {
      patchTicket(ticket.id, before)
      toast.error(t("The project could not be changed"), { description: why(error) })
    }
  }
  return (
    <Select value={ticket.project_id ?? ""} onValueChange={(id) => void choose(id)} onOpenChange={load}>
      <SelectTrigger
        size="sm"
        className="h-7 max-w-44 gap-1 px-2 text-xs font-semibold"
        aria-label={t("Change the project")}
        data-slot="ticket-project-field"
      >
        {/* The name the ticket has, before the list is read: the value alone would draw nothing. */}
        <span className="truncate">{ticket.project || t("no project — a document")}</span>
      </SelectTrigger>
      <SelectContent>
        {projects === undefined ? (
          <SelectItem value={ticket.project_id || "-"} disabled>
            {t("Loading…")}
          </SelectItem>
        ) : (
          projects.map((project) => (
            <SelectItem key={project.id} value={project.id}>
              {project.name}
            </SelectItem>
          ))
        )}
      </SelectContent>
    </Select>
  )
}
