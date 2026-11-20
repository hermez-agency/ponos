import * as React from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { api, why } from "@/lib/api"
import { patchTicket, useBoardWith } from "@/lib/board-store"
import { useT } from "@/lib/i18n"
import { upcoming } from "@/lib/later"
import { DEFAULT_SCORE, readScore } from "@/lib/priority"
import { canAct } from "@/lib/role"
import type { Board, Project, Ticket } from "@/lib/types"

import { SchedulePicker } from "./schedule-picker"
import { when } from "./ticket-bits"
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

/** « Scheduled for »: when it may start, set, moved or removed until the ticket is over.
 *
 * In a popover rather than in the rail itself: five shortcuts and a date
 * field are a question asked now and then, not a fact to read every time. Written
 * on « Save », not at each key — a date half typed is a moment nobody chose —
 * and the server refuses one already past, said in a toast with the date kept.
 */
export function ScheduledField({ ticket, children }: { ticket: Ticket; children: React.ReactNode }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const [draft, setDraft] = React.useState(ticket.scheduled ?? "")
  const [busy, setBusy] = React.useState(false)
  if (!canAct() || settled(ticket.column)) return children
  const save = async (next: string) => {
    // Said here, in the page's language, rather than in the server's English.
    if (next && !upcoming(next, Date.now())) {
      toast.error(t("This moment has already passed: choose a later one, or none."))
      return
    }
    const before = { scheduled: ticket.scheduled, held: ticket.held }
    setBusy(true)
    try {
      const done = await api.setScheduled(ticket.id, next)
      // The wait it is held for is the board's to say again, at its next read.
      patchTicket(ticket.id, { scheduled: done.scheduled, ...(done.scheduled ? {} : { held: undefined }) })
      setOpen(false)
    } catch (error) {
      patchTicket(ticket.id, before)
      toast.error(t("The date could not be changed"), { description: why(error) })
    } finally {
      setBusy(false)
    }
  }
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) setDraft(ticket.scheduled ?? "")
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          data-slot="ticket-scheduled-field"
          aria-label={t("Change the date")}
          className="hover:bg-accent -mx-1 rounded-md px-1 text-left underline-offset-2 hover:underline"
        >
          {ticket.scheduled ? children : <span className="text-muted-foreground">{t("As soon as possible")}</span>}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="flex w-80 flex-col gap-3">
        <p className="text-sm font-medium">{t("Scheduled for")}</p>
        <SchedulePicker value={draft} onChange={setDraft} disabled={busy} />
        <p className="text-muted-foreground text-xs">
          {draft
            ? t("It waits until {{at}}, in your timezone.", { at: when(draft) })
            : t("No date: it starts as soon as a place is free.")}
        </p>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" size="sm" onClick={() => setOpen(false)}>
            {t("Cancel")}
          </Button>
          <Button
            type="button"
            size="sm"
            data-slot="ticket-scheduled-save"
            disabled={busy || draft === (ticket.scheduled ?? "")}
            onClick={() => void save(draft)}
          >
            {t("Save")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}

/** « Launch now », on a ticket held back by its date: the date taken away, and the ticket the runner's at its turn.
 *
 * Not « Run now »: that one jumps the queue, this one only stops waiting —
 * on a ready ticket it is in the queue at once, on a validated one it is
 * published or merged at the next look. In the view, under the line that says
 * when it is due: the card keeps « Run now », and the first load its budget. */
export function LaunchNow({ ticket }: { ticket: Ticket }) {
  const t = useT()
  const [busy, setBusy] = React.useState(false)
  const launch = async () => {
    const before = { scheduled: ticket.scheduled, held: ticket.held }
    setBusy(true)
    patchTicket(ticket.id, { scheduled: "", held: undefined })
    try {
      await api.setScheduled(ticket.id, "")
    } catch (error) {
      patchTicket(ticket.id, before)
      toast.error(t("The date could not be removed"), { description: why(error) })
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button
      variant="outline"
      size="xs"
      disabled={busy}
      data-slot="launch-now"
      title={t("Remove the date: it no longer waits.")}
      onClick={() => void launch()}
    >
      {t("Launch now")}
    </Button>
  )
}
