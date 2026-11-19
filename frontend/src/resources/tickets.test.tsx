import { describe, expect, test } from "vitest"

import { applyChanges, publishBoard } from "@/lib/board-store"
import type { Board, Ticket } from "@/lib/types"
import { tickets, type TicketItem } from "./tickets"

/* The rows the board's list is drawn from, as the stream moves the board.
 *
 * A move of the board rereads the whole list (`DashboardTop`): a row made
 * again for every ticket was 600 ms of every move on a board of 2 000, and a
 * card drawn again for each, however memoised. A ticket the move left alone
 * gives the very same row; only the ones that moved are made again. */

const ticket = (id: string, more: Partial<Ticket> = {}): Ticket =>
  ({ id, title: `Ticket ${id}`, column: "done", edited: "2026-11-01T10:00:00Z", ...more }) as unknown as Ticket

const rows = async (): Promise<TicketItem[]> => {
  const read = (await tickets.getCollection({})) as unknown as { data: { items: TicketItem[] } }
  return read.data.items
}

describe("the board's rows", () => {
  test("a ticket the stream did not change gives the same row, a changed one a new row", async () => {
    const board: Board = {
      version: 1,
      columns: [],
      tickets: [ticket("a"), ticket("b", { column: "running", cost: 2.5 }), ticket("c")],
    }
    publishBoard(board)
    const before = await rows()
    expect(before.map((row) => row.id)).toEqual(["a", "b", "c"])

    const moved = ticket("b", { column: "review", cost: 3 })
    expect(applyChanges({ base: 1, version: 2, changed: [{ after: "a", ticket: moved }], removed: [] })).not.toBeNull()
    const after = await rows()

    expect(after.map((row) => row.id)).toEqual(["a", "b", "c"])
    expect(after[0]).toBe(before[0])
    expect(after[2]).toBe(before[2])
    expect(after[1]).not.toBe(before[1])
    expect(after[1].column).toBe("review")
    expect(after[1].spent).toBe("$3.00")
  })

  test("the age is not frozen in the row: it keeps the instant, said where it is drawn", async () => {
    publishBoard({ version: 7, columns: [], tickets: [ticket("d", { edited: "2026-11-02T08:30:00Z" })] })
    const [row] = await rows()
    expect(row.changed).toBe("2026-11-02T08:30:00Z")
  })
})
