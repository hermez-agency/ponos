import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, test, vi } from "vitest"

import { OnInputController } from "./new-ticket"

/* The « On » field of the new-ticket form: a box of several lines among the
 * advanced options, with its help line, that hands what is typed to the form. */

describe("the On field of the creation form", () => {
  test("says what it is for, and passes what is typed to the form", async () => {
    const onChange = vi.fn()
    const formInput = { id: "field-on", name: "on", label: "Automation (On)", value: "" }
    render(<OnInputController formInput={formInput as never} onChange={onChange} />)
    expect(screen.getByText(/A prompt Ponos runs at every change/)).toBeTruthy()
    await userEvent.type(screen.getByRole("textbox"), "x")
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ name: "on", value: "x" }))
  })

  test("shows the value the form holds, several lines of it", () => {
    const formInput = { id: "field-on", name: "on", label: "Automation (On)", value: "one\ntwo" }
    render(<OnInputController formInput={formInput as never} onChange={() => undefined} />)
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("one\ntwo")
  })
})
