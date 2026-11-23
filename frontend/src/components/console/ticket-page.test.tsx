import * as React from "react"
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test, vi } from "vitest"

import { ApiError } from "@/lib/api"
import { publishBoard } from "@/lib/board-store"
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

// The ticket's gestures, as one button that asks for the Decide tab the way
// `DecideButton` does: through the context the whole view is wrapped in.
vi.mock("./ticket-bits", async (original) => {
  const { use } = await import("react")
  const { TicketTabContext } = await import("./ticket-decision")
  return {
    ...(await original<typeof import("./ticket-bits")>()),
    TicketActions: () => {
      const tabs = use(TicketTabContext)
      return tabs && tabs.shown !== "decide" ? (
        <button type="button" onClick={() => tabs.goTo("decide")}>
          the gestures
        </button>
      ) : null
    },
  }
})

vi.mock("./session-log", () => ({ Pulse: () => null }))
vi.mock("./ticket-live", () => ({ TicketLive: () => <p>the session's journal</p> }))

vi.mock("./ticket-talk", () => ({ TicketTalk: () => <p>the discussion</p> }))

vi.mock("./ticket-on", () => ({ TicketOn: () => null }))
vi.mock("./ticket-validation", () => ({ TicketValidation: () => null }))

vi.mock("./ticket-decision", async () => {
  const { createContext } = await import("react")
  return {
    WINDOW_TAB: "ticket-tab",
    TicketTabContext: createContext<{ goTo: (tab: "decide") => void; shown?: string } | null>(null),
    DecideButton: () => null,
  }
})

vi.mock("./ticket-decision-panel", () => ({
  TicketDecision: ({ onDone }: { onDone: () => void }) => (
    <button type="button" onClick={onDone}>
      the decision, sent
    </button>
  ),
}))

const ID = "000000000000000000000000000abcde"

function ticket(change: Partial<TicketDetail> = {}): TicketDetail {
  return {
    id: ID,
    short: "000abcde",
    public_id: "PON-142",
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
    mission: "",
    result: "",
    results: [],
    journal: "",
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
/** The tabs' names, without what a badge says beside them. */
const names = () => tabs().map((name) => name?.replace(/writing now|your decision is awaited|a question is waiting for you/, ""))
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
    const read = drawn(ticket(), Promise.reject(new Error("The board did not answer")))
    expect(await screen.findByText("The board did not answer")).toBeTruthy()
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

  test("a ticket the board does not have says so, and offers only the way back", () => {
    const gone = new ApiError("no ticket with id 0000000000000000000000000000dead", 404)
    world.context = { error: true, loadError: gone, fetchData: vi.fn() }
    render(<TicketPage />)
    expect(screen.getByText("This ticket could not be found.")).toBeTruthy()
    expect(
      screen.getByText(
        "This ticket does not exist: it was deleted, or was never on this board."
      )
    ).toBeTruthy()
    expect(screen.queryByText(/no ticket with id/)).toBeNull()
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull()
    expect(screen.getByRole("link", { name: "Back to the board" }).getAttribute("href")).toBe("/board")
  })
})

describe("the summary", () => {
  test("a ticket that never ran says only what it is", () => {
    drawn(ticket({ project: "Opoil", type: "Code", subtype: "" }))
    const summary = document.querySelector<HTMLElement>('[data-slot="ticket-summary"]')!
    expect(within(summary).getByText("Opoil")).toBeTruthy()
    expect(within(summary).queryByTitle(/session|taken by/)).toBeNull()
  })

  test("one that ran says its cost, its model, its branch and its session, each under its name", async () => {
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
        branch: "ponos/une-branche-3f2a9c1e",
      })
    )
    const summary = document.querySelector<HTMLElement>('[data-slot="ticket-summary"]')!
    // The pull request is said once on the view, in its own block — not among the facts.
    expect(within(summary).queryByRole("link", { name: "PR #385" })).toBeNull()
    const delivery = document.querySelector<HTMLElement>('[data-slot="ticket-delivery"]')!
    expect(within(delivery).getByRole("link", { name: "PR #385" }).getAttribute("href")).toBe(
      "https://github.com/hermez/ponos/pull/385"
    )
    expect(screen.getAllByRole("link", { name: "PR #385" })).toHaveLength(1)
    expect(within(summary).getByText("$1.50").closest("div")?.querySelector("dt")?.textContent).toBe("Cost")
    expect(within(summary).getByTitle("claude-opus-4-1-20250805").textContent).toBe("opus")
    expect(within(summary).getByText("$1.50").closest("div")?.querySelector("dt")?.className).toContain("sr-only")
    // The rarer details are said in the page, one "Details" away — not in a tooltip.
    expect(within(summary).queryByText("workstation")).toBeNull()
    expect(within(summary).queryByText("ponos/une-branche-3f2a9c1e")).toBeNull()
    const more = within(summary).getByRole("button", { name: "Details" })
    await user.click(more)
    expect(more.getAttribute("aria-expanded")).toBe("true")
    expect(within(summary).getByText("workstation").closest("div")?.querySelector("dt")?.textContent).toBe("Taken by")
    expect(within(summary).getByText("$1.50").closest("div")?.querySelector("dt")?.className).not.toContain("sr-only")
    // The branch is among the facts, a link on the pull request's repository.
    const branch = within(summary).getByRole("link", { name: "ponos/une-branche-3f2a9c1e" })
    expect(branch.getAttribute("href")).toBe("https://github.com/hermez/ponos/tree/ponos/une-branche-3f2a9c1e")
    await user.click(within(summary).getByRole("button", { name: "3f2a9c1e" }))
    expect(selected()).toBe("Activity")
  })
})

describe("the tabs", () => {
  test("a ticket neither running nor waiting opens on its brief, and the tab picked is written in the address", async () => {
    const user = userEvent.setup()
    drawn(ticket())
    expect(tabs()).toEqual(["Mission", "Discussion", "Activity"])
    expect(selected()).toBe("Mission")

    await user.click(screen.getByRole("tab", { name: "Activity" }))
    expect(selected()).toBe("Activity")
    // The session and the journal, in one tab: the journal first once nothing runs.
    expect(screen.getByRole("tabpanel").textContent).toContain("the session's journal")
    expect(screen.getByRole("tabpanel").querySelector('[data-slot="ticket-journal"]')).not.toBeNull()
    expect(world.replace).toHaveBeenLastCalledWith("/?tab=live")
  })

  test("a running ticket opens on its session", () => {
    drawn(ticket({ column: "running" }))
    expect(screen.getByRole("tab", { name: /^Activity/ }).getAttribute("aria-selected")).toBe("true")
    expect(screen.getByText("writing now")).toBeTruthy()
  })

  test("a blocked ticket opens on its discussion, marked as waiting on you", () => {
    drawn(ticket({ column: "blocked" }))
    expect(selected()).toBe("Discussion")
    expect(screen.getByLabelText("a question is waiting for you")).toBeTruthy()
    // No tab of its own to unblock it: the question is answered in the discussion.
    expect(tabs()).toEqual(["Mission", "Discussion", "Activity"])
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

  test("a ticket not finished has its mission and no result; an address naming the result opens the mission", () => {
    for (const column of ["draft", "ready", "running", "blocked"] as const) {
      world.searchStr = "?tab=result"
      world.replace = vi.fn()
      drawn(ticket({ column }))
      expect(names()).toEqual(["Mission", "Discussion", "Activity"])
      expect(selected()).toBe("Mission")
      expect(world.replace).toHaveBeenLastCalledWith("/?tab=mission")
      cleanup()
    }
  })

  test("an old address naming the brief opens the mission", () => {
    world.searchStr = "?tab=brief"
    drawn(ticket({ column: "done" }))
    expect(selected()).toBe("Mission")
  })

  test("the Result tab comes, first, when the ticket goes into review under the reader — who stays where they are", () => {
    world.context = { data: ticket({ column: "running" }), fetchData: vi.fn() }
    const read = vi.fn(() => new Promise<{ content: string }>(() => {}))
    world.read = read
    world.open = ticket({ column: "running" })
    const { rerender } = render(<TicketPage />)
    expect(names()).toEqual(["Mission", "Discussion", "Activity"])
    expect(selected()).toMatch(/^Activity/)

    world.open = ticket({ column: "review" })
    rerender(<TicketPage />)
    expect(names()).toEqual(["Decide", "Result", "Mission", "Discussion", "Activity"])
    expect(selected()).toBe("Activity")
    // Its page is read again: the result it just wrote is what the tab shows.
    expect(read).toHaveBeenCalledTimes(2)
  })

  test("a ticket in review has a Decide tab, which goes once the decision is sent", async () => {
    const user = userEvent.setup()
    drawn(ticket({ column: "review" }))
    expect(tabs()).toEqual(["Decide", "Result", "Mission", "Discussion", "Activity"])
    expect(screen.getByLabelText("your decision is awaited")).toBeTruthy()

    await user.click(screen.getByRole("tab", { name: /Decide/ }))
    await user.click(screen.getByRole("button", { name: "the decision, sent" }))
    await waitFor(() => expect(names()).toEqual(["Result", "Mission", "Discussion", "Activity"]))
    expect(selected()).toBe("Discussion")
  })

  test("a ticket in review says first that it waits for a decision, and its gestures lead to the Decide tab", async () => {
    const user = userEvent.setup()
    drawn(ticket({ column: "review" }))
    const status = document.querySelector<HTMLElement>('[data-slot="ticket-status"]')!
    expect(within(status).getByText("In review")).toBeTruthy()
    expect(within(status).getByText("Your decision is awaited.")).toBeTruthy()
    // First on the view: before the facts, and before the tabs.
    const summary = document.querySelector('[data-slot="ticket-summary"]')!
    expect(status.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(status.compareDocumentPosition(screen.getByRole("tablist")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    await user.click(within(status).getByRole("button", { name: "the gestures" }))
    expect(selected()).toMatch(/^Decide/)
    expect(world.replace).toHaveBeenLastCalledWith("/?tab=decide")
    expect(within(status).queryByRole("button", { name: "the gestures" })).toBeNull()
  })

  test("the status says what each column waits for, and a blocked ticket its cause", () => {
    drawn(ticket({ column: "running" }))
    expect(screen.getByText("A session is working on it.")).toBeTruthy()
    cleanup()
    drawn(
      ticket({
        column: "blocked",
        block: {
          code: "session.question",
          family: "question",
          label: { en: "Question for you", fr: "Une question pour vous" },
          help: { en: "The session stopped to ask you something.", fr: "" },
        },
      } as Partial<TicketDetail>)
    )
    const block = document.querySelector<HTMLElement>('[data-slot="ticket-status"] [data-slot="ticket-block"]')!
    expect(block.getAttribute("data-code")).toBe("session.question")
    expect(within(block).getByText("Question for you")).toBeTruthy()
    expect(within(block).getByText("The session stopped to ask you something.")).toBeTruthy()
  })

  test("an old address naming the journal opens Activity, where it is read", () => {
    world.searchStr = "?tab=journal"
    drawn(ticket({ column: "done" }))
    expect(selected()).toBe("Activity")
  })
})

describe("the result", () => {
  const POST = "Trois choses apprises en livrant **Ponos**.\n\n1. Petit.\n2. Souvent."
  const done = (change: Partial<TicketDetail> = {}) =>
    ({
      content: "## Mission\n\nÉcris un post LinkedIn.",
      mission: "Écris un post LinkedIn.",
      result: POST,
      results: [
        { version: 2, text: POST, source: "edit", author: "Léa", at: "2026-11-02T10:00:00Z" },
        { version: 1, text: "Premier jet.", source: "session", author: "", at: "2026-11-01T10:00:00Z" },
      ],
      journal: "**Résultat** : ✅ post écrit\n\nJ'ai relu deux fois.",
      ...change,
    }) as unknown as { content: string }

  test("a ticket with a result opens on it, the mission in a tab of its own and the journal apart", async () => {
    const user = userEvent.setup()
    drawn(ticket({ column: "done", type: "Writing" }), Promise.resolve(done()))
    const result = await screen.findByText("Ponos")
    expect(selected()).toBe("Result")
    expect(tabs()).toEqual(["Result", "Mission", "Discussion", "Activity"])
    const body = result.closest<HTMLElement>('[data-slot="ticket-result-body"]')!
    expect(body.textContent).toContain("Trois choses apprises")
    // Neither the session's account nor the mission is mixed into the post.
    expect(screen.getByRole("tabpanel").textContent).not.toContain("J'ai relu deux fois.")
    expect(screen.getByRole("tabpanel").textContent).not.toContain("Écris un post LinkedIn.")

    await user.click(screen.getByRole("tab", { name: "Mission" }))
    expect(screen.getByRole("tabpanel").textContent).toContain("Écris un post LinkedIn.")
    expect(screen.getByRole("tabpanel").textContent).not.toContain("Trois choses apprises")
    expect(world.replace).toHaveBeenLastCalledWith("/?tab=mission")

    await user.click(screen.getByRole("tab", { name: "Activity" }))
    expect(screen.getByRole("tabpanel").textContent).toContain("J'ai relu deux fois.")
    // The facts are above the tabs, whichever is open.
    const summary = document.querySelector('[data-slot="ticket-summary"]')!
    expect(screen.getByRole("tablist").compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
  })

  test("an earlier version is shown in place of the last, and said to be one", async () => {
    const user = userEvent.setup()
    drawn(ticket({ column: "done" }), Promise.resolve(done()))
    await user.click(await screen.findByRole("button", { name: "Version 2" }))
    await user.click(await screen.findByRole("menuitem", { name: /Version 1/ }))
    expect(screen.getByText("Premier jet.")).toBeTruthy()
    expect(document.querySelector('[data-slot="ticket-result-older"]')?.textContent).toContain("by a session")
    await user.click(screen.getByRole("button", { name: "Back to the latest" }))
    expect(screen.queryByText("Premier jet.")).toBeNull()
  })

  test("a session that ran and rendered nothing is said so, rather than passing for done", async () => {
    drawn(ticket({ column: "review" }), Promise.resolve(done({ result: "", results: [] })))
    expect(await screen.findByText(/No result rendered/)).toBeTruthy()
    expect(selected()).toBe("Result")
  })

  test("the mission is drawn open, under one title, without the heading it was written with", async () => {
    world.searchStr = "?tab=mission"
    drawn(ticket({ column: "ready" }), Promise.resolve(done({ mission: "## Mission\n\nÉcris un post LinkedIn." })))
    expect(await screen.findByText("Écris un post LinkedIn.")).toBeTruthy()
    const panel = screen.getByRole("tabpanel")
    expect(panel.textContent?.match(/Mission/g)).toHaveLength(1)
    expect(within(panel).queryByRole("heading")).toBeNull()
    expect(within(panel).queryByRole("button")).toBeNull()
  })

  test("a code ticket that wrote no result points at its pull request and shows what changed in its place", async () => {
    drawn(
      ticket({ column: "review", type: "Code", pull_request: "https://github.com/hermez/ponos/pull/385" }),
      Promise.resolve(
        done({
          result: "",
          results: [],
          journal:
            "**Result:** ✅ two tabs\n\n**Pull request:** https://github.com/hermez/ponos/pull/385\n\nThe mission and the result each have their tab.\n\n### History\n\n- 2026-11-06 · 12 minutes",
        })
      )
    )
    await waitFor(() => expect(document.querySelector('[data-slot="ticket-result-is-pr"]')).not.toBeNull())
    // Said once, above the tabs: the result does not draw it a second time.
    expect(screen.getAllByRole("link", { name: "PR #385" })).toHaveLength(1)
    expect(screen.getByRole("tabpanel").querySelector("a[href*='/pull/385']")).toBeNull()
    const said = document.querySelector<HTMLElement>('[data-slot="ticket-result-changes"]')!
    expect(said.textContent).toContain("The mission and the result each have their tab.")
    expect(said.textContent).not.toContain("12 minutes")
    expect(screen.queryByText(/No result rendered/)).toBeNull()
  })

  test("a code ticket's pull request is above its tabs, once, with where it stands and the way to its diff", async () => {
    drawn(
      ticket({ column: "review", type: "Code", pull_request: "https://github.com/hermez/ponos/pull/385" }),
      Promise.resolve(done())
    )
    const diff = await screen.findByRole("link", { name: /View the diff/ })
    const card = diff.closest<HTMLElement>('[data-slot="ticket-delivery"]')!
    expect(card.compareDocumentPosition(screen.getByRole("tablist")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getAllByRole("link", { name: /View the diff/ })).toHaveLength(1)
    expect(within(card).getByRole("link", { name: "PR #385" })).toBeTruthy()
    expect(within(card).getByText("open, waiting for your review")).toBeTruthy()
    expect(within(card).getByRole("link", { name: /View the diff/ }).getAttribute("href")).toBe(
      "https://github.com/hermez/ponos/pull/385/files"
    )
  })
})

describe("the rail", () => {
  /** A screen wide enough for the rail: every media query asked holds. */
  function wide() {
    const before = window.matchMedia
    window.matchMedia = ((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as typeof window.matchMedia
    return () => {
      window.matchMedia = before
    }
  }

  test("on a wide screen, the status, the facts under their names and the pull request are a column beside the tabs", () => {
    const narrow = wide()
    try {
      drawn(
        ticket({
          column: "review",
          type: "Code",
          cost: 1.5,
          runner: "workstation",
          pull_request: "https://github.com/hermez/ponos/pull/385",
        })
      )
      const view = document.querySelector<HTMLElement>('[data-slot="ticket-view"]')!
      expect(view.getAttribute("data-layout")).toBe("rail")
      const rail = screen.getByRole("complementary", { name: "Status and details" })
      const status = rail.querySelector('[data-slot="ticket-status"]')!
      const summary = rail.querySelector<HTMLElement>('[data-slot="ticket-summary"]')!
      const delivery = rail.querySelector('[data-slot="ticket-delivery"]')!
      // The status first, then the facts, then the pull request: the rail's order, and the reading order.
      expect(status.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      expect(summary.compareDocumentPosition(delivery) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      expect(rail.compareDocumentPosition(screen.getByRole("tablist")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      expect(within(rail).queryByRole("tablist")).toBeNull()
      // Every fact under its name, the rare ones too, and no « Details » to press.
      expect(within(summary).getByText("workstation").closest("div")?.querySelector("dt")?.textContent).toBe("Taken by")
      expect(within(summary).getByText("$1.50").closest("div")?.querySelector("dt")?.className).not.toContain("sr-only")
      expect(within(summary).queryByRole("button", { name: "Details" })).toBeNull()
    } finally {
      narrow()
    }
  })

  test("its settings are changed in place: the priority, the model, the project of a ticket not yet run", () => {
    const narrow = wide()
    publishBoard({
      tickets: [],
      columns: [],
      priority: true,
      choices: { model: [{ value: "opus", label: "claude/opus" }] },
    })
    try {
      drawn(ticket({ column: "ready", project: "Opoil", project_id: "p1", priority: 70 }))
      const summary = document.querySelector<HTMLElement>('[data-slot="ticket-summary"]')!
      expect((within(summary).getByRole("spinbutton", { name: "Priority, from 0 to 100" }) as HTMLInputElement).value).toBe("70")
      expect(within(summary).getByRole("combobox", { name: "Change the model" })).toBeTruthy()
      expect(within(summary).getByRole("combobox", { name: "Change the project" }).textContent).toContain("Opoil")
      cleanup()
      // Over: said, and no longer changed.
      drawn(ticket({ column: "done", project: "Opoil", project_id: "p1", priority: 70 }))
      const over = document.querySelector<HTMLElement>('[data-slot="ticket-summary"]')!
      expect(within(over).queryByRole("spinbutton")).toBeNull()
      expect(within(over).queryByRole("combobox")).toBeNull()
      expect(within(over).getByText("Opoil")).toBeTruthy()
    } finally {
      publishBoard({ tickets: [], columns: [] })
      narrow()
    }
  })

  test("on a narrow screen, the same blocks are above the tabs, the facts folded", () => {
    drawn(ticket({ column: "review" }))
    expect(document.querySelector('[data-slot="ticket-view"]')?.getAttribute("data-layout")).toBe("column")
    expect(screen.queryByRole("complementary")).toBeNull()
    const summary = document.querySelector<HTMLElement>('[data-slot="ticket-summary"]')!
    expect(within(summary).getByRole("button", { name: "Details" })).toBeTruthy()
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
