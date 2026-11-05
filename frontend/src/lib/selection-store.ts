import * as React from "react"

import { rangeOf } from "./bulk"

/* The cards selected on the board, outside React.
 *
 * A card is memoised on its ticket (see `TicketCardBody`): a selection held in
 * a context, or in the list's state, would draw all of them again at every
 * tick of a box. Each card asks this store whether it is selected, and only the
 * cards whose answer changed draw again — plus all of them once, when the
 * board enters or leaves the selection, since a click then means something
 * else on every card.
 *
 * The selection is by ticket id and outlives a move: a ticket launched from
 * the bar goes to Ready and leaves the selection with the bar's own gesture,
 * not with the board's next read. Ids the board no longer holds are the bar's
 * to leave out (see `BulkBar`).
 */

let selected: ReadonlySet<string> = new Set()
/** The card clicked last, where a Shift-click runs from. */
let anchor: string | null = null
const listeners = new Set<() => void>()

const tell = () => listeners.forEach((listener) => listener())

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function replace(next: Set<string>) {
  selected = next
  tell()
}

/** One card in or out of the selection — or, with Shift, the run of cards from the one clicked last. */
export function pick(id: string, order: string[] = [], run = false) {
  const next = new Set(selected)
  if (run && anchor !== null) {
    // A run takes the state of the card it ends on: Shift on a selected card
    // takes the whole run out, on another one puts it in.
    const on = !selected.has(id)
    for (const one of rangeOf(order, anchor, id)) {
      if (on) next.add(one)
      else next.delete(one)
    }
  } else if (next.has(id)) next.delete(id)
  else next.add(id)
  anchor = id
  replace(next)
}

/** All these in, or all of them out when they already all are: a column's box. */
export function pickAll(ids: string[]) {
  const next = new Set(selected)
  const all = ids.length > 0 && ids.every((id) => next.has(id))
  for (const id of ids) {
    if (all) next.delete(id)
    else next.add(id)
  }
  replace(next)
}

/** Out of the selection: after a gesture of the bar, Escape, or its ×. */
export function clearSelection() {
  anchor = null
  if (selected.size) replace(new Set())
}

export const currentSelection = (): ReadonlySet<string> => selected

/** The ids selected, the same set until it changes. */
export function useSelection(): ReadonlySet<string> {
  return React.useSyncExternalStore(subscribe, () => selected)
}

/** Whether this card is selected: true or false, so a card draws again only when its own answer changes. */
export function useSelected(id: string): boolean {
  return React.useSyncExternalStore(subscribe, () => selected.has(id))
}

/** Whether the board is selecting at all — a click on a card then selects it rather than opening it. */
export function useSelecting(): boolean {
  return React.useSyncExternalStore(subscribe, () => selected.size > 0)
}
