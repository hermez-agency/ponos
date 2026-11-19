import { act, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, test, vi } from "vitest"

import { ConsolePane } from "./console-pane"

/* The conversation, drawn again: only the message that changed is.
 *
 * Every chunk of a streamed answer, every change of the console's state draws
 * the conversation again; a message already said must not be — with its Markdown,
 * a hundred of them were most of a keystroke. Each message is counted where it
 * is drawn (`ChatMessage`), with the voice ready, since the Listen callback
 * every answer is handed is what used to change at each render.
 *
 * Around it, only what it reads: the console's state, which a test changes to
 * draw the conversation again, and `useChat`'s messages. The bar and the
 * header's pickers are tested where they live.
 */

interface Message {
  id: string
  role: "user" | "assistant"
  parts: { type: "text"; content: string }[]
}

const world = vi.hoisted(() => ({
  state: {} as Record<string, unknown>,
  messages: [] as Message[],
  listeners: new Set<() => void>(),
  drawn: {} as Record<string, number>,
}))

function change(state: Record<string, unknown>, messages = world.messages) {
  act(() => {
    world.state = { ...world.state, ...state }
    world.messages = messages
    for (const listener of world.listeners) listener()
  })
}

vi.mock("@/hooks/use-console", async () => {
  const { useSyncExternalStore } = await import("react")
  const subscribe = (listener: () => void) => {
    world.listeners.add(listener)
    return () => world.listeners.delete(listener)
  }
  return { useConsole: () => useSyncExternalStore(subscribe, () => world.state) }
})

vi.mock("@tanstack/ai-react", () => ({
  useChat: () => ({ messages: world.messages, sendMessage: () => Promise.resolve() }),
}))

vi.mock("@/lib/agui", async (original) => ({
  ...(await original<typeof import("@/lib/agui")>()),
  connectionFor: () => ({}),
}))

vi.mock("@/components/chat/chat-message", () => ({
  ChatMessage: ({ message }: { message: Message }) => {
    world.drawn[message.id] = (world.drawn[message.id] ?? 0) + 1
    return <p>{message.parts.map((part) => part.content).join("")}</p>
  },
}))

vi.mock("./composer", () => ({ Composer: () => null }))
vi.mock("./model-picker", () => ({ ModelPicker: () => null }))
vi.mock("./talk-history", () => ({ TalkHistory: () => null }))

const text = (id: string, role: Message["role"], content: string): Message => ({
  id,
  role,
  parts: [{ type: "text", content }],
})

beforeEach(() => {
  world.drawn = {}
  world.listeners.clear()
  world.messages = [text("u1", "user", "Hello"), text("a1", "assistant", "Hi there")]
  world.state = {
    chat: { id: "c1", title: "", speech: { ready: true }, dictation: { ready: true } },
    transcript: [],
    busy: false,
    commanding: false,
    stopping: false,
    queue: [],
    held: false,
    limited: false,
    elsewhere: { running: 0 },
    runner: null,
    newChat: () => Promise.resolve(),
    reloadState: () => {},
    submit: () => Promise.resolve(true),
    stopChat: () => Promise.resolve(),
    say: () => {},
  }
})

describe("the conversation", () => {
  test("a message already drawn is not drawn again when the conversation is", () => {
    render(<ConsolePane />)
    expect(world.drawn).toEqual({ u1: 1, a1: 1 })

    // Another conversation started, then ended: this one is drawn again, its messages are not.
    change({ elsewhere: { running: 1 } })
    change({ elsewhere: { running: 0 } })
    expect(world.drawn).toEqual({ u1: 1, a1: 1 })
  })

  test("while an answer streams, only that answer is drawn again", () => {
    render(<ConsolePane />)
    const asked = [...world.messages, text("u2", "user", "And now?")]
    change({ busy: true }, [...asked, text("a2", "assistant", "Let")])
    const before = { ...world.drawn }

    for (const chunk of ["Let me", "Let me look", "Let me look at it."])
      change({}, [...asked, text("a2", "assistant", chunk)])

    expect(world.drawn).toEqual({ ...before, a2: before.a2! + 3 })
    expect(screen.getByText("Let me look at it.")).toBeTruthy()
  })

  test("a screen reader hears what is added, not each streamed word", () => {
    render(<ConsolePane />)
    const log = screen.getByRole("log")
    expect(log.getAttribute("aria-live")).toBe("polite")
    expect(log.getAttribute("aria-relevant")).toBe("additions")
  })
})
