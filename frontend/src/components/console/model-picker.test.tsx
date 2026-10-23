import { render, screen } from "@testing-library/react"
import { describe, expect, test } from "vitest"

import type { ChatModels } from "@/lib/types"

import { ModelList } from "./model-picker"

/* jsdom lays nothing out, so what is checked is the structure that lets the
 * browser do it: the name has its own line and is never truncated, the slug and
 * the price sit under it, and the slug carries itself in full as a tooltip. */

const slug = "qwen/qwen3-vl-30b-a3b-thinking"
const models = {
  recent: [],
  claude: [],
  openrouter: {
    configured: true,
    error: null,
    models: [{ id: slug, name: "Qwen: Qwen3 VL 30B A3B Thinking", input: 0.29, output: 1, tools: true }],
  },
} as unknown as ChatModels

describe("a model of the list", () => {
  test("keeps its name whole, with the slug and the price under it", () => {
    render(<ModelList model="" models={models} reading={false} pick={() => {}} empty="Default" settingsTo="/" onSettings={() => {}} />)
    const name = screen.getByText("Qwen: Qwen3 VL 30B A3B Thinking")
    expect(name.className).not.toContain("truncate")
    const id = screen.getByText(slug)
    expect(id.getAttribute("title")).toBe(slug)
    expect(id.className).toContain("truncate")
    expect(name.parentElement).toBe(id.closest("[data-model-text]"))
    expect(screen.getByText("$0.29 / $1 per million tokens")).toBeTruthy()
  })
})
