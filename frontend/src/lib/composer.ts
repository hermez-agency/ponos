/* What the message bar decides, without a DOM to decide it in.
 *
 * Which file it takes, what a pasted screenshot is called, whether there is
 * anything to send, which command a half-typed `>st` is heading for: all of it
 * is plain data in, plain data out, so that `node --test` can hold it to what
 * it says without a browser — the console has no test runner of its own, and
 * this file imports nothing so that it needs none.
 *
 * The list of accepted kinds is the server's (`web/attachments.py`), said twice
 * on purpose: the page refuses early, with a sentence, and the server refuses
 * anyway, because the page is not what decides what lands on the disk.
 */

export type Kind = "image" | "video" | "document"

export const ACCEPTED: Record<string, Kind> = {
  png: "image",
  jpg: "image",
  jpeg: "image",
  webp: "image",
  gif: "image",
  mp4: "video",
  webm: "video",
  mov: "video",
  pdf: "document",
  txt: "document",
  md: "document",
  csv: "document",
  json: "document",
  docx: "document",
  xlsx: "document",
}

/** What the file picker is told to offer. */
export const ACCEPT_ATTRIBUTE = Object.keys(ACCEPTED)
  .map((extension) => `.${extension}`)
  .join(",")

/* A file without an extension worth reading — a pasted screenshot, a blob — is
 * named by its type instead. */
const BY_TYPE: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
  "video/mp4": "mp4",
  "video/webm": "webm",
  "video/quicktime": "mov",
  "application/pdf": "pdf",
}

/** The little a bar needs to know about a file: `File` has it, and so does a test. */
export interface FileLike {
  name: string
  type: string
  size: number
}

/** A file on its way into a message: uploading, kept, or refused on the way. */
export interface Pending {
  key: string
  name: string
  kind: Kind
  size: number
  state: "uploading" | "done" | "error"
  /** The server's id, once it has kept the file. */
  id?: string
  /** An object URL to draw the thumbnail from, for images and videos. */
  preview?: string
  error?: string
}

export interface Refusal {
  name: string
  why: "type" | "size"
}

export const extensionOf = (name: string) =>
  name.includes(".") ? name.slice(name.lastIndexOf(".") + 1).toLowerCase() : ""

export function kindOf(file: Pick<FileLike, "name" | "type">): Kind | null {
  return ACCEPTED[extensionOf(file.name)] ?? ACCEPTED[BY_TYPE[file.type] ?? ""] ?? null
}

/* What a file is called in the message. A screenshot pasted from the clipboard
 * arrives as `image.png` — every one of them — which reads as nothing in a
 * transcript of three; it is named after the moment it was pasted instead. */
export function nameFor(file: Pick<FileLike, "name" | "type">, pasted = false, now = new Date()): string {
  const extension = ACCEPTED[extensionOf(file.name)] ? extensionOf(file.name) : BY_TYPE[file.type]
  const generic = !file.name || /^image\.(png|jpe?g|gif|webp)$/i.test(file.name)
  if (!pasted && !generic && ACCEPTED[extensionOf(file.name)]) return file.name
  if (!pasted && file.name && !generic) return `${file.name}.${extension ?? "bin"}`
  const stamp = [now.getHours(), now.getMinutes(), now.getSeconds()]
    .map((part) => String(part).padStart(2, "0"))
    .join("")
  return `${pasted ? "screenshot" : "file"}-${stamp}.${extension ?? "png"}`
}

/** Sorts what was dropped into what the bar takes and what it says no to. */
export function screen<T extends FileLike>(
  files: readonly T[],
  limitMb: number
): { taken: T[]; refused: Refusal[] } {
  const taken: T[] = []
  const refused: Refusal[] = []
  for (const file of files) {
    if (!kindOf(file)) refused.push({ name: file.name || file.type, why: "type" })
    else if (file.size > limitMb * 1024 * 1024) refused.push({ name: file.name, why: "size" })
    else taken.push(file)
  }
  return { taken, refused }
}

/** The files a paste carries — a screenshot, a copied file — and nothing else. */
export function pastedFiles<T>(data: { files?: ArrayLike<T> | null } | null): T[] {
  return data?.files ? Array.from(data.files) : []
}

export const withAdded = (list: Pending[], added: Pending[]) => [...list, ...added]

export const without = (list: Pending[], key: string) => list.filter((item) => item.key !== key)

export const settled = (list: Pending[], key: string, change: Partial<Pending>) =>
  list.map((item) => (item.key === key ? { ...item, ...change } : item))

/* A sentence talks to your workspace; a line that starts with `>` runs a
 * ponos command. */
export const isCommand = (text: string) => text.trimStart().startsWith(">")

/* Whether the arrow would send anything — and it is drawn disabled when not.
 * A sentence can be sent while Ponos answers: it waits its turn. A command
 * cannot: it runs at once, and one command at a time. */
export function canSend({
  text,
  attachments,
  busy,
  sending = false,
}: {
  text: string
  attachments: Pending[]
  busy: boolean
  sending?: boolean
}): boolean {
  if (sending) return false
  if (isCommand(text)) return !busy && text.trim().replace(/^>\s*/, "").length > 0
  if (attachments.some((item) => item.state === "uploading")) return false
  return text.trim().length > 0 || attachments.some((item) => item.state === "done")
}

/* Escape stops the turn in flight — but only from an empty field. With words
 * in it, Escape is a key somebody pressed while writing the next message, and
 * a stop nobody meant cannot be taken back. */
export function stopsOnEscape({
  text,
  attachments,
  busy,
  stoppable,
}: {
  text: string
  attachments: Pending[]
  busy: boolean
  stoppable: boolean
}): boolean {
  return busy && stoppable && !text.trim() && !attachments.length
}

/* The verb being typed after `>`, while it is still the only word: past the
 * first space the menu has nothing left to offer. */
export function typedVerb(text: string): string | null {
  const match = /^\s*>\s*(\S*)$/.exec(text)
  return match ? match[1] : null
}

export function completions(text: string, commands: readonly string[]): string[] {
  const verb = typedVerb(text)
  if (verb === null) return []
  const offered = commands.filter((command) => command.startsWith(verb.toLowerCase()))
  // Typed out in full, there is nothing to complete.
  return offered.length === 1 && offered[0] === verb ? [] : offered
}

export const completed = (verb: string) => `>${verb} `

export function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(/\.0$/, "")} MB`
}

/** A recording's length as a clock: `0:07`, `1:32`. */
export function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`
}

/** Where a transcription goes: after what is already typed, a space between. */
export function inserted(text: string, transcription: string): string {
  const said = transcription.trim()
  if (!said) return text
  if (!text.trim()) return said
  return `${text.replace(/\s+$/, "")} ${said}`
}
