import * as React from "react"
import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { TicketDetail } from "@/lib/types"

import { TicketHead, TicketPage } from "./ticket-page"

/* A ticket's page, on its own: what it draws before its brief is read, which
 * tab it opens on, and what it says when something could not be read — what
 * `e2e/ticket.spec.ts` and `e2e/talk.spec.ts` ask of it over a real board.
 *
 * Around it, only what it reads: the record react-resource-view holds, the
 * console's open ticket, the address. The tabs' contents — the discussion, the
 * session, the decision — are tested where they live, and stand here as one
 * line each that says which one is on show.
 */

const world = vi.hoisted(() => ({
  context: {} as { data?: unknown; error?: boolean; loadError?: unknown; fetchData: () => void },
  open: null as unknown,
  talk: [] as { role: string }[],
  talkWaiting: false,
  sessions: [] as { source: string }[],
  searchStr: "",
  params: {} as Record<string, unknown>,
  replace: (_to: string) => {},
  read: (_id: string, _edited?: string): Promise<{ content: string }> => Promise.resolve({ content: "" }),
}))

vi.mock("react-resource-view", async (original) => ({
  ...(await original<typeof import("react-resource-view")>()),
  useCurrentViewResourceContext: () => world.context,
  Link: ({ to, children, ...props }: { to: string; children: React.ReactNode }) => (
    <a href={to} {...props}>
      {children}
    </a>
  ),
}))

vi.mock("@tanstack/react-router", async (original) => ({
  ...(await original<typeof import("@tanstack/react-router")>()),
  useLocation: () => ({ pathname: "/", searchStr: world.searchStr }),
  useRouter: () => ({ history: { replace: (to: string) => world.replace(to) } }),
}))

vi.mock("@/lib/router", () => ({ useRoute: () => ({ params: world.params }) }))

vi.mock("@/hooks/use-console", () => ({
  useConsole: () => ({
    ticket: world.open,
    openTicket: () => {},
    talk: world.talk,
    talkWaiting: world.talkWaiting,
    board: { columns: [] },
  }),
  useSteps: () => ({ sessions: world.sessions }),
  moveWithToast: () => {},
}))

vi.mock("@/resources/tickets", () => ({
  boardHref: () => "/board",
  holdTicket: () => {},
  releaseTicket: () => {},
  readTicket: (id: string, edited?: string) => world.read(id, edited),
  tickets: {},
}))

vi.mock("@/resources/projects", () => ({ projectHref: (id: string) => `/projects/${id}` }))

vi.mock("./ticket-bits", async (original) => ({
  ...(await original<typeof import("./ticket-bits")>()),
  TicketActions: () => null,
  TicketLinks: () => null,
}))

vi.mock("./session-log", () => ({
  Pulse: () => null,
  TicketLive: () => <p>the session's journal</p>,
}))

vi.mock("./ticket-talk", () => ({ TicketTalk: () => <p>the discussion</p> }))

vi.mock("./ticket-on", () => ({ TicketOn: () => null }))

vi.mock("./ticket-decision", async () => {
  const { createContext } = await import("react")
  return {
    WINDOW_TAB: "ticket-tab",
    TicketTabContext: createContext(null),
    DecideButton: () => null,
    TicketDecision: ({ onDone }: { onDone: () => void }) => (
      <button type="button" onClick={onDone}>
        the decision, sent
      </button>
    ),
  }
})

const ID = "000000000000000000000000000abcde"

function ticket(change: Partial<TicketDetail> = {}): TicketDetail {
  return {
    id: ID,
    short: "000abcde",
    title: "A long ticket",
    url: "",
    status: "Ready",
    column: "ready",
    project: "",
    kind: "",
    type: "",
    priority: null,
    model: "",
    progress: "",
    runner: "",
    pull_request: "",
    session: "",
    session_link: "",
    cost: null,
    duration: null,
    scheduled: "",
    created: "",
    edited: "2026-10-01T10:00:00.000Z",
    content: "",
    ...change,
  }
}

/** The page of `page`, with its brief read once `brief` resolves. */
function drawn(page: TicketDetail | undefined, brief: Promise<{ content: string }> = new Promise(() => {})) {
  world.context = { data: page, fetchData: vi.fn() }
  const read = vi.fn(() => brief)
  world.read = read
  render(<TicketPage />)
  return read
}

const tabs = () => screen.getAllByRole("tab").map((tab) => tab.textContent)
const selected = () => screen.getAllByRole("tab").find((tab) => tab.getAttribute("aria-selected") === "true")?.textContent

beforeEach(() => {
  world.open = null
  world.talk = []
  world.talkWaiting = false
  world.sessions = []
  world.searchStr = ""
  world.params = { resourceAction: "read", id: ID }
  world.replace = vi.fn()
})

describe("before the brief is read", () => {
  test("the card's facts are drawn at once, and the brief asked for once", async () => {
    let answer!: (detail: { content: string }) => void
    const read = drawn(ticket(), new Promise((resolve) => (answer = resolve)))

    const summary = document.querySelector<HTMLElement>('[data-slot="ticket-summary"]')!
    expect(within(summary).getByText("Ticket")).toBeTruthy()
    expect(within(summary).getByText("no project — a document")).toBeTruthy()
    expect(screen.getByRole("tabpanel").querySelector('[aria-busy="true"]')).not.toBeNull()
    expect(read).toHaveBeenCalledExactlyOnceWith(ID, ticket().edited)

    await act(async () => answer({ content: "Part 40" }))
    expect(screen.getByRole("tabpanel").textContent).toContain("Part 40")
    expect(read).toHaveBeenCalledOnce()
  })

  test("a page with nothing under its title says so", async () => {
    drawn(ticket(), Promise.resolve({ content: "" }))
    expect(await screen.findByText("The page is empty: the title is the whole brief.")).toBeTruthy()
  })

  test("a brief that could not be read says why, and is asked for again", async () => {
    const user = userEvent.setup()
    const read = drawn(ticket(), Promise.reject(new Error("Notion did not answer")))
    expect(await screen.findByText("Notion did not answer")).toBeTruthy()
    expect(screen.getByText("This ticket could not be read.")).toBeTruthy()
    await user.click(screen.getByRole("button", { name: "Try again" }))
    expect(read).toHaveBeenCalledTimes(2)
  })

  test("a ticket the board could not give says why, and asks again", async () => {
    const user = userEvent.setup()
    world.context = { error: true, loadError: new Error("No such ticket"), fetchData: vi.fn() }
    render(<TicketPage />)
    expect(screen.getByText("This ticket could not be read.")).toBeTruthy()
    expect(screen.getByText("No such ticket")).toBeTruthy()
    expect(screen.getByRole("link", { name: "Back to the board" }).getAttribute("href")).toBe("/board")
    await user.click(screen.getByRole("button", { name: "Try again" }))
    expect(world.context.fetchData).toHaveBeenCalledOnce()
  })
})

describe("the summary", () => {
  test("a ticket that never ran has no Execution column", () => {
    drawn(ticket({ project: "Opoil", type: "Code", subtype: "" }))
    const summary = document.querySelector<HTMLElement>('[data-slot="ticket-summary"]')!
    expect(within(summary).getByText("Opoil")).toBeTruthy()
    expect(within(summary).queryByText("Execution")).toBeNull()
  })

  test("one that ran says its pull request, its cost, its model and its session", async () => {
    const user = userEvent.setup()
    drawn(
      ticket({
        column: "done",
        pull_request: "https://github.com/hermez/ponos/pull/385",
        cost: 1.5,
        model: "claude-opus-4-1-20250805",
        model_label: "claude/opus",
        session: "3f2a9c1e-0000-4000-8000-000000000000",
        runner: "workstation",
      })
    )
    const summary = document.querySelector<HTMLElement>('[data-slot="ticket-summary"]')!
    expect(within(summary).getByText("Execution")).toBeTruthy()
    expect(within(summary).getByRole("link", { name: "PR #385" }).getAttribute("href")).toBe(
      "https://github.com/hermez/ponos/pull/385"
    )
    expect(within(summary).getByText("$1.50")).toBeTruthy()
    expect(within(summary).getByTitle("claude-opus-4-1-20250805").textContent).toBe("opus")
    expect(within(summary).getByText("workstation")).toBeTruthy()
    // The session's id opens its tab.
    await user.click(within(summary).getByRole("button", { name: "3f2a9c1e" }))
    expect(selected()).toBe("Live")
  })
})

describe("the tabs", () => {
  test("a ticket neither running nor waiting opens on its brief, and the tab picked is written in the address", async () => {
    const user = userEvent.setup()
    drawn(ticket())
    expect(tabs()).toEqual(["Brief", "Discussion", "Live"])
    expect(selected()).toBe("Brief")

    await user.click(screen.getByRole("tab", { name: "Live" }))
    expect(selected()).toBe("Live")
    expect(screen.getByRole("tabpanel").textContent).toBe("the session's journal")
    expect(world.replace).toHaveBeenLastCalledWith("/?tab=live")
  })

  test("a running ticket opens on its session", () => {
    drawn(ticket({ column: "running" }))
    expect(screen.getByRole("tab", { name: /^Live/ }).getAttribute("aria-selected")).toBe("true")
    expect(screen.getByText("writing now")).toBeTruthy()
  })

  test("a blocked ticket opens on its discussion, marked as waiting on you", () => {
    drawn(ticket({ column: "blocked" }))
    expect(selected()).toBe("Discussion")
    expect(screen.getByLabelText("a question is waiting for you")).toBeTruthy()
    // No tab of its own to unblock it: the question is answered in the discussion.
    expect(tabs()).toEqual(["Brief", "Discussion", "Live"])
  })

  test("the discussion's tab counts what was said, not the lines saying it could not be read", () => {
    world.open = ticket()
    world.talk = [{ role: "user" }, { role: "assistant" }, { role: "error" }]
    drawn(ticket())
    expect(screen.getByRole("tab", { name: /Discussion/ }).textContent).toBe("Discussion2")
  })

  test("the address picks the tab, and an old unblock reads as the discussion", () => {
    world.searchStr = "?view=console/tickets/read/x&tab=unblock"
    drawn(ticket())
    expect(selected()).toBe("Discussion")
  })

  test("a ticket in review has a Decide tab, which goes once the decision is sent", async () => {
    const user = userEvent.setup()
    drawn(ticket({ column: "review" }))
    expect(tabs()).toEqual(["Brief", "Discussion", "Live", "Decide"])
    expect(screen.getByLabelText("your decision is awaited")).toBeTruthy()

    await user.click(screen.getByRole("tab", { name: /Decide/ }))
    await user.click(screen.getByRole("button", { name: "the decision, sent" }))
    await waitFor(() => expect(tabs()).toEqual(["Brief", "Discussion", "Live"]))
    expect(selected()).toBe("Discussion")
  })
})

describe("the header", () => {
  test("says the title and the short id, and has a way back to the dashboard", () => {
    world.context = { data: ticket(), fetchData: vi.fn() }
    render(<TicketHead />)
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("A long ticket")
    expect(screen.getByText("#000abcde")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Copy the full id" })).toBeTruthy()
    expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("href")).toBe("/board")
  })

  test("follows the stream where it has the same ticket", () => {
    world.context = { data: ticket(), fetchData: vi.fn() }
    world.open = ticket({ title: "A long ticket, renamed" })
    render(<TicketHead />)
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("A long ticket, renamed")
  })
})
