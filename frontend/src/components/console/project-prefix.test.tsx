import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, test, vi } from "vitest"

import { PrefixCard } from "./project-settings"

/* The project's prefix is typed, saved in capitals, and left alone for
 * « Sans projet », whose prefix is the same for everybody. */

vi.mock("@/lib/api", () => ({ api: {}, why: (error: unknown) => String(error) }))

describe("PrefixCard", () => {
  test("saves what is typed, in capitals", async () => {
    const saved: string[] = []
    render(
      <PrefixCard
        prefix={{ value: "PON", fixed: false }}
        saving={false}
        onSave={(value) => {
          saved.push(value)
          return Promise.resolve()
        }}
      />
    )
    const save = screen.getByRole("button", { name: "Save" })
    expect((save as HTMLButtonElement).disabled).toBe(true)
    const input = screen.getByLabelText("Prefix")
    await userEvent.clear(input)
    await userEvent.type(input, "po")
    await userEvent.click(save)
    expect(saved).toEqual(["PO"])
  })

  test("cannot be changed for the tickets without a project", () => {
    render(<PrefixCard prefix={{ value: "T", fixed: true }} saving={false} onSave={() => Promise.resolve()} />)
    expect((screen.getByLabelText("Prefix") as HTMLInputElement).readOnly).toBe(true)
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true)
  })
})
