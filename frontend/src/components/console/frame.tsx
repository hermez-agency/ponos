import * as React from "react"

import { cn } from "@/lib/utils"

/* The shapes every pane of the console is built from.
 *
 * Four of them, and they are the whole design language: a mono label too small
 * to read as prose, which is how the console says what a thing *is*; a heading
 * block, which is how a pane opens; a grid of facts, which is how a ticket
 * states its metadata; and a panel, which is a card that announces itself.
 *
 * They live together in one file because they are one decision — change the
 * tracking on `Eyebrow` and the board, the sessions, the settings and a ticket
 * all change with it, which is the point of having them at all.
 */

/** The mono label over a heading, a panel or a fact. Small enough that it reads as a tag, not a sentence. */
export function Eyebrow({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        "text-muted-foreground font-mono text-[0.65rem] font-semibold tracking-[0.14em] uppercase",
        className
      )}
    >
      {children}
    </span>
  )
}

/* How a page opens: its icon, its name, the line under it, and — at the right
 * edge — the gesture the page exists to offer.
 *
 * It is the header react-resource-view draws over its own lists (the projects,
 * the ideas, the schedules), in the same markup and under the same slot, so
 * that a page the package does not list — the settings, the sessions — opens
 * like the ones it does, and what `index.css` says of theirs holds for it too.
 *
 * Where you are is not said here: the bar above every pane already says it, and
 * a path printed twice, one line under the other, reads as a page that has lost
 * count of itself. This is the same reason the board opens on the package's own
 * header rather than on a `PageHead` of its own. */
export function PageHead({
  icon: Icon,
  title,
  blurb,
  action,
  children,
  className,
}: {
  icon?: React.ElementType<{ className?: string }>
  title: string
  blurb?: string
  /** The page's own gesture, against the right edge on anything wider than a phone. */
  action?: React.ReactNode
  /** Under the blurb: a switch, a filter, whatever the page is steered with. */
  children?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("mb-6", className)}>
      <div data-slot="list-header" className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b pb-4">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          {Icon ? (
            <span className="bg-muted text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-xl">
              <Icon className="size-5" />
            </span>
          ) : null}
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold tracking-tight">{title}</h2>
            {blurb ? <p className="text-muted-foreground text-sm">{blurb}</p> : null}
          </div>
        </div>
        {action ? (
          <div
            data-slot="list-header-controls"
            className="flex w-full flex-wrap items-center gap-2 md:ms-auto md:w-auto md:justify-end"
          >
            {action}
          </div>
        ) : null}
      </div>
      {children ? <div className="mt-4 flex flex-wrap items-center gap-2">{children}</div> : null}
    </div>
  )
}

/** A card that says what it is before it says anything else. */
export function Panel({
  eyebrow,
  title,
  action,
  children,
  className,
  bodyClassName,
}: {
  eyebrow: string
  title?: React.ReactNode
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={cn("bg-card rounded-xl border", className)}>
      <header className="flex items-start justify-between gap-3 px-4 pt-3.5 pb-3">
        <div className="min-w-0">
          <Eyebrow>{eyebrow}</Eyebrow>
          {title ? (
            <h3 className="mt-1 text-base leading-tight font-semibold tracking-[-0.01em]">
              {title}
            </h3>
          ) : null}
        </div>
        {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
      </header>
      <div className={cn("px-4 pb-4", bodyClassName)}>{children}</div>
    </section>
  )
}

/** One figure, as the statistics draw them in a row: what it is, the number, and a line under it. */
export function Tile({
  label,
  value,
  note,
  more,
  children,
}: {
  label: string
  value: React.ReactNode
  note?: React.ReactNode
  /** Under the pointer: how the figure was arrived at. */
  more?: string
  /** Under the note: what the number is made of. */
  children?: React.ReactNode
}) {
  return (
    <section className="bg-card min-w-0 rounded-xl border px-3.5 py-2.5" title={more ?? (typeof note === "string" ? note : undefined)}>
      <Eyebrow>{label}</Eyebrow>
      <p className="mt-1 text-2xl leading-none font-bold tracking-[-0.03em] tabular-nums">{value}</p>
      {note ? <p className="text-muted-foreground mt-1 truncate text-[0.7rem]">{note}</p> : null}
      {children}
    </section>
  )
}

/* A ticket's metadata, as a ruled grid rather than a list of pills: two
 * columns of cells sharing their edges, each cell a label and the answer under
 * it. Read down the labels and you know what is written about a ticket without
 * reading a single value. */
export function Facts({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        // The rule between two cells is drawn by the second of them — the top
        // edge of everything past the first row, the left edge of everything in
        // the second column — so the grid never doubles a line against its own
        // border, whether it holds an even number of facts or an odd one.
        "grid grid-cols-2 rounded-xl border",
        "[&>*:nth-child(n+3)]:border-t [&>*:nth-child(even)]:border-l",
        className
      )}
    >
      {children}
    </div>
  )
}

/** One cell of {@link Facts}: what it is, and what it says. */
export function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 px-3.5 py-3">
      <Eyebrow>{label}</Eyebrow>
      <div className="mt-1 truncate text-sm font-semibold">{children}</div>
    </div>
  )
}
