import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, test, vi } from "vitest"

import type { Step } from "@/lib/types"

import { SessionLog, withoutProtocol } from "./session-log"
import { StepForks, type Forks } from "./ticket-live"

/* What a session's last message shows: its words, not the lines the runner reads. */
describe("withoutProtocol", () => {
  test("drops the end-of-session lines and keeps the prose", () => {
    const said = [
      "J'ai terminé la boîte mail.",
      "",
      "DONE: boîte créée",
      "WHY: identifiants manquants",
      "CATEGORY: access",
      "QUESTION: Peux-tu fournir le jeton ?",
      "MODE: free",
      "CODE: access.credentials",
      "RESULT: blocked — il manque le jeton",
    ].join("\n")
    expect(withoutProtocol(said)).toBe("J'ai terminé la boîte mail.")
  })

  test("leaves a sentence that merely mentions a keyword", () => {
    expect(withoutProtocol("Le RESULT: de la CI est vert.")).toBe("Le RESULT: de la CI est vert.")
  })

  test("a message of protocol alone becomes empty", () => {
    expect(withoutProtocol("RESULT: ok — fait")).toBe("")
  })
})

/* « Start again from here »: offered on the steps a session can be cut at, and
 * the runs that branched from a step marked on it. */
describe("SessionLog forks", () => {
  const steps: Step[] = [
    { position: 1, label: "I look first.", detail: "", said: true, forkable: true },
    { position: 2, label: "Bash", detail: "ls", forkable: true },
    { position: 3, label: "Read", detail: "a subagent's", forkable: false },
  ]

  test("asks for the step clicked, and only where a session can start", async () => {
    const ask = vi.fn()
    const forks: Forks = { ask, branches: new Map([[2, [3]]]) }
    render(<SessionLog steps={steps} live={false} aside={(step) => <StepForks step={step} forks={forks} />} />)
    await userEvent.click(screen.getByRole("button", { name: /Show the steps/ }))
    const buttons = screen.getAllByRole("button", { name: "Start again from here" })
    expect(buttons).toHaveLength(2)
    await userEvent.click(buttons[1])
    expect(ask).toHaveBeenCalledWith(steps[1])
    expect(screen.getByTitle("Started again from here").textContent).toBe("#3")
  })

  test("offers nothing where nobody can start again", () => {
    const forks: Forks = { branches: new Map() }
    render(<SessionLog steps={steps} live={false} aside={(step) => <StepForks step={step} forks={forks} />} />)
    expect(screen.queryByRole("button", { name: "Start again from here" })).toBeNull()
  })
})
