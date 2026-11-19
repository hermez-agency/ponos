import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { toast } from "sonner"
import { afterAll, beforeAll, beforeEach, describe, expect, test, vi } from "vitest"

import type { Attached } from "@/lib/types"

import { Composer } from "./composer"

/* The message bar, drawn: what `lib/composer.test.ts` decides, seen where it
 * shows — the arrow that lights up, the file refused with a sentence, the
 * screenshot pasted, the `>` that offers the commands.
 *
 * The toasts are watched rather than drawn: what is checked is the sentence
 * the bar hands them, in English, which is its key.
 *
 * The bar is drawn as in Chrome, which sizes the field itself
 * (`field-sizing: content`); jsdom is told so before the bar is imported,
 * since it asks once. The browsers that do not are drawn at the end.
 */

const sizing = vi.hoisted(() => {
  const state = { itself: true }
  vi.spyOn(CSS, "supports").mockImplementation(
    (property: string, value?: string) => property === "field-sizing" && value === "content" && state.itself
  )
  return state
})

vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), message: vi.fn(), success: vi.fn() }) }))

const PLACEHOLDER = "Write to your workspace"

function draw(props: Partial<React.ComponentProps<typeof Composer>> = {}) {
  const onSend = props.onSend ?? vi.fn(async () => true)
  const upload = vi.fn(
    async (_file: File, name: string): Promise<Attached> =>
      ({ id: `id-${name}`, name, kind: "image", size: 4 }) as Attached
  )
  render(<Composer busy={false} placeholder={PLACEHOLDER} upload={upload} {...props} onSend={onSend} />)
  return {
    onSend,
    upload,
    field: screen.getByRole("textbox", { name: PLACEHOLDER }) as HTMLTextAreaElement,
    arrow: () => screen.getByRole("button", { name: "Send" }) as HTMLButtonElement,
  }
}

const file = (name: string, type = "", size = 4) => new File([new Uint8Array(size)], name, { type })

beforeEach(() => vi.clearAllMocks())

describe("the send button", () => {
  test("is off on an empty bar, on once something is written, and sends it on Enter", async () => {
    const user = userEvent.setup()
    const { field, arrow, onSend } = draw()
    expect(arrow().disabled).toBe(true)

    await user.type(field, "   ")
    expect(arrow().disabled).toBe(true)

    await user.clear(field)
    await user.type(field, "Hello{Enter}")
    expect(onSend).toHaveBeenCalledWith("Hello", [])
    await waitFor(() => expect(field.value).toBe(""))
    expect(arrow().disabled).toBe(true)
  })

  test("keeps the words when the message was not taken", async () => {
    const user = userEvent.setup()
    const { field, arrow, onSend } = draw({ onSend: vi.fn(async () => false) })
    await user.type(field, "Hello")
    await user.click(arrow())
    expect(onSend).toHaveBeenCalledOnce()
    expect(field.value).toBe("Hello")
  })

  test("takes a sentence while Ponos answers, and says it will wait; a command runs at once, one at a time", async () => {
    const user = userEvent.setup()
    const { field, arrow } = draw({ busy: true, commands: ["status"] })
    await user.type(field, "Hello")
    expect(arrow().disabled).toBe(false)
    expect(arrow().title).toBe("Send — it waits for Ponos to finish")

    await user.clear(field)
    await user.type(field, ">status ")
    expect(arrow().disabled).toBe(false)
  })

  test("holds a second command while one is running", async () => {
    const user = userEvent.setup()
    const { field, arrow } = draw({ busy: true, commanding: true, commands: ["status"] })
    await user.type(field, ">status ")
    expect(arrow().disabled).toBe(true)
  })

  test("is joined by Stop while there is something to stop", async () => {
    const user = userEvent.setup()
    const onStop = vi.fn()
    draw({ busy: true, onStop })
    await user.click(screen.getByRole("button", { name: "Stop" }))
    expect(onStop).toHaveBeenCalledOnce()
  })
})

describe("files", () => {
  test("a file of a kind the workspace cannot take is refused, with why, and never uploaded", async () => {
    const user = userEvent.setup({ applyAccept: false })
    const { upload } = draw()
    const picker = document.querySelector<HTMLInputElement>('input[type="file"]')!
    await user.upload(picker, [file("setup.exe")])

    expect(upload).not.toHaveBeenCalled()
    expect(toast.error).toHaveBeenCalledWith(
      "“setup.exe” is not a file the workspace can take",
      expect.objectContaining({
        description: expect.stringContaining("Images (png, jpg, webp, gif)"),
      })
    )
  })

  test("a file over the limit is refused, and the limit named", async () => {
    const user = userEvent.setup()
    const { upload } = draw({ limitMb: 1 })
    const picker = document.querySelector<HTMLInputElement>('input[type="file"]')!
    await user.upload(picker, [file("big.png", "image/png", 2 * 1024 * 1024)])

    expect(upload).not.toHaveBeenCalled()
    expect(toast.error).toHaveBeenCalledWith(
      "“big.png” is over 1 MB",
      expect.objectContaining({ description: "The limit is web.attachment_max_mb, in the settings." })
    )
  })

  test("a file taken is uploaded at once, and sent with the message", async () => {
    const user = userEvent.setup()
    const { field, arrow, upload, onSend } = draw()
    await user.upload(document.querySelector<HTMLInputElement>('input[type="file"]')!, [file("photo.png", "image/png")])

    expect(upload).toHaveBeenCalledOnce()
    // A file alone is a message: the arrow lights up once it is kept.
    await waitFor(() => expect(arrow().disabled).toBe(false))
    await user.type(field, "Look{Enter}")
    expect(onSend).toHaveBeenCalledWith("Look", [expect.objectContaining({ id: "id-photo.png" })])
  })

  test("a screenshot pasted is attached under a name of its own, and its text not pasted", async () => {
    const { field, upload } = draw()
    const pasted = fireEvent.paste(field, { clipboardData: { files: [file("image.png", "image/png")] } })

    expect(pasted).toBe(false)
    expect(upload).toHaveBeenCalledOnce()
    const [, name] = upload.mock.calls[0]
    expect(name).not.toBe("image.png")
    expect(name).toMatch(/\.png$/)
    expect(field.value).toBe("")
  })

  test("a bar given nothing to upload with has no + and lets a paste through", () => {
    const { field } = draw({ upload: undefined })
    expect(screen.queryByRole("button", { name: "Attach a file" })).toBeNull()
    expect(fireEvent.paste(field, { clipboardData: { files: [file("image.png", "image/png")] } })).toBe(true)
  })
})

describe("the > commands", () => {
  const commands = ["status", "start", "stop", "doctor"]

  test("a > offers the commands it may be heading for, and narrows as it is typed", async () => {
    const user = userEvent.setup()
    const { field } = draw({ commands })
    await user.type(field, ">")
    const menu = screen.getByRole("listbox", { name: "Commands" })
    expect(Array.from(menu.querySelectorAll('[role="option"]'), (option) => option.textContent)).toEqual([
      ">status",
      ">start",
      ">stop",
      ">doctor",
    ])

    await user.type(field, "st")
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([">status", ">start", ">stop"])
    // The bar says it is a command now, and not a sentence.
    expect(screen.getByText("command")).toBeTruthy()
  })

  test("the arrows walk the list, Tab writes the one chosen, Escape closes it", async () => {
    const user = userEvent.setup()
    const { field } = draw({ commands })
    await user.type(field, ">st")
    expect(screen.getAllByRole("option")[0].getAttribute("aria-selected")).toBe("true")
    await user.keyboard("{ArrowDown}")
    expect(screen.getAllByRole("option")[1].getAttribute("aria-selected")).toBe("true")
    await user.keyboard("{Tab}")
    expect(field.value).toBe(">start ")
    expect(screen.queryByRole("listbox")).toBeNull()

    await user.clear(field)
    await user.type(field, ">d")
    expect(screen.getByRole("listbox")).toBeTruthy()
    await user.keyboard("{Escape}")
    expect(screen.queryByRole("listbox")).toBeNull()
  })

  test("Enter on an open list completes rather than sends, and a click does too", async () => {
    const user = userEvent.setup()
    const { field, onSend } = draw({ commands })
    await user.type(field, ">sto{Enter}")
    expect(field.value).toBe(">stop ")
    expect(onSend).not.toHaveBeenCalled()

    await user.clear(field)
    await user.type(field, ">")
    await user.click(screen.getByRole("option", { name: ">doctor" }))
    expect(field.value).toBe(">doctor ")
  })

  test("a bar given no commands takes a > as a sentence", async () => {
    const user = userEvent.setup()
    const { field } = draw()
    await user.type(field, ">st")
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(screen.queryByText("command")).toBeNull()
  })
})

/* jsdom lays nothing out: the field is given the geometry of a browser's, a
 * line of 24 px for each line written (forty letters to one) and as tall as
 * its height says, or one line — and every look at what overflows it counted,
 * with the height it was taken at. */
const LINE = 24
const read: string[] = []
const lineCount = (text: string) =>
  text.split("\n").reduce((rows, line) => rows + Math.max(1, Math.ceil(line.length / 40)), 0)
const tall = (field: HTMLTextAreaElement) => parseInt(field.style.height) || LINE

beforeAll(() => {
  Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", {
    configurable: true,
    get(this: HTMLTextAreaElement) {
      read.push(this.style.height)
      return Math.max(lineCount(this.value) * LINE, tall(this))
    },
  })
  Object.defineProperty(HTMLTextAreaElement.prototype, "clientHeight", {
    configurable: true,
    get(this: HTMLTextAreaElement) {
      return tall(this)
    },
  })
})
afterAll(() => {
  delete (HTMLTextAreaElement.prototype as { scrollHeight?: number }).scrollHeight
  delete (HTMLTextAreaElement.prototype as { clientHeight?: number }).clientHeight
})
beforeEach(() => {
  read.length = 0
})

const NEWLINE = "{Shift>}{Enter}{/Shift}"

describe("the field, where the browser sizes it", () => {
  test("is never measured: it grows by its own CSS, as tall as eight lines", async () => {
    const user = userEvent.setup()
    const { field } = draw()
    expect(field.className).toContain("field-sizing-content")
    expect(field.className).toContain("max-h-[200px]")

    await user.type(field, `one${NEWLINE}two${NEWLINE}three`)
    expect(field.value).toBe("one\ntwo\nthree")
    expect(read).toEqual([])
    expect(field.style.height).toBe("")
  })
})

describe("the field, where the browser does not size it", () => {
  let Measured: typeof Composer

  beforeAll(async () => {
    sizing.itself = false
    vi.resetModules()
    ;({ Composer: Measured } = await import("./composer"))
  })
  afterAll(() => {
    sizing.itself = true
  })

  const drawMeasured = () => {
    const onSend = vi.fn(async () => true)
    render(<Measured busy={false} placeholder={PLACEHOLDER} onSend={onSend} />)
    return screen.getByRole("textbox", { name: PLACEHOLDER }) as HTMLTextAreaElement
  }

  test("grows a line at a time, never collapsed to measure a longer text", async () => {
    const user = userEvent.setup()
    const field = drawMeasured()
    await user.type(field, "one")
    expect(field.style.height).toBe("")

    await user.type(field, `${NEWLINE}two`)
    expect(field.style.height).toBe("48px")
    await user.type(field, `${NEWLINE}three`)
    expect(field.style.height).toBe("72px")
    // A long line wraps, and the field grows with it.
    await user.type(field, ` ${"x".repeat(40)}`)
    expect(field.style.height).toBe("96px")
    expect(read).not.toContain("auto")
  })

  test("stops at about eight lines, then scrolls", async () => {
    const user = userEvent.setup()
    const field = drawMeasured()
    await user.type(field, Array.from({ length: 12 }, (_, line) => `line ${line}`).join(NEWLINE))
    expect(field.style.height).toBe("200px")
    read.length = 0
    await user.type(field, `${NEWLINE}more`)
    expect(read).toEqual([])
    expect(field.style.height).toBe("200px")
  })

  test("shrinks when lines go, and a one-line field is not measured as it is emptied", async () => {
    const user = userEvent.setup()
    const field = drawMeasured()
    await user.type(field, `one${NEWLINE}two`)
    expect(field.style.height).toBe("48px")
    await user.type(field, "{Backspace}{Backspace}{Backspace}{Backspace}")
    expect(field.value).toBe("one")
    expect(field.style.height).toBe("")

    read.length = 0
    await user.type(field, "{Backspace}{Backspace}")
    expect(read).toEqual([])
  })

  test("is one line again once the message is sent", async () => {
    const user = userEvent.setup()
    const field = drawMeasured()
    await user.type(field, `one${NEWLINE}two${NEWLINE}three`)
    expect(field.style.height).toBe("72px")
    await user.type(field, "{Enter}")
    await waitFor(() => expect(field.value).toBe(""))
    expect(field.style.height).toBe("")
  })
})
