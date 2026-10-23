import * as React from "react"
import { CalendarClock, Settings2 } from "lucide-react"
import { toast } from "sonner"

import { ModelChoice } from "@/components/console/model-input"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { api, why } from "@/lib/api"
import { counted, useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import { clockOf, dayName, locale, WEEKDAYS } from "@/lib/recurrence"
import type { IdeasPlan } from "@/lib/types"

/* When Ponos looks for ideas on its own, and the window that sets it.
 *
 * The line at the head of the Ideas page says what the schedule will do next and
 * what it did last, as the Recurrences page's "Next" and "Last" columns say it
 * for a recurrence; the button beside "New idea" opens the window that changes
 * it. Both read `/api/ideas/schedule`, and both read it again when the stream
 * says a pass has been made or the settings have moved — here, so that the
 * line and the window never disagree about what the file holds.
 */

/** The plan as the server has it, read again whenever the stream says it moved. */
function useIdeasPlan() {
  const [plan, setPlan] = React.useState<IdeasPlan | null>(null)
  const [problem, setProblem] = React.useState("")
  const read = React.useCallback(() => {
    api.ideasPlan().then(
      (fresh) => {
        setPlan(fresh)
        setProblem("")
      },
      (error) => setProblem(why(error))
    )
  }, [])
  React.useEffect(() => {
    read()
    window.addEventListener("ponos:ideas-plan", read)
    window.addEventListener("ponos:settings", read)
    return () => {
      window.removeEventListener("ponos:ideas-plan", read)
      window.removeEventListener("ponos:settings", read)
    }
  }, [read])
  return { plan, problem, read, setPlan }
}

/** A moment the way the recurrences' table says one: the day, then the hour. */
function moment(value: string): string {
  const date = value ? new Date(value) : null
  if (!date || Number.isNaN(date.getTime())) return ""
  const day = new Intl.DateTimeFormat(locale()).format(date)
  const hour = date.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" })
  return `${day} - ${hour}`
}

/* -- the line at the head of the page -------------------------------------- */

export function IdeasPlanLine() {
  const t = useT()
  const { plan } = useIdeasPlan()
  if (!plan) return null
  const { last } = plan
  const on = plan.settings.schedule !== "off"
  const skipped = last?.skipped.length ?? 0
  return (
    <p
      data-slot="ideas-plan-line"
      className="text-muted-foreground mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[0.7rem]"
    >
      <span className="inline-flex items-center gap-1.5">
        <CalendarClock className="size-3.5" />
        {plan.problem
          ? plan.problem
          : on && plan.next
            ? t("Next pass: {{when}}", { when: moment(plan.next) })
            : t("No automatic search: ideas are found when you ask.")}
      </span>
      {last ? (
        <span data-slot="ideas-last-pass" title={last.skipped.map((one) => `${one.name}: ${one.reason}`).join("\n")}>
          {t("Last pass: {{when}} - {{ideas}}", {
            when: moment(last.at),
            ideas: counted(last.found, "{{count}} idea found", "{{count}} ideas found"),
          })}
          {skipped ? ` · ${counted(skipped, "{{count}} project skipped", "{{count}} projects skipped")}` : ""}
          {last.error ? ` · ${last.error}` : ""}
        </span>
      ) : on ? (
        <span>{t("No pass yet.")}</span>
      ) : null}
    </p>
  )
}

/* -- the window ------------------------------------------------------------ */

const SCHEDULES = ["off", "every_4h", "daily", "weekly", "hours", "cron"] as const

/** What the window is editing: the settings as text boxes hold them, and the projects ticked. */
interface Draft {
  schedule: string
  at: string
  day: string
  hours: string
  cron: string
  scope: string
  workspace: boolean
  perBatch: string
  skipAbove: string
  budget: string
  notify: boolean
  model: string
  projects: Set<string>
}

function draftOf(plan: IdeasPlan): Draft {
  const { settings } = plan
  return {
    schedule: settings.schedule,
    at: clockOf(settings.at) || "09:00",
    day: settings.day,
    hours: String(settings.every_hours),
    cron: settings.cron,
    scope: settings.scope,
    workspace: settings.workspace,
    perBatch: String(settings.per_batch),
    skipAbove: String(settings.skip_above),
    budget: settings.budget_usd ? String(settings.budget_usd) : "",
    notify: settings.notify,
    model: settings.model,
    projects: new Set(plan.projects.filter((project) => project.enabled).map((project) => project.id)),
  }
}

export function IdeasSettingsButton() {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" data-slot="ideas-settings">
          <Settings2 />
          {t("Settings")}
        </Button>
      </DialogTrigger>
      {open ? <IdeasSettings onClose={() => setOpen(false)} /> : null}
    </Dialog>
  )
}

function Row({ label, id, children }: { label: string; id: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id} className="leading-snug font-semibold">
        {label}
      </Label>
      {children}
    </div>
  )
}

function IdeasSettings({ onClose }: { onClose: () => void }) {
  const t = useT()
  const { plan, problem: unread, setPlan } = useIdeasPlan()
  const [draft, setDraft] = React.useState<Draft | null>(null)
  const [problem, setProblem] = React.useState("")
  const [saving, setSaving] = React.useState(false)
  // The window opens on what the file says, once; a pass finishing while it is
  // open must not rewrite what is being typed.
  React.useEffect(() => {
    if (plan && !draft) setDraft(draftOf(plan))
  }, [plan, draft])

  const change = (changes: Partial<Draft>) => setDraft((now) => (now ? { ...now, ...changes } : now))
  const labels: Record<(typeof SCHEDULES)[number], string> = {
    off: t("Never, only when I ask"),
    every_4h: t("Every 4 hours"),
    daily: t("Every day"),
    weekly: t("Every week"),
    hours: t("Every N hours"),
    cron: t("A cron expression"),
  }

  const save = async () => {
    if (!draft) return
    setSaving(true)
    setProblem("")
    try {
      const fresh = await api.saveIdeasPlan({
        schedule: draft.schedule,
        at: draft.at,
        day: draft.day,
        every_hours: Number(draft.hours) || 1,
        cron: draft.cron.trim(),
        scope: draft.scope,
        workspace: draft.workspace,
        per_batch: Number(draft.perBatch) || 10,
        skip_above: Number(draft.skipAbove) || 0,
        budget_usd: Number(draft.budget) || 0,
        notify: draft.notify,
        model: draft.model,
        // Only a scope that is a list has one to send: for "all", the projects
        // that turned themselves off keep their word.
        ...(draft.scope === "selected" ? { projects: [...draft.projects] } : {}),
      })
      setPlan(fresh)
      toast.success(t("Ideas settings saved."))
      onClose()
    } catch (error) {
      setProblem(why(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl" data-slot="ideas-settings-window">
      <DialogHeader>
        <DialogTitle>{t("Ideas settings")}</DialogTitle>
        <DialogDescription>
          {t("When Ponos looks for ideas on its own, for which projects, and how much it may do. The button still works whatever is set here.")}
        </DialogDescription>
      </DialogHeader>
      {unread || problem ? (
        <Alert variant="destructive">
          <AlertDescription>{problem || unread}</AlertDescription>
        </Alert>
      ) : null}
      {!plan || !draft ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <div className="flex flex-col gap-5">
          <fieldset className="flex flex-col gap-3" data-slot="ideas-frequency">
            <legend className="mb-1 text-sm font-semibold">{t("Frequency")}</legend>
            <Row id="ideas-schedule" label={t("How often")}>
              <Select value={draft.schedule} onValueChange={(schedule) => change({ schedule })}>
                <SelectTrigger id="ideas-schedule" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SCHEDULES.map((name) => (
                    <SelectItem key={name} value={name}>
                      {labels[name]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Row>
            {draft.schedule === "weekly" ? (
              <Row id="ideas-day" label={t("On which day")}>
                <Select value={draft.day} onValueChange={(day) => change({ day })}>
                  <SelectTrigger id="ideas-day" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WEEKDAYS.map((name, index) => (
                      <SelectItem key={name} value={name}>
                        {dayName(index, "long")}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Row>
            ) : null}
            {draft.schedule === "daily" || draft.schedule === "weekly" ? (
              <Row id="ideas-at" label={t("At")}>
                <Input id="ideas-at" type="time" value={draft.at} onChange={(event) => change({ at: event.target.value })} />
              </Row>
            ) : null}
            {draft.schedule === "hours" ? (
              <Row id="ideas-hours" label={t("Every (hours)")}>
                <Input id="ideas-hours" type="number" min={1} value={draft.hours} onChange={(event) => change({ hours: event.target.value })} />
              </Row>
            ) : null}
            {draft.schedule === "cron" ? (
              <Row id="ideas-cron" label={t("Cron expression")}>
                <Input
                  id="ideas-cron"
                  className="font-mono"
                  placeholder="0 9 * * 1-5"
                  value={draft.cron}
                  onChange={(event) => change({ cron: event.target.value })}
                />
                <p className="text-muted-foreground text-xs">{t("Minute, hour, day, month, weekday: 0 9 * * 1-5 is weekdays at nine.")}</p>
              </Row>
            ) : null}
            {draft.schedule !== "off" ? (
              <p className="text-muted-foreground text-xs">
                {t("Hours are this machine's{{zone}}. The searches run while the console does.", {
                  zone: plan.timezone ? ` (${plan.timezone})` : "",
                })}
              </p>
            ) : null}
          </fieldset>

          <fieldset className="flex flex-col gap-3" data-slot="ideas-scope">
            <legend className="mb-1 text-sm font-semibold">{t("Projects")}</legend>
            <Row id="ideas-scope" label={t("Which projects")}>
              <Select value={draft.scope} onValueChange={(scope) => change({ scope })}>
                <SelectTrigger id="ideas-scope" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("All projects, the ones added later too")}</SelectItem>
                  <SelectItem value="selected">{t("Selected projects")}</SelectItem>
                </SelectContent>
              </Select>
            </Row>
            {draft.scope === "selected" ? (
              <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto rounded-md border p-2" data-slot="ideas-projects">
                {plan.projects.length ? (
                  plan.projects.map((project) => (
                    <li key={project.id} className="flex items-center gap-2">
                      <Checkbox
                        id={`ideas-project-${project.id}`}
                        checked={draft.projects.has(project.id)}
                        onCheckedChange={(on) => {
                          const next = new Set(draft.projects)
                          if (on) next.add(project.id)
                          else next.delete(project.id)
                          change({ projects: next })
                        }}
                      />
                      <Label htmlFor={`ideas-project-${project.id}`} className="font-normal">
                        {project.name}
                      </Label>
                    </li>
                  ))
                ) : (
                  <li className="text-muted-foreground text-sm">{t("No project yet.")}</li>
                )}
              </ul>
            ) : (
              <p className="text-muted-foreground text-xs">
                {t("A project's own page can still turn it off: it is unticked there.")}
              </p>
            )}
            <div className="flex items-center gap-2">
              <Checkbox
                id="ideas-workspace"
                checked={draft.workspace}
                onCheckedChange={(on) => change({ workspace: on === true })}
              />
              <Label htmlFor="ideas-workspace" className="font-normal">
                {t("Ideas for the workspace, the ones that belong to no project")}
              </Label>
            </div>
          </fieldset>

          <fieldset className="flex flex-col gap-3" data-slot="ideas-limits">
            <legend className="mb-1 text-sm font-semibold">{t("Limits")}</legend>
            <div className="grid gap-3 sm:grid-cols-3">
              <Row id="ideas-per-batch" label={t("Ideas per project")}>
                <Input id="ideas-per-batch" type="number" min={1} max={20} value={draft.perBatch} onChange={(event) => change({ perBatch: event.target.value })} />
              </Row>
              <Row id="ideas-skip-above" label={t("Skip above")}>
                <Input id="ideas-skip-above" type="number" min={0} value={draft.skipAbove} onChange={(event) => change({ skipAbove: event.target.value })} />
              </Row>
              <Row id="ideas-budget" label={t("Budget per pass ($)")}>
                <Input
                  id="ideas-budget"
                  type="number"
                  min={0}
                  step="0.5"
                  placeholder={t("none")}
                  value={draft.budget}
                  onChange={(event) => change({ budget: event.target.value })}
                />
              </Row>
            </div>
            <p className="text-muted-foreground text-xs">
              {t("A project with that many new ideas nobody has sorted is skipped, and the journal says so (0: never). The budget is read between two projects; empty is no ceiling.")}
              {plan.last?.cost_usd ? ` ${t("Last pass: {{cost}}.", { cost: money(plan.last.cost_usd) })}` : ""}
            </p>
            <div className="flex items-center gap-2">
              <Checkbox id="ideas-notify" checked={draft.notify} onCheckedChange={(on) => change({ notify: on === true })} />
              <Label htmlFor="ideas-notify" className="font-normal">
                {t("Tell me on my channels when a pass finds new ideas")}
              </Label>
            </div>
          </fieldset>

          <fieldset className="flex flex-col gap-3" data-slot="ideas-model">
            <legend className="mb-1 text-sm font-semibold">{t("Model")}</legend>
            <ModelChoice
              id="ideas-model"
              value={draft.model}
              onChange={(model) => change({ model })}
              empty={t("The CLI's own model")}
              label={t("Model that finds ideas")}
            />
          </fieldset>
        </div>
      )}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          {t("Cancel")}
        </Button>
        <Button onClick={() => void save()} disabled={!draft || saving} data-slot="ideas-settings-save">
          {t("Save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  )
}
