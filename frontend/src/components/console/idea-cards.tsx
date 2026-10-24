import * as React from "react"
import { Bookmark, ExternalLink, Lightbulb, Pencil, Plus, RotateCcw, SearchX, X } from "lucide-react"
import { ActionList } from "react-data-form"
import {
  Link,
  ListPagination,
  ResourceViewButton,
  useCurrentViewResourceContext,
  useListViewContext,
  useNavigate,
  type ListComponentPropsInterface,
} from "react-resource-view"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { EVERY_STATUS, keeps, statusOf, toneOf, type Tone } from "@/lib/idea-search"
import type { Idea, IdeaAuthor, IdeaCategory, IdeaStatus } from "@/lib/types"
import { cn } from "@/lib/utils"
import { SCOPED_IDEAS, ideaOf, ideasChanged, useIdeas, type IdeaItem } from "@/resources/ideas"
import { projectHref } from "@/resources/projects"
import { ticketHref } from "@/resources/tickets"

import { EmptyState } from "./empty-state"
import { IdeaOrigin } from "./idea-origin"
import { Robot } from "./robot"
import { ago } from "./ticket-bits"

/* One idea, as the list of the ideas draws it — a card, a row of the table, or
 * the page it opens on.
 *
 * Read in this order: what the idea is (its title, then where it stands and
 * what it is about),
 * why (a few lines of it), then who and when, small. And one gesture in plain
 * sight, the one the idea is waiting for: turning it into a ticket — or, once
 * it is one, opening that ticket. Keeping it for later, throwing it away and
 * making it new again sit beside it in the foot of the card, one click each
 * (a toast offers to take it back); rewording it is the pencil at the top,
 * which opens the package's form. Its score sits first, a number in a
 * coloured circle: the number is always written, so the colour is never all
 * it says.
 *
 * The gestures are not the package's: they are the endpoints an idea has
 * (`/keep`, `/discard`, `/reopen`, `/ticket`), and after one of them the list is
 * told the way a form tells it — see `ideasChanged`.
 */

/** What a status is called on a card, and on its filter. */
export function useStatusWords() {
  const t = useT()
  return {
    one: {
      proposed: t("New"),
      kept: t("Kept"),
      discarded: t("Thrown"),
      ticket: t("Turned into a ticket"),
    } satisfies Record<IdeaStatus, string>,
    many: {
      proposed: t("New ideas"),
      kept: t("Kept ideas"),
      discarded: t("Thrown ideas"),
      ticket: t("Became tickets"),
    } satisfies Record<IdeaStatus, string>,
  }
}

/** The colour a status is said in: a dot and a word, the same in both themes. */
const TONE: Record<IdeaStatus, string> = {
  proposed: "bg-primary",
  kept: "bg-emerald-500",
  discarded: "bg-muted-foreground/60",
  ticket: "bg-violet-500",
}

function StatusBadge({ status }: { status: IdeaStatus }) {
  const words = useStatusWords()
  return (
    <Badge variant="outline" className="text-muted-foreground gap-1.5 rounded-full font-normal">
      <span className={cn("size-1.5 rounded-full", TONE[status])} aria-hidden />
      <span data-slot="ideas-status">{words.one[status]}</span>
    </Badge>
  )
}

/* What each category is called, on a card, on its filter and in the form: the
 * developers' words, the same in every language — like a ticket's sub-type
 * (subtypes.py), they are the words of the tickets and the commits, and read
 * wrong translated. Not to be put through `t()`, nor into french.ts. */
export const CATEGORY_WORDS: Record<Exclude<IdeaCategory, "">, string> = {
  ux: "UX/UI",
  feature: "Feature",
  security: "Security",
  technical: "Tech",
}

/* A tint each, so a list is sorted at a glance — security the loudest, since
 * it is the one to deal with first. */
const CATEGORY_TONE: Record<Exclude<IdeaCategory, "">, string> = {
  ux: "border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-300",
  feature: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  security: "border-rose-500/40 bg-rose-500/15 text-rose-700 dark:text-rose-300",
  technical: "border-slate-500/30 bg-slate-500/10 text-slate-700 dark:text-slate-300",
}

/** The category an idea was sorted into; nothing for one nobody sorted. */
export function CategoryBadge({ category }: { category: IdeaCategory }) {
  if (!category) return null
  return (
    <Badge
      variant="outline"
      className={cn("rounded-full font-normal", CATEGORY_TONE[category])}
      data-slot="ideas-category"
      data-category={category}
    >
      {CATEGORY_WORDS[category]}
    </Badge>
  )
}

/* The colour of a score, in the tints the categories use: readable on a light
 * card and on a dark one. Not scored is grey, and says so in words. */
const SCORE_TONE: Record<Tone, string> = {
  green: "border-emerald-500/40 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  orange: "border-amber-500/45 bg-amber-500/15 text-amber-700 dark:text-amber-300",
  red: "border-rose-500/40 bg-rose-500/15 text-rose-700 dark:text-rose-300",
  unscored: "border-border bg-muted text-muted-foreground",
}

/** What a colour is called, on the pill's label and on its filter. */
export function useToneWords(): Record<Tone, string> {
  const t = useT()
  return {
    green: t("Green (70 and up)"),
    orange: t("Orange (40 to 69)"),
    red: t("Red (under 40)"),
    unscored: t("Not scored"),
  }
}

/** The score: its number in a circle of its colour, why in the tooltip — "…" while it is being given. */
export function ScoreBadge({ idea, className }: { idea: Pick<Idea, "score" | "score_reason" | "score_error" | "scoring">; className?: string }) {
  const t = useT()
  const tone = toneOf(idea.score)
  const scored = tone !== "unscored"
  const label = scored
    ? t("Relevance {{score}} out of 100", { score: String(idea.score) })
    : idea.scoring
      ? t("Being scored…")
      : idea.score_error
        ? t("Not scored — try again")
        : t("Not scored")
  const pill = (
    <span
      data-slot="ideas-score"
      data-tone={idea.scoring && !scored ? "scoring" : tone}
      aria-label={label}
      tabIndex={0}
      className={cn(
        "inline-flex h-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tabular-nums",
        scored || idea.scoring ? "min-w-7 px-1" : "px-2 font-normal",
        SCORE_TONE[tone],
        className
      )}
    >
      {scored ? idea.score : idea.scoring ? "…" : label}
    </span>
  )
  return (
    <Tooltip>
      <TooltipTrigger asChild>{pill}</TooltipTrigger>
      <TooltipContent className="max-w-64" data-slot="ideas-score-reason">
        <span className="font-medium">{label}</span>
        {scored && idea.score_reason ? <span className="block">{idea.score_reason}</span> : null}
        {!scored && !idea.scoring && idea.score_error ? <span className="block">{idea.score_error}</span> : null}
      </TooltipContent>
    </Tooltip>
  )
}

function KindBadge({ kind }: { kind: Idea["kind"] }) {
  const t = useT()
  return (
    <Badge
      variant={kind === "project" ? "default" : "secondary"}
      className="rounded-full font-normal"
      data-slot="ideas-kind"
    >
      {kind === "project" ? t("New project") : t("Ticket")}
    </Badge>
  )
}

/* -- the gestures ---------------------------------------------------------- */

type Gesture = "keep" | "discard" | "reopen" | "ticket"

/** The four decisions, and the one being written. */
function useGestures(idea: Idea) {
  const t = useT()
  const navigate = useNavigate()
  const [busy, setBusy] = React.useState(false)
  const run = async (gesture: Gesture, undoing = false) => {
    const call = {
      keep: api.keepIdea,
      discard: api.discardIdea,
      reopen: api.reopenIdea,
      ticket: api.ticketIdea,
    }[gesture]
    setBusy(true)
    try {
      const done = await call(idea.id)
      if (gesture === "ticket") {
        // What it became, a click away — the answer names it.
        const target = idea.kind === "project" ? done.created : done.ticket
        toast.success(
          idea.kind === "project"
            ? t("Project created: {{title}}", { title: idea.title })
            : t("Ticket created: {{title}}", { title: idea.title }),
          target
            ? {
                action: {
                  label: idea.kind === "project" ? t("Open the project") : t("Open the ticket"),
                  onClick: () =>
                    void navigate({ to: idea.kind === "project" ? projectHref(target) : ticketHref(target) }),
                },
              }
            : undefined
        )
      }
      if (gesture !== "ticket" && !undoing) {
        // The gesture that puts the idea back where it stood — none from a ticket.
        const back = { proposed: "reopen", kept: "keep", discarded: "discard" }[idea.status as "proposed" | "kept" | "discarded"] as
          | Gesture
          | undefined
        toast(
          {
            keep: t("Idea kept: {{title}}", { title: idea.title }),
            discard: t("Idea thrown away: {{title}}", { title: idea.title }),
            reopen: t("Idea back to new: {{title}}", { title: idea.title }),
            ticket: "",
          }[gesture],
          back ? { action: { label: t("Undo"), onClick: () => void run(back, true) } } : undefined
        )
      }
      ideasChanged(done)
    } catch (error) {
      toast.error(t("The decision could not be saved"), { description: why(error) })
    } finally {
      setBusy(false)
    }
  }
  // A ticket is on the board: it is made new again before anything else is decided.
  const offered: { gesture: Gesture; label: string; shown: boolean }[] = [
    { gesture: "discard", label: t("Throw away"), shown: idea.status === "proposed" || idea.status === "kept" },
    { gesture: "keep", label: t("Keep"), shown: idea.status === "proposed" || idea.status === "discarded" },
    { gesture: "reopen", label: t("Back to new"), shown: idea.status !== "proposed" },
  ]
  const secondary = offered.filter((one) => one.shown)
  return { busy, run, secondary }
}

/** The one gesture an idea is waiting for: becoming a ticket, or the ticket it became. */
function MainAction({ idea, busy, onTicket, className }: { idea: Idea; busy: boolean; onTicket: () => void; className?: string }) {
  const t = useT()
  if (idea.status === "ticket")
    return idea.ticket ? (
      <Link
        to={idea.kind === "project" && idea.created ? projectHref(idea.created) : ticketHref(idea.ticket)}
        data-slot="ideas-open"
        className={cn(buttonVariants({ variant: "outline", size: "sm" }), className)}
      >
        <ExternalLink />
        {idea.kind === "project" ? t("Open the project") : t("Open the ticket")}
      </Link>
    ) : null
  return (
    <Button size="sm" data-slot="ideas-ticket" disabled={busy} className={className} onClick={onTicket}>
      <Plus />
      {idea.kind === "project" ? t("Create the project") : t("Turn into a ticket")}
    </Button>
  )
}

/** The pencil: the package's form, over the list. None for an idea that is already a ticket. */
function EditButton({ idea }: { idea: Idea }) {
  const t = useT()
  if (idea.status === "ticket") return null
  return (
    <ResourceViewButton action={ActionList.update} id={String(idea.id)}>
      <span
        data-slot="ideas-edit"
        title={t("Edit")}
        className={cn(buttonVariants({ variant: "ghost", size: "icon-sm" }), "text-muted-foreground")}
      >
        <Pencil />
        <span className="sr-only">{t("Edit")}</span>
      </span>
    </ResourceViewButton>
  )
}

/** The gestures beside the main one, one click each: icon alone where the foot is too narrow for a word. */
function Gestures({
  busy,
  choices,
  onRun,
}: {
  busy: boolean
  choices: { gesture: Gesture; label: string }[]
  onRun: (gesture: Gesture) => void
}) {
  const ICON = { keep: Bookmark, discard: X, reopen: RotateCcw, ticket: Plus }
  return (
    <>
      {choices.map((choice) => {
        const Icon = ICON[choice.gesture]
        return (
          <Button
            key={choice.gesture}
            size="sm"
            variant="outline"
            data-slot={`ideas-${choice.gesture}`}
            disabled={busy}
            aria-label={choice.label}
            title={choice.label}
            className={cn("@max-sm:size-8 @max-sm:px-0", choice.gesture === "discard" && "text-muted-foreground")}
            onClick={() => onRun(choice.gesture)}
          >
            <Icon />
            <span className="@max-sm:sr-only">{choice.label}</span>
          </Button>
        )
      })}
    </>
  )
}

/** The title, as the way into the idea's page. */
function TitleLink({ idea, className }: { idea: Idea; className?: string }) {
  return (
    <ResourceViewButton action={ActionList.read} id={String(idea.id)}>
      <span
        data-slot="ideas-title"
        title={idea.title}
        className={cn(
          "hover:text-primary underline-offset-2 hover:underline",
          idea.status === "discarded" && "text-muted-foreground",
          className
        )}
      >
        {idea.title}
      </span>
    </ResourceViewButton>
  )
}

/** Whether the list is the page of every scope, where an idea says whom it is for. */
function useNamed(): boolean {
  return useCurrentViewResourceContext().resource?.["@id"] !== SCOPED_IDEAS
}

/* -- the card layout ------------------------------------------------------- */

function IdeaCard({ idea, named }: { idea: Idea; named: boolean }) {
  const t = useT()
  const { busy, run, secondary } = useGestures(idea)
  return (
    <li
      data-slot="ideas-item"
      data-idea={idea.id}
      data-status={idea.status}
      data-author={idea.author.kind}
      className={cn(
        "bg-card text-card-foreground flex min-w-0 flex-col gap-3 rounded-2xl border p-4 shadow-xs transition-colors",
        "hover:border-primary/40 dark:hover:border-primary/50",
        idea.status === "discarded" && "bg-muted/30"
      )}
    >
      <div className="flex min-w-0 items-start gap-2">
        <ScoreBadge idea={idea} className="-mt-0.5" />
        <h3 className="min-w-0 flex-1 text-[0.95rem] leading-snug font-semibold">
          <TitleLink idea={idea} className="line-clamp-2" />
        </h3>
        <div className="-mt-1 -mr-1.5 flex shrink-0 items-center">
          <EditButton idea={idea} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge status={idea.status} />
        <CategoryBadge category={idea.category} />
        <KindBadge kind={idea.kind} />
      </div>

      {idea.description ? (
        <p className="text-muted-foreground line-clamp-3 text-sm leading-relaxed whitespace-pre-line">{idea.description}</p>
      ) : null}

      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        <Byline author={idea.author} when={idea.created_at} />
        {named ? <IdeaOrigin project={idea.kind === "project" ? "" : idea.project} /> : null}
      </div>
      {idea.edited ? (
        <p className="text-muted-foreground -mt-1.5 flex items-center gap-1.5 text-[0.7rem]" data-slot="ideas-edited">
          <Pencil className="size-3" />
          {t("Edited by {{name}}", { name: idea.edited.name || t("you") })}
          {ago(idea.edited.at) ? ` · ${ago(idea.edited.at)}` : ""}
        </p>
      ) : null}

      <div className="@container mt-auto flex items-center gap-2 border-t pt-3" data-slot="ideas-foot">
        <Gestures busy={busy} choices={secondary} onRun={(gesture) => void run(gesture)} />
        <MainAction idea={idea} busy={busy} onTicket={() => void run("ticket")} className="ml-auto" />
      </div>
    </li>
  )
}

/** The card layout: one column in a narrow place, two or three where there is room. */
export function IdeaCards({ rows = [] }: ListComponentPropsInterface) {
  const named = useNamed()
  return (
    <div className="@container w-full">
      <ul className="grid grid-cols-1 gap-3 @2xl:grid-cols-2 @5xl:grid-cols-3" data-slot="ideas-items">
        {rows.map((row) => {
          const idea = row.data as IdeaItem | undefined
          return idea ? <IdeaCard key={idea.id} idea={ideaOf(idea)} named={named} /> : null
        })}
      </ul>
      <div className="mt-5">
        <ListPagination />
      </div>
    </div>
  )
}

/* -- the table layout ------------------------------------------------------ */

/** The columns of a row, shared by the heading and every row so they line up. */
const COLUMNS =
  "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 px-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_7.5rem_10.5rem_minmax(0,1.4fr)_15.5rem]"

function IdeaRow({ idea, named }: { idea: Idea; named: boolean }) {
  const { busy, run, secondary } = useGestures(idea)
  return (
    <li
      data-slot="ideas-item"
      data-idea={idea.id}
      data-status={idea.status}
      data-author={idea.author.kind}
      className={cn(COLUMNS, "hover:bg-accent/40 border-b py-2.5 text-sm last:border-b-0")}
    >
      <span className="flex min-w-0 items-center gap-2.5">
        <ScoreBadge idea={idea} />
        <span className="flex min-w-0 flex-col gap-0.5">
        <TitleLink idea={idea} className="block truncate font-medium" />
        <span className="flex min-w-0 items-center gap-1.5 md:hidden">
          <StatusBadge status={idea.status} />
          <CategoryBadge category={idea.category} />
        </span>
        </span>
      </span>
      <span className="hidden min-w-0 md:block">
        {named ? <IdeaOrigin project={idea.kind === "project" ? "" : idea.project} /> : <KindBadge kind={idea.kind} />}
      </span>
      <span className="hidden md:block">
        <CategoryBadge category={idea.category} />
      </span>
      <span className="hidden md:block">
        <StatusBadge status={idea.status} />
      </span>
      <span className="hidden min-w-0 md:block">
        <Byline author={idea.author} when={idea.created_at} />
      </span>
      <span className="@container flex items-center justify-end gap-1">
        <Gestures busy={busy} choices={secondary} onRun={(gesture) => void run(gesture)} />
        <MainAction idea={idea} busy={busy} onTicket={() => void run("ticket")} className="h-7 px-2 text-xs" />
        <EditButton idea={idea} />
      </span>
    </li>
  )
}

/** The table layout: to go down a long list, one line per idea. */
export function IdeaRows({ rows = [] }: ListComponentPropsInterface) {
  const t = useT()
  const named = useNamed()
  return (
    <div className="w-full">
      <div className="bg-card overflow-hidden rounded-md border">
        <div className={cn(COLUMNS, "text-muted-foreground border-b py-2 text-xs font-medium")} aria-hidden>
          <span>{t("Idea")}</span>
          <span className="hidden md:block">{named ? t("For") : t("Type")}</span>
          <span className="hidden md:block">{t("Category")}</span>
          <span className="hidden md:block">{t("Status")}</span>
          <span className="hidden md:block">{t("Written by")}</span>
          <span />
        </div>
        <ul data-slot="ideas-items">
          {rows.map((row) => {
            const idea = row.data as IdeaItem | undefined
            return idea ? <IdeaRow key={idea.id} idea={ideaOf(idea)} named={named} /> : null
          })}
        </ul>
      </div>
      <div className="mt-5">
        <ListPagination />
      </div>
    </div>
  )
}

/* -- one idea, read ------------------------------------------------------- */

/** An idea whole: every line of it, what Ponos wrote it should touch and leave alone, and every gesture. */
export function IdeaPage() {
  const idea = useCurrentViewResourceContext().data as IdeaItem | undefined
  if (!idea) return <Skeleton className="h-40 w-full" />
  return <IdeaWhole idea={ideaOf(idea)} />
}

function IdeaWhole({ idea }: { idea: Idea }) {
  const t = useT()
  const { busy, run, secondary } = useGestures(idea)
  const lists = [
    { label: t("Done when"), lines: idea.done },
    { label: t("Out of scope"), lines: idea.out },
  ].filter((one) => one.lines.length)
  return (
    <article data-slot="ideas-page" className="flex max-w-2xl flex-col gap-5 pb-6">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <ScoreBadge idea={idea} />
          <StatusBadge status={idea.status} />
          <CategoryBadge category={idea.category} />
          <KindBadge kind={idea.kind} />
        </div>
        <h2 className="text-lg leading-snug font-semibold">{idea.title}</h2>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <Byline author={idea.author} when={idea.created_at} />
          <IdeaOrigin project={idea.kind === "project" ? "" : idea.project} />
        </div>
      </div>
      {idea.description ? (
        <p className="text-sm leading-relaxed whitespace-pre-line">{idea.description}</p>
      ) : null}
      {idea.score !== null && idea.score_reason ? (
        <section className="flex flex-col gap-1" data-slot="ideas-page-score">
          <h3 className="text-muted-foreground text-xs font-medium">
            {t("Relevance {{score}} out of 100", { score: String(idea.score) })}
          </h3>
          <p className="text-sm">{idea.score_reason}</p>
        </section>
      ) : null}
      {idea.where ? (
        <section className="flex flex-col gap-1">
          <h3 className="text-muted-foreground text-xs font-medium">{t("Where")}</h3>
          <p className="text-sm">{idea.where}</p>
        </section>
      ) : null}
      {lists.map((list) => (
        <section key={list.label} className="flex flex-col gap-1">
          <h3 className="text-muted-foreground text-xs font-medium">{list.label}</h3>
          <ul className="list-disc space-y-0.5 pl-5 text-sm">
            {list.lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
      ))}
      <div className="flex flex-wrap items-center gap-2 border-t pt-4">
        <MainAction idea={idea} busy={busy} onTicket={() => void run("ticket")} />
        {secondary.map((choice) => (
          <Button
            key={choice.gesture}
            size="sm"
            variant="ghost"
            disabled={busy}
            data-slot={`ideas-${choice.gesture}`}
            onClick={() => void run(choice.gesture)}
          >
            {choice.label}
          </Button>
        ))}
        <span className="flex-1" />
        <EditButton idea={idea} />
      </div>
    </article>
  )
}

/* -- nothing to show ------------------------------------------------------ */

/** The way to write one: the package's create form, as a button that says so. */
export function NewIdeaButton({ className }: { className?: string }) {
  const t = useT()
  return (
    <ResourceViewButton action={ActionList.create}>
      <span data-slot="ideas-new" className={cn(buttonVariants({ size: "sm" }), className)}>
        <Plus />
        {t("New idea")}
      </span>
    </ResourceViewButton>
  )
}

/** An empty list: no idea yet, with the way to write one — or none that the filters keep, with the way back. */
export function NoIdea() {
  const t = useT()
  const { filterContext } = useListViewContext()
  const { ideas: known } = useIdeas()
  // The list rests on the new ideas: with none, the others are one click away, and never shown unasked.
  if (
    statusOf(filterContext.filter) === "proposed" &&
    known?.some((idea) => keeps(idea, { ...filterContext.filter, status: EVERY_STATUS }))
  )
    return (
      <EmptyState
        robot="sleep"
        title={t("No new idea.")}
        action={
          <Button variant="outline" size="sm" onClick={() => filterContext.updateFilter({ status: EVERY_STATUS })}>
            {t("Show all")}
          </Button>
        }
      >
        {t("Every idea is sorted: kept, thrown away or turned into a ticket.")}
      </EmptyState>
    )
  if (!filterContext.filterIsEmpty)
    return (
      <EmptyState
        icon={SearchX}
        title={t("No idea matches these filters.")}
        action={
          <Button variant="outline" size="sm" onClick={() => filterContext.resetFilter({})}>
            <X />
            {t("Clear the filters")}
          </Button>
        }
      >
        {t("Another status, category, score, author or project, and they will be back.")}
      </EmptyState>
    )
  return (
    <EmptyState robot="sleep" title={t("No idea yet.")} action={<NewIdeaButton />}>
      <span className="inline-flex items-center gap-1.5">
        <Lightbulb className="size-4" aria-hidden />
        {t("Write one, or ask Ponos for a batch.")}
      </span>
    </EmptyState>
  )
}

/* -- who wrote it ---------------------------------------------------------- */

/** Who wrote it: the mascot for Ponos, the picture or the initials of a person. */
export function Byline({ author, when }: { author: IdeaAuthor; when: string }) {
  const t = useT()
  const name = author.kind === "ponos" ? "Ponos" : author.name || t("you")
  return (
    <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs" data-slot="ideas-author">
      <Avatar author={author} />
      <span className="text-foreground/80 truncate font-medium">{name}</span>
      {ago(when) ? <span className="shrink-0">· {ago(when)}</span> : null}
    </span>
  )
}

function Avatar({ author }: { author: IdeaAuthor }) {
  const [broken, setBroken] = React.useState(false)
  const frame = "bg-muted flex size-5 shrink-0 items-center justify-center overflow-hidden rounded-full"
  if (author.kind === "ponos")
    return (
      <span className={frame} data-slot="ideas-avatar-ponos">
        <Robot state="idle" size={16} still />
      </span>
    )
  if (author.avatar && !broken)
    return (
      <img
        src={author.avatar}
        alt=""
        className={cn(frame, "object-cover")}
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
      />
    )
  const initials = author.name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]!.toUpperCase())
    .join("")
  return (
    <span className={cn(frame, "text-[0.55rem] font-semibold")} aria-hidden="true">
      {initials || "?"}
    </span>
  )
}
