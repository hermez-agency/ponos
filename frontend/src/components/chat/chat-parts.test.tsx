import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, test } from "vitest"

import { ChatMessage } from "./chat-message"
import type { ChatMessageData, ToolCallPart, ToolResultPart } from "./chat-types"
import { ToolCallPartView } from "./chat-parts"

/* A step of the chat: one folded line for a call and its result together, its
 * title in plain words, the technical name only once it is opened. */

function call(
  name: string,
  args: object,
  state: ToolCallPart["state"] = "input-complete"
): ToolCallPart {
  return {
    type: "tool-call",
    id: "c1",
    name,
    arguments: JSON.stringify(args),
    state,
  }
}

const answered: ToolResultPart = {
  type: "tool-result",
  toolCallId: "c1",
  content: "ok",
  state: "complete",
}

describe("a step", () => {
  test("is closed by default, with a plain title and no technical name", () => {
    render(<ToolCallPartView part={call("Read", { file_path: "a.py" })} result={answered} />)
    const toggle = screen.getByRole("button", { name: /Reads a file/ })
    expect(toggle.getAttribute("aria-expanded")).toBe("false")
    expect(screen.queryByText("Read")).toBeNull()
    expect(screen.queryByText(/file_path/)).toBeNull()
  })

  test("shows the arguments then the result once opened, in one item", async () => {
    render(<ToolCallPartView part={call("Read", { file_path: "a.py" })} result={answered} />)
    await userEvent.click(screen.getByRole("button", { name: /Reads a file/ }))
    expect(screen.getByText("Read")).toBeTruthy()
    expect(screen.getByLabelText("Arguments of Read").textContent).toContain("a.py")
    expect(screen.getByLabelText("Result of Read").textContent).toContain("ok")
  })

  test("an unknown tool has a generic title, its name only once opened", async () => {
    render(<ToolCallPartView part={call("mcp__acme__frobnicate", {})} />)
    expect(screen.getByRole("button", { name: /Uses a tool/ })).toBeTruthy()
    expect(screen.queryByText("mcp__acme__frobnicate")).toBeNull()
    await userEvent.click(screen.getByRole("button"))
    expect(screen.getByText("mcp__acme__frobnicate")).toBeTruthy()
  })

  test("titles a browser tool, a ponos command and a plain command", () => {
    const { rerender } = render(
      <ToolCallPartView part={call("mcp__claude-in-chrome__javascript_tool", {})} />
    )
    expect(screen.getByText("Looks in the browser")).toBeTruthy()
    rerender(<ToolCallPartView part={call("Bash", { command: "ponos tickets list" })} />)
    expect(screen.getByText("Looks in the tickets")).toBeTruthy()
    rerender(
      <ToolCallPartView part={call("Bash", { command: "ls", description: "Lists the folder" })} />
    )
    expect(screen.getByText("Looks at the disk")).toBeTruthy()
    expect(screen.getByText("Lists the folder")).toBeTruthy()
  })

  test("a failed step stays closed, with its failed badge", () => {
    const failed: ToolResultPart = {
      ...answered,
      state: "error",
      error: "boom",
    }
    render(<ToolCallPartView part={call("Bash", { command: "false" }, "error")} result={failed} />)
    expect(screen.getByRole("button", { expanded: false })).toBeTruthy()
    expect(screen.getByText("Failed")).toBeTruthy()
    expect(screen.queryByText("boom")).toBeNull()
  })

  test("a call and its result in a message make one step", () => {
    const message: ChatMessageData = {
      id: "m",
      role: "assistant",
      parts: [call("Grep", { pattern: "x" }), answered],
    }
    const { container } = render(<ChatMessage message={message} />)
    expect(container.querySelectorAll("[data-slot=chat-tool-call]")).toHaveLength(1)
    expect(container.querySelectorAll("[data-slot=chat-tool-result]")).toHaveLength(0)
    expect(screen.getByText("Searches the code")).toBeTruthy()
  })
})
