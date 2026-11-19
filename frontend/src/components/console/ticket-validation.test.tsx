import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { TicketValidation } from "./ticket-validation"

vi.mock("@/lib/role", () => ({ canAct: () => true }))
vi.mock("@/lib/api", () => ({ api: { setValidation: vi.fn() }, why: String }))

const ticket = (validation: string, inherited: string, column = "ready") =>
  ({ id: "a".repeat(32), column, validation, validation_inherited: inherited }) as never

afterEach(cleanup)

describe("the ticket's Force validated", () => {
  it("says what an inherited ticket gets, and from whom", () => {
    render(<TicketValidation ticket={ticket("", "project")} />)
    expect(screen.getByText(/the project's setting/)).toBeTruthy()
    expect(screen.getByRole("button", { name: "Inherited" }).getAttribute("aria-pressed")).toBe("true")
  })

  it("says the ticket's own word over what it would inherit", () => {
    render(<TicketValidation ticket={ticket("free", "global")} />)
    expect(screen.getByText(/Waits for the review — the ticket's setting/)).toBeTruthy()
  })

  it("is read only once the ticket is done", () => {
    render(<TicketValidation ticket={ticket("", "", "done")} />)
    expect(screen.getByRole("button", { name: "Forced" }).hasAttribute("disabled")).toBe(true)
  })
})
