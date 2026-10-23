import * as React from "react"

import { Eyebrow } from "./frame"

// Not in `frame.tsx`: the statistics and a schedule's panel draw it, and neither
// is in the first load that file is part of.
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
