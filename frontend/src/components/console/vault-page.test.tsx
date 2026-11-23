import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { ApiError } from "@/lib/api"
import type { Vault } from "@/lib/types"

import { New, normalized } from "./vault-page"

/* « New entry » of the vault: what is wrong is said under its field once the
 * typing pauses, gone as soon as it is right, and the server's refusals land
 * under the field they are about. The values are never held by the form. */

const world = vi.hoisted(() => ({
  sent: [] as Record<string, unknown>[],
  answers: [] as (() => Promise<unknown>)[],
}))

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: {
    createVaultEntry: (body: Record<string, unknown>) => {
      world.sent.push(body)
      return world.answers.shift()?.() ?? Promise.reject(new Error("nothing answers"))
    },
  },
}))

const vault = {
  entries: [{ id: "1", name: "DOKPLOY", kind: "login", variables: ["DOKPLOY_USER", "DOKPLOY_PASSWORD"] }],
  projects: ["Leadz", "Ponos"],
  reserved: ["ANTHROPIC_API_KEY"],
  key: { source: "file", where: "vault.key" },
  proven: true,
  relocks_after: 900,
} as unknown as Vault

const field = (name: string) => document.querySelector(`[data-field="${name}"]`) as HTMLElement
const typing = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) })
const pause = (ms: number) => act(() => vi.advanceTimersByTime(ms))

beforeEach(() => {
  world.sent = []
  world.answers = []
  // The pauses only: React schedules its own work with setImmediate, which must still run.
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] })
  // The Testing Library waits for a timer of its own after each gesture, and
  // only moves fake ones on when it finds `jest`: lent Vitest's under that name.
  vi.stubGlobal("jest", { advanceTimersByTime: (ms: number) => vi.advanceTimersByTime(ms) })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const draw = () => render(<New vault={vault} guard={(send) => send()} onMade={() => {}} />)

describe("New entry", () => {
  test("says a password is too short after a pause in the typing, and no more once it is long enough", async () => {
    const user = typing()
    draw()
    await user.selectOptions(screen.getByRole("combobox"), "login")
    await user.type(field("password").querySelector("input")!, "abc")
    await pause(900)
    expect(within(field("password")).queryByRole("alert")).toBeNull()
    await pause(100)
    expect(within(field("password")).getByRole("alert").textContent).toMatch(/^The password needs at least 6 characters/)
    // A user is no secret: `admin` is no problem, whatever its length.
    await user.type(field("user").querySelector("input")!, "admin")
    await pause(1000)
    expect(within(field("user")).queryByRole("alert")).toBeNull()
    // Right again, and said at once: no pause to wait for.
    await user.type(field("password").querySelector("input")!, "def")
    expect(within(field("password")).queryByRole("alert")).toBeNull()
  })

  test("corrects a name rather than refusing it, and refuses one already given or the runner's own", async () => {
    const user = typing()
    draw()
    const name = field("name").querySelector("input")!
    await user.type(name, "umami login")
    await pause(1000)
    expect(within(field("name")).queryByRole("alert")).toBeNull()
    expect(field("name").querySelector('[data-slot="vault-variables"]')?.textContent).toBe("UMAMI_LOGIN")
    await user.clear(name)
    await user.type(name, "dokploy-user")
    await pause(1000)
    expect(within(field("name")).getByRole("alert").textContent).toBe(
      "This name is already given by the entry DOKPLOY: choose another one."
    )
    await user.clear(name)
    await user.type(name, "anthropic api key")
    await pause(1000)
    expect(within(field("name")).getByRole("alert").textContent).toBe(
      "ANTHROPIC_API_KEY is Ponos's own and never given to a project: choose another name."
    )
    await user.clear(name)
    await user.type(name, "umami")
    expect(within(field("name")).queryByRole("alert")).toBeNull()
  })

  test("draws a refusal of the server under its field, and keeps what was typed", async () => {
    const user = typing()
    world.answers.push(() =>
      Promise.reject(
        new ApiError("This name is already given by the entry UMAMI: choose another one.", 400, [
          { propertyPath: "name", message: "This name is already given by the entry UMAMI: choose another one." },
        ])
      )
    )
    draw()
    await user.type(field("name").querySelector("input")!, "UMAMI_TOKEN")
    const value = field("value").querySelector("input")!
    await user.type(value, "a-real-token-0123")
    await user.click(screen.getByRole("button", { name: "Keep in the vault" }))
    await waitFor(() =>
      expect(within(field("name")).getByRole("alert").textContent).toBe(
        "This name is already given by the entry UMAMI: choose another one."
      )
    )
    expect(value.value).toBe("a-real-token-0123")
    // Edited, and the server's sentence is gone with what it was about.
    await user.type(field("name").querySelector("input")!, "2")
    expect(within(field("name")).queryByRole("alert")).toBeNull()
  })

  test("keeps the Umami login at the first try: UMAMI, admin and a real password", async () => {
    const user = typing()
    world.answers.push(() =>
      Promise.resolve({ name: "UMAMI", variables: ["UMAMI_USER", "UMAMI_PASSWORD"], url_variable: "UMAMI_URL" })
    )
    draw()
    await user.selectOptions(screen.getByRole("combobox"), "login")
    await user.type(field("name").querySelector("input")!, "UMAMI")
    await user.type(field("user").querySelector("input")!, "admin")
    await user.type(field("password").querySelector("input")!, "correct horse battery")
    await user.type(field("url").querySelector("input")!, "umami.example.com")
    expect(field("name").querySelector('[data-slot="vault-variables"]')?.textContent).toBe(
      "UMAMI_USER, UMAMI_PASSWORD, UMAMI_URL"
    )
    await user.click(screen.getByRole("button", { name: "Keep in the vault" }))
    await waitFor(() => expect(world.sent).toHaveLength(1))
    expect(world.sent[0]).toMatchObject({
      name: "UMAMI",
      kind: "login",
      user: "admin",
      password: "correct horse battery",
      url: "umami.example.com",
    })
    // Sent, then gone from the page: nothing keeps it.
    await waitFor(() => expect(field("password").querySelector("input")!.value).toBe(""))
    expect(field("user").querySelector("input")!.value).toBe("")
    expect(document.querySelectorAll('[role="alert"]')).toHaveLength(0)
  })
})

test("a name is made a variable as the server makes it", () => {
  expect(normalized("umami login")).toBe("UMAMI_LOGIN")
  expect(normalized("Umämi-prod")).toBe("UMAMI_PROD")
  expect(normalized("  api.key -- v2  ")).toBe("API_KEY_V2")
  expect(normalized("2fa")).toBe("_2FA")
  expect(normalized("---")).toBe("")
})
