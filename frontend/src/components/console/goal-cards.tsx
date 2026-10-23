import { CalendarDays, ExternalLink, Pencil, SearchX, Target, Trash2, X } from "lucide-react"
import { toast } from "sonner"
import { ActionList } from "react-data-form"
import {
  ListPagination,
  ResourceViewButton,
  useCurrentViewResourceContext,
  useListViewContext,
  useNavigate,
  type ListComponentPropsInterface,
} from "react-resource-view"

import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api, why } from "@/lib/api"
import { useBoard } from "@/lib/board-store"
import { dueOf, progressOf } from "@/lib/goal-search"
import { useT } from "@/lib/i18n"
import { count } from "@/lib/numbers"
import { locale } from "@/lib/recurrence"
import type { Goal } from "@/lib/types"
import { cn } from "@/lib/utils"
import { goals, goalsHref, goalsOnce, useGoals, type GoalItem } from "@/resources/goals"

import { EmptyState } from "./empty-state"

/* One goal, as the list of the goals draws it — a card, or the page it opens on.
 *
 * Read in this order: what the goal is, when it is due, what says it is met,
 * and how far its tickets have gone. The count is the line the card is for, so
 * it is written in words as well as drawn: a bar alone says "about half", and
 * "3 of 7 tickets done" is what was asked.
 */

/** "n of m tickets done", and the bar under it. */
function Progress({ goal }: { goal: Goal }) {
  const t = useT()
  const { done, total } = progressOf(goal)
  // Strings, not numbers: the dictionary leaves a parameter that is 0 unsaid.
  // In the form the total asks for: « 0 sur 1 ticket fait », not « tickets faits ».
  const form = count(total, "{{done}} of {{count}} ticket done", "{{done}} of {{count}} tickets done")
  const said = t(form.key, { ...form.params, done: String(done) })
  return (
    <div className="flex flex-col gap-1.5" data-slot="goal-progress">
      <span className="text-muted-foreground text-xs tabular-nums">{said}</span>
      <div
        className="bg-muted h-1.5 overflow-hidden rounded-full"
        role="progressbar"
        aria-label={said}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
      >
        <div className="bg-primary h-full rounded-full" style={{ width: total ? `${(100 * done) / total}%` : "0%" }} />
      </div>
    </div>
  )
}

function Due({ due }: { due: string }) {
  const t = useT()
  if (!due) return null
  return (
    <span className="text-muted-foreground inline-flex items-center gap-1 text-xs" title={t("Due")}>
      <CalendarDays className="size-3.5" />
      {dueOf(due, locale())}
    </span>
  )
}

function GoalCard({ goal }: { goal: Goal }) {
  const t = useT()
  return (
    <li
      data-slot="goals-item"
      data-goal={goal.id}
      className="bg-card flex flex-col gap-3 rounded-xl border p-4 text-sm"
    >
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <ResourceViewButton action={ActionList.read} id={goal.id}>
            <span data-slot="goals-title" className="hover:text-primary font-medium underline-offset-2 hover:underline">
              {goal.name}
            </span>
          </ResourceViewButton>
          <div className="flex shrink-0 items-center gap-1">
            {goal.status ? <Badge variant="secondary">{goal.status}</Badge> : null}
            <ResourceViewButton action={ActionList.update} id={goal.id}>
              <span data-slot="goals-edit" title={t("Edit the goal")} aria-label={`${t("Edit the goal")} — ${goal.name}`}>
                <Pencil className="text-muted-foreground hover:text-foreground size-3.5" />
              </span>
            </ResourceViewButton>
          </div>
        </div>
        <Due due={goal.due} />
      </div>
      {goal.criterion ? <p className="text-muted-foreground line-clamp-3 leading-relaxed">{goal.criterion}</p> : null}
      <div className="mt-auto">
        <Progress goal={goal} />
      </div>
    </li>
  )
}

export function GoalCards({ rows = [] }: ListComponentPropsInterface) {
  return (
    <div className="@container w-full">
      <ul className="grid grid-cols-1 gap-3 @2xl:grid-cols-2 @5xl:grid-cols-3" data-slot="goals-items">
        {rows.map((row) => {
          const goal = row.data as GoalItem | undefined
          return goal ? <GoalCard key={goal.id} goal={goal} /> : null
        })}
      </ul>
      <div className="mt-5">
        <ListPagination />
      </div>
    </div>
  )
}

/* -- the page --------------------------------------------------------------- */

export function GoalPage() {
  const goal = useCurrentViewResourceContext().data as GoalItem | undefined
  if (!goal) return <Skeleton className="h-40 w-full" />
  return <GoalWhole goal={goal} />
}

function GoalWhole({ goal }: { goal: Goal }) {
  const t = useT()
  const { columns } = useBoard()
  // In the board's order, under the board's words for its columns.
  const counted = columns
    .map((column) => ({ key: column.key, name: column.name || t("Draft"), count: goal.tickets[column.key] ?? 0 }))
    .filter((column) => column.count)
  const facts = [
    { label: t("Done when"), value: goal.criterion },
    { label: t("Priority"), value: goal.priority },
    { label: t("Projects"), value: goal.projects.join(", ") },
  ].filter((fact) => fact.value)
  return (
    <article data-slot="goals-page" className="flex max-w-2xl flex-col gap-5 pb-6">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {goal.status ? <Badge variant="secondary">{goal.status}</Badge> : null}
          <Due due={goal.due} />
        </div>
        <h2 className="text-lg leading-snug font-semibold">{goal.name}</h2>
      </div>
      {goal.description ? <p className="text-sm leading-relaxed whitespace-pre-line">{goal.description}</p> : null}
      {facts.length ? (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
          {facts.map((fact) => (
            <div key={fact.label} className="contents">
              <dt className="text-muted-foreground">{fact.label}</dt>
              <dd>{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <Progress goal={goal} />
      {counted.length ? (
        <ul className="flex flex-wrap gap-1.5" data-slot="goal-columns">
          {counted.map((column) => (
            <li key={column.key}>
              <Badge variant="outline" className="gap-1.5">
                {column.name}
                <span className="text-muted-foreground tabular-nums">{column.count}</span>
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <ResourceViewButton action={ActionList.update} id={goal.id}>
          <span data-slot="goal-edit" className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
            <Pencil />
            {t("Edit")}
          </span>
        </ResourceViewButton>
        <ArchiveGoal goal={goal} />
        {goal.url ? (
          <a
            href={goal.url}
            target="_blank"
            rel="noreferrer"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
          >
            <ExternalLink />
            {t("Open in Notion")}
          </a>
        ) : null}
      </div>
    </article>
  )
}

/* Archived after a confirmation: the goal goes to Notion's trash, where it can
 * be brought back, and the tickets that served it simply serve none. */
function ArchiveGoal({ goal }: { goal: Goal }) {
  const t = useT()
  const navigate = useNavigate()
  const confirm = async () => {
    try {
      await api.deleteGoal(goal.id)
    } catch (error) {
      toast.error(t("The goal could not be archived"), { description: why(error) })
      return false
    }
    toast.success(t("Goal “{{name}}” archived", { name: goal.name }))
    await goalsOnce().catch(() => null)
    // The list holds the card it drew: told it is gone, it draws without it.
    goals.onChange.publish({ data: goal as GoalItem, action: ActionList.delete })
    void navigate({ to: goalsHref() })
  }
  return (
    <ConfirmDialog
      title={t("Archive “{{name}}”?", { name: goal.name })}
      description={t("The goal goes to Notion's trash. Its tickets stay where they are, and serve no goal.")}
      destructive
      confirm={
        <>
          <Trash2 />
          {t("Archive the goal")}
        </>
      }
      onConfirm={confirm}
      trigger={
        <Button type="button" variant="outline" size="sm" data-archive-goal>
          <Trash2 />
          {t("Archive")}
        </Button>
      }
    />
  )
}

/* -- nothing to show --------------------------------------------------------- */

export function NoGoal() {
  const t = useT()
  const { filterContext } = useListViewContext()
  const { configured, problem } = useGoals()
  if (problem) return <EmptyState robot="error">{problem}</EmptyState>
  if (!filterContext.filterIsEmpty)
    return (
      <EmptyState
        icon={SearchX}
        title={t("No goal matches these filters.")}
        action={
          <Button variant="outline" size="sm" onClick={() => filterContext.resetFilter({})}>
            <X />
            {t("Clear the filters")}
          </Button>
        }
      >
        {t("Another status or project, and they will be back.")}
      </EmptyState>
    )
  return (
    <EmptyState icon={Target} title={t("No goal yet.")}>
      {configured
        ? t("A goal is a row of the Goals database in Notion; a ticket points at it through its Goal column.")
        : t("The workspace has no Goals database: add one in Notion, and its rows show here.")}
    </EmptyState>
  )
}
