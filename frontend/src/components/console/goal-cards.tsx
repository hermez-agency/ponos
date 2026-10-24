import * as React from "react"
import { Ban, CalendarDays, CircleCheck, ExternalLink, Pencil, Plus, SearchX, Target, Trash2, X } from "lucide-react"
import { toast } from "sonner"
import { ActionList } from "react-data-form"
import {
  generateLinkByResource,
  Link,
  ListPagination,
  ResourceViewButton,
  useCurrentViewResourceContext,
  useListViewContext,
  useNavigate,
  useViewLink,
  type ListComponentPropsInterface,
} from "react-resource-view"

import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api, why } from "@/lib/api"
import { useBoard } from "@/lib/board-store"
import { byDeadline, deadlineOf, todayOf } from "@/lib/goal-deadline"
import { EVERY_STATUS, dueOf, keeps, progressOf } from "@/lib/goal-search"
import { onGoalsMoved } from "@/lib/goals-store"
import { useFrench, useT } from "@/lib/i18n"
import { count } from "@/lib/numbers"
import { locale } from "@/lib/recurrence"
import { carrying } from "@/lib/resource-view"
import type { Goal } from "@/lib/types"
import { cn } from "@/lib/utils"
import { goalHref, goals, goalsHref, goalsOnce, useGoals, type GoalItem } from "@/resources/goals"
import { ticketHref, tickets } from "@/resources/tickets"

import { EmptyState } from "./empty-state"
import { Eyebrow } from "./frame"
import { useOpensOverTheList } from "./record-window"
import { SEED, columnTitle, reachable } from "./ticket-bits"

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

/** The due date, and beside it whether the goal is late or close to it. */
function Due({ goal }: { goal: Goal }) {
  const t = useT()
  if (!goal.due) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className="text-muted-foreground inline-flex items-center gap-1 text-xs" title={t("Due")}>
        <CalendarDays className="size-3.5" />
        {dueOf(goal.due, locale())}
      </span>
      <Deadline goal={goal} />
    </span>
  )
}

/* The badge's words, in French: fetched when one is drawn, see `goal-french.ts`. */
const words = () => import("@/lib/goal-french").then((module) => module.GOAL_FRENCH)

function Deadline({ goal }: { goal: Goal }) {
  const t = useT()
  const ready = useFrench(words)
  const deadline = deadlineOf(goal, todayOf())
  // Not drawn in English while its French is on the way.
  if (!deadline || !ready) return null
  if (deadline.late)
    return (
      <Badge variant="destructive" data-slot="goal-deadline" data-late>
        {t("Late")}
      </Badge>
    )
  const form = count(deadline.days, "In {{count}} day", "In {{count}} days")
  return (
    <Badge variant="outline" data-slot="goal-deadline">
      {deadline.days ? t(form.key, form.params) : t("Today")}
    </Badge>
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
        <Due goal={goal} />
      </div>
      {goal.criterion ? <p className="text-muted-foreground line-clamp-3 leading-relaxed">{goal.criterion}</p> : null}
      <div className="mt-auto">
        <Progress goal={goal} />
      </div>
    </li>
  )
}

/* The rows are every goal the filters keep, in Notion's order: drawn soonest due first. */
export function GoalCards({ rows = [] }: ListComponentPropsInterface) {
  const drawn = byDeadline(rows.flatMap((row) => (row.data ? [row.data as GoalItem] : [])))
  return (
    <div className="@container w-full">
      <ul className="grid grid-cols-1 gap-3 @2xl:grid-cols-2 @5xl:grid-cols-3" data-slot="goals-items">
        {drawn.map((goal) => (
          <GoalCard key={goal.id} goal={goal} />
        ))}
      </ul>
      <div className="mt-5">
        <ListPagination />
      </div>
    </div>
  )
}

/* -- under a project ---------------------------------------------------------- */

/* The goals a project serves, on its page: the active ones only, each with how
 * far its tickets have gone, and the way to the list of every one of them —
 * the Goals page, kept to the project. A goal names its projects by name, as
 * the list's filter does. Nothing at all for a project that serves none: the
 * page has enough to say without an empty box. */
export function ProjectGoals({ project }: { project: string }) {
  const t = useT()
  const { goals: known } = useGoals()
  React.useEffect(() => {
    void goalsOnce().catch(() => null)
  }, [])
  const mine = (known ?? []).filter((goal) => goal.active !== false && goal.projects.includes(project))
  if (!mine.length) return null
  const every = generateLinkByResource({ resource: goals, resourceAction: ActionList.list, filter: { project } })
  return (
    <section data-slot="project-goals" className="@container flex flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-center justify-between gap-3">
        <Eyebrow>{t("Goals")}</Eyebrow>
        <Link
          to={every}
          data-slot="project-goals-all"
          className="text-muted-foreground hover:text-foreground text-xs underline-offset-2 hover:underline"
        >
          {t("See every goal of the project")}
        </Link>
      </div>
      <ul className="grid grid-cols-1 gap-4 @2xl:grid-cols-2">
        {mine.map((goal) => (
          <li key={goal.id} data-goal={goal.id} className="flex min-w-0 flex-col gap-1.5 text-sm">
            <div className="flex min-w-0 items-center gap-2">
              <Link to={goalHref(goal.id)} className="hover:text-primary truncate font-medium underline-offset-2 hover:underline">
                {goal.name}
              </Link>
              <Due goal={goal} />
            </div>
            <Progress goal={goal} />
          </li>
        ))}
      </ul>
    </section>
  )
}

/* -- the page --------------------------------------------------------------- */

export function GoalPage() {
  const view = useCurrentViewResourceContext()
  const goal = view.data as GoalItem | undefined
  // The package reads a list again when the goals move, not a page: this one
  // does it itself, from the request the lists are read again by.
  const fetchData = React.useRef(view.fetchData)
  fetchData.current = view.fetchData
  React.useEffect(() => onGoalsMoved(() => void fetchData.current?.()), [])
  // Drawn from the row the last read holds: the item read again is the form's,
  // its tickets a list of ids where the count wants them by column.
  const row = useGoals().goals?.find((one) => one.id === goal?.id)
  if (!goal) return <Skeleton className="h-40 w-full" />
  return <GoalWhole goal={row ?? goal} reread={() => void fetchData.current?.()} />
}

function GoalWhole({ goal, reread }: { goal: Goal; reread: () => void }) {
  const t = useT()
  const facts = [
    { label: t("Done when"), value: goal.criterion },
    { label: t("Priority"), value: goal.priority === null ? "" : String(goal.priority) },
    { label: t("Projects"), value: goal.projects.join(", ") },
  ].filter((fact) => fact.value)
  return (
    <article data-slot="goals-page" className="flex max-w-2xl flex-col gap-5 pb-6">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {goal.status ? <Badge variant="secondary">{goal.status}</Badge> : null}
          <Due goal={goal} />
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
      <GoalTickets goal={goal} />
      <div className="flex flex-wrap items-center gap-2">
        <ResourceViewButton action={ActionList.update} id={goal.id}>
          <span data-slot="goal-edit" className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
            <Pencil />
            {t("Edit")}
          </span>
        </ResourceViewButton>
        {CLOSINGS.map((closing) =>
          goal.status === closing.status ? null : (
            <CloseGoal key={closing.status} goal={goal} closing={closing} reread={reread} />
          )
        )}
        {/* A Markdown board's page is a file:// address, and no Notion to open. */}
        {reachable(goal.url) ? (
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
        <DeleteGoal goal={goal} />
      </div>
    </article>
  )
}

/* The tickets that serve it, under the board's columns and in the board's
 * order — each one a way into its window over the page — and "+ Ticket" for
 * one more: the dashboard's "New ticket", with the goal already in its field. */
function GoalTickets({ goal }: { goal: Goal }) {
  const t = useT()
  const { columns } = useBoard()
  const create = useViewLink({ resource: tickets, action: ActionList.create })
  const linked = goal.linked ?? []
  // A column the board no longer draws still says where its tickets stand, after the others.
  const keys = [...new Set([...columns.map((column) => column.key), ...linked.map((ticket) => ticket.column)])]
  const groups = keys
    .map((key) => ({
      key,
      name: columns.find((column) => column.key === key)?.name || (key ? columnTitle(key) : t("Draft")),
      tickets: linked.filter((ticket) => ticket.column === key),
    }))
    .filter((group) => group.tickets.length)
  return (
    <section className="flex flex-col gap-3" data-slot="goal-tickets">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">{t("Tickets")}</h3>
        <Link
          to={carrying(create.to, { goal: goal.id })}
          onClick={create.onOpen}
          data-slot="goal-new-ticket"
          className={cn(buttonVariants({ variant: "outline", size: "sm" }), "whitespace-nowrap")}
        >
          <Plus />
          {t("Ticket")}
        </Link>
      </div>
      {groups.length ? (
        <div className="flex flex-col gap-3" data-slot="goal-columns">
          {groups.map((group) => (
            <div key={group.key} data-goal-column={group.key} className="flex flex-col gap-1.5">
              <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
                <span className={cn("size-1.5 rounded-full", SEED[group.key] ?? "bg-muted-foreground")} />
                {group.name}
                <span className="tabular-nums">{group.tickets.length}</span>
              </span>
              <ul className="overflow-hidden rounded-md border">
                {group.tickets.map((ticket) => (
                  <GoalTicketRow key={ticket.id} ticket={ticket} />
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">{t("No ticket serves this goal yet.")}</p>
      )}
    </section>
  )
}

function GoalTicketRow({ ticket }: { ticket: NonNullable<Goal["linked"]>[number] }) {
  const open = useOpensOverTheList(tickets, "read", ticket.id)
  return (
    <li
      data-goal-ticket={ticket.id}
      className="flex min-w-0 items-baseline gap-2 border-b px-3 py-2 text-sm last:border-b-0"
    >
      {ticket.short ? <span className="text-muted-foreground shrink-0 font-mono text-xs">#{ticket.short}</span> : null}
      <Link to={ticketHref(ticket.id)} onClick={open} className="truncate hover:underline" title={ticket.title}>
        {ticket.title}
      </Link>
    </li>
  )
}

/* Two ways a goal is over, each a status of the goals database: written, the
 * goal stays — its page, its tickets and its count with it —, and the list,
 * which rests on the active ones, no longer shows it unasked. */
const CLOSINGS = [
  { status: "atteint", label: "Reached", said: "Goal “{{name}}” reached", icon: CircleCheck },
  { status: "abandonné", label: "Given up", said: "Goal “{{name}}” given up", icon: Ban },
] as const

function CloseGoal({
  goal,
  closing,
  reread,
}: {
  goal: Goal
  closing: (typeof CLOSINGS)[number]
  reread: () => void
}) {
  const t = useT()
  const [busy, setBusy] = React.useState(false)
  const Icon = closing.icon
  const close = async () => {
    setBusy(true)
    try {
      await api.saveGoal(goal.id, { status: closing.status })
    } catch (error) {
      toast.error(t("The goal could not be changed"), { description: why(error) })
      return
    } finally {
      setBusy(false)
    }
    toast.success(t(closing.said, { name: goal.name }))
    await goalsOnce().catch(() => null)
    goals.onChange.publish({ data: goal as GoalItem, action: ActionList.update })
    reread()
  }
  return (
    <Button type="button" variant="outline" size="sm" disabled={busy} onClick={close} data-close-goal={closing.status}>
      <Icon />
      {t(closing.label)}
    </Button>
  )
}

/* Deleted after a confirmation, and said so: the goal goes to Notion's trash —
 * or its file to the board's, on a board of Markdown files — where it can be
 * brought back, and the tickets that served it simply serve none. Set apart
 * from the statuses, since a goal that is over is closed, not deleted. */
function DeleteGoal({ goal }: { goal: Goal }) {
  const t = useT()
  const markdown = useGoals().storage === "markdown"
  // Its words on a Markdown board are in `goal-french.ts`: fetched before the dialog opens.
  useFrench(words)
  const navigate = useNavigate()
  const confirm = async () => {
    try {
      await api.deleteGoal(goal.id)
    } catch (error) {
      toast.error(t("The goal could not be deleted"), { description: why(error) })
      return false
    }
    toast.success(t("Goal “{{name}}” deleted", { name: goal.name }))
    await goalsOnce().catch(() => null)
    // The list holds the card it drew: told it is gone, it draws without it.
    goals.onChange.publish({ data: goal as GoalItem, action: ActionList.delete })
    void navigate({ to: goalsHref() })
  }
  return (
    <ConfirmDialog
      title={t("Delete “{{name}}”?", { name: goal.name })}
      description={
        markdown
          ? t(
              "The goal is deleted: its file goes to the board's trash. Its tickets stay where they are, and serve no goal. To close a goal that is over, mark it reached or given up instead."
            )
          : t(
              "The goal is deleted: it goes to Notion's trash, with its count. Its tickets stay where they are, and serve no goal. To close a goal that is over, mark it reached or given up instead."
            )
      }
      destructive
      confirm={
        <>
          <Trash2 />
          {t("Delete the goal")}
        </>
      }
      onConfirm={confirm}
      trigger={
        <Button type="button" variant="ghost" size="sm" className="text-destructive ml-auto" data-delete-goal>
          <Trash2 />
          {t("Delete")}
        </Button>
      }
    />
  )
}

/* -- nothing to show --------------------------------------------------------- */

export function NoGoal() {
  const t = useT()
  const { filterContext } = useListViewContext()
  const { configured, storage, problem, goals: known } = useGoals()
  // A Markdown board's sentence is in `goal-french.ts`, as the badge's words are.
  const ready = useFrench(words)
  if (problem) return <EmptyState robot="error">{problem}</EmptyState>
  // The list rests on the active goals: with none, the closed ones are one click away.
  if (
    !String(filterContext.filter.status ?? "") &&
    known?.some((goal) => keeps(goal, { ...filterContext.filter, status: EVERY_STATUS }))
  )
    return (
      <EmptyState
        icon={Target}
        title={t("No active goal.")}
        action={
          <Button variant="outline" size="sm" onClick={() => filterContext.updateFilter({ status: EVERY_STATUS })}>
            {t("Show all")}
          </Button>
        }
      >
        {t("Every goal is reached or given up.")}
      </EmptyState>
    )
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
  // Written from here only where there is a Goals database to write it in.
  return configured ? (
    <EmptyState icon={Target} title={t("No goal.")} action={<NewGoalButton />}>
      {t("Write one, then point the tickets that serve it at it.")}
    </EmptyState>
  ) : (
    <EmptyState icon={Target} title={t("No goal.")}>
      {storage !== "markdown"
        ? t("The workspace has no Goals database: add one in Notion, and goals can be written here.")
        : ready
          ? t("The board has no goals/ folder: add one, and goals can be written here.")
          : null}
    </EmptyState>
  )
}

/** "New goal", the button the empty list offers: the same form as the one over the list. */
function NewGoalButton() {
  const t = useT()
  return (
    <ResourceViewButton action={ActionList.create}>
      <span data-slot="goals-new" className={buttonVariants({ size: "sm" })}>
        <Plus />
        {t("New goal")}
      </span>
    </ResourceViewButton>
  )
}
