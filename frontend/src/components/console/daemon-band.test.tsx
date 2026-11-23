import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { publishBoard } from "@/lib/board-store"
import type { Board, Ticket } from "@/lib/types"

import { DAEMON_FRENCH, startCommand } from "./daemon-band"
import { RunnerStrip } from "./runner-strip"

/* No daemon running, said once over the board rather than on every ready card:
 * how many cards it holds back, and the line that starts it, to copy. */

const world: { daemon: string } = { daemon: "stopped" }

vi.mock("@/hooks/use-console", () => ({
  useConsole: () => ({ runner: { daemon: world.daemon, claude: true } }),
  useStatus: () => ({ running: [] }),
}))

const copied: string[] = []
vi.mock("@/lib/copy", () => ({
  copy: (text: string) => {
    copied.push(text)
    return Promise.resolve(true)
  },
}))

const card = (id: string, column: string, reason?: string) =>
  ({ id, title: id, column, held: reason ? { reason, detail: "" } : undefined }) as unknown as Ticket

function board(...tickets: Ticket[]) {
  publishBoard({ version: 1, columns: [], tickets } as unknown as Board)
}

const band = () => document.querySelector('[data-slot="daemon-band"]')
/** The band is fetched when it is drawn: found once its module is in. */
const drawn = () => screen.findByText("No daemon is running: ready tickets wait.")

beforeEach(() => {
  world.daemon = "stopped"
  copied.length = 0
})

afterEach(cleanup)

describe("the daemon band", () => {
  test("says it once, with the number of ready tickets it holds back", async () => {
    board(
      card("a", "ready", "daemon"),
      card("b", "ready", "daemon"),
      card("c", "ready", "date"),
      card("d", "review")
    )
    render(<RunnerStrip />)
    await drawn()
    expect(document.querySelector('[data-slot="daemon-band-count"]')?.textContent).toBe("2 tickets concerned")
  })

  test("gives the line that starts the daemon, to copy", async () => {
    board(card("a", "ready", "daemon"))
    render(<RunnerStrip />)
    await drawn()
    expect(band()?.querySelector("code")?.textContent).toBe("ponos daemon")
    screen.getByRole("button", { name: "Copy" }).click()
    expect(copied).toEqual(["ponos daemon"])
  })

  test("is gone once a daemon runs", () => {
    world.daemon = "running"
    board(card("a", "ready", "daemon"))
    render(<RunnerStrip />)
    expect(band()).toBeNull()
  })

  test("says nothing when no ticket waits for it", () => {
    board(card("a", "ready", "date"), card("b", "done"))
    render(<RunnerStrip />)
    expect(band()).toBeNull()
  })
})

describe("the line that starts it", () => {
  test.each([
    ["stopped", "ponos daemon"],
    ["no systemd", "ponos daemon"],
    ["disabled", "ponos service on"],
    ["inactive", "ponos service on"],
    ["failed", "ponos service on"],
  ])("%s: %s", (state, command) => {
    expect(startCommand(state)).toBe(command)
  })
})

test("every sentence of the band has its French", () => {
  for (const [english, french] of Object.entries(DAEMON_FRENCH)) expect(french, english).not.toBe("")
  expect(DAEMON_FRENCH["No daemon is running: ready tickets wait."]).toBe(
    "Aucun démon ne tourne : les tickets prêts attendent."
  )
})
