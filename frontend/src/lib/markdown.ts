/* Markdown, read rather than shown — what `components/console/markdown.tsx`
 * draws, decided without a DOM.
 *
 * It is not a markdown engine: it knows the shapes a ticket body holds as
 * typed Markdown, those its imported pages kept, and the few more a session
 * reaches for — a nested list, a table, a word behind a link, an emphasis — and
 * nothing else. It returns plain data, never markup: the page hands every
 * string to React, which escapes it.
 *
 * It lives here, importing nothing, so that `node --test` can hold it to what
 * it says; three shapes came out as their own source before it could — a
 * numbered list read « 1. 1. 1. », a table its pipes, a bold holding a bit of
 * code its asterisks.
 */

// A language may have spaces in its name ("plain text"), so everything after
// the fence is the language.
const FENCE = /^```(.*)$/

export type Align = "left" | "center" | "right" | null

export type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "item"; text: string; marker: string; depth: number; done?: boolean }
  | { kind: "quote"; text: string }
  | { kind: "code"; language: string; lines: string[] }
  | { kind: "table"; head: string[]; align: Align[]; rows: string[][] }
  | { kind: "rule" }
  | { kind: "paragraph"; text: string }
  | { kind: "attached"; file: string; label: string; block: string }

/** How deep a list item sits: two spaces is a level, a tab is a level. */
function depth(line: string): number {
  const indent = /^[\t ]*/.exec(line)?.[0] ?? ""
  return Math.min(3, indent.replace(/\t/g, "  ").length >> 1)
}

/* An image, a file or a PDF a page carried when it was imported, as its line
 * names it: « [image attached to the ticket: capture.png (… block <id>)] ».
 *
 * The line carries no address but the block holding the file, which
 * `/api/files/<block>` serves from the files kept beside `ponos.db`. The word
 * before « block » names where the page came from, and is not read. */
const ATTACHED =
  /^\[(image|file|pdf) attached to the ticket(?:: (.*))? \((?:\S+ )?block ([0-9a-f]{32})\)\]$/

/** A table row's cells: split on the pipes not written `\|`, the outer ones dropped. */
function cells(line: string): string[] {
  let row = line.trim()
  if (row.startsWith("|")) row = row.slice(1)
  if (row.endsWith("|") && !row.endsWith("\\|")) row = row.slice(0, -1)
  return row.split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, "|"))
}

/** The line under a table's head — `|---|:--:|` — read as each column's alignment. */
function alignments(line: string): Align[] | null {
  if (!line.includes("-") || !/^[\s|:-]+$/.test(line)) return null
  const columns = cells(line)
  if (!columns.every((cell) => /^:?-+:?$/.test(cell))) return null
  return columns.map((cell) =>
    cell.startsWith(":") && cell.endsWith(":")
      ? "center"
      : cell.endsWith(":")
        ? "right"
        : cell.startsWith(":")
          ? "left"
          : null
  )
}

export function blocks(text: string): Block[] {
  const out: Block[] = []
  const lines = text.replace(/\r\n/g, "\n").split("\n")
  let index = 0
  // Whether a blank line has been read since the last paragraph, which is the
  // only thing that ends one. See the foot of the loop, where they are pushed;
  // everything else pushes a block of another kind, and a paragraph never
  // continues across one of those.
  let ended = true
  /* The number the next item of the numbered list open at each depth gets.
   *
   * An imported page cannot say where an item stands, so it writes every one
   * `1.`, and a session often does the same. The list
   * is counted here instead: its first item gives the start, as in CommonMark,
   * so a list a session began at 3 still begins at 3, and each item after it
   * is one more. A list ends at anything that is not one of its items, deeper
   * ones included; a blank line between two items does not end it. */
  let counting: (number | null)[] = []
  const settle = (level: number) => {
    counting = counting.slice(0, level + 1)
  }
  while (index < lines.length) {
    const line = lines[index]
    const fence = FENCE.exec(line.trim())
    if (fence) {
      const body: string[] = []
      index += 1
      while (index < lines.length && !FENCE.test(lines[index].trim())) body.push(lines[index++])
      index += 1
      out.push({ kind: "code", language: fence[1].trim(), lines: body })
      counting = []
      continue
    }
    const trimmed = line.trim()
    const level = depth(line)
    index += 1
    if (!trimmed) {
      ended = true
      continue
    }
    /* A table is a row of pipes with its alignments under it, as on GitHub;
     * the rows that follow are its own until a blank line or a line without a
     * pipe. A row short of cells is padded, a long one cut to the head. */
    const align =
      trimmed.includes("|") && index < lines.length ? alignments(lines[index].trim()) : null
    const head = align ? cells(trimmed) : []
    if (align && head.length === align.length) {
      index += 1
      const rows: string[][] = []
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        const row = cells(lines[index++])
        rows.push(head.map((_, column) => row[column] ?? ""))
      }
      out.push({ kind: "table", head, align, rows })
      counting = []
      continue
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed)
    if (heading) {
      out.push({ kind: "heading", level: heading[1].length, text: heading[2] })
      counting = []
      continue
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      out.push({ kind: "rule" })
      counting = []
      continue
    }
    const todo = /^[-*+]\s+\[( |x)\]\s*(.*)$/.exec(trimmed)
    if (todo) {
      settle(level)
      counting[level] = null
      out.push({
        kind: "item",
        marker: todo[1] === "x" ? "☑" : "☐",
        depth: level,
        done: todo[1] === "x",
        text: todo[2],
      })
      continue
    }
    if (/^[-*+]\s+/.test(trimmed)) {
      settle(level)
      counting[level] = null
      out.push({
        kind: "item",
        marker: "–",
        depth: level,
        text: trimmed.replace(/^[-*+]\s+/, ""),
      })
      continue
    }
    const ordered = /^(\d+)[.)]\s+(.*)$/.exec(trimmed)
    if (ordered) {
      settle(level)
      const number = counting[level] ?? Number(ordered[1])
      counting[level] = number + 1
      out.push({ kind: "item", marker: `${number}.`, depth: level, text: ordered[2] })
      continue
    }
    counting = []
    const attached = ATTACHED.exec(trimmed)
    if (attached) {
      out.push({ kind: "attached", file: attached[1], label: attached[2] ?? "", block: attached[3] })
      continue
    }
    if (trimmed.startsWith(">")) {
      out.push({ kind: "quote", text: trimmed.replace(/^>\s?/, "") })
      continue
    }
    /* A line under a line is the same paragraph.
     *
     * Two shapes arrive here. An imported page holds one line per block,
     * so two lines in a row are two paragraphs; a body typed by hand
     * has a paragraph wrapped at the width of the editor
     * and a blank line is what ends it. Drawn as separate blocks, the second
     * shape came out as a stack of one-line paragraphs with a gap between each
     * — a brief nobody could read.
     *
     * So consecutive lines join, and the break between them is kept rather than
     * collapsed: the paragraph is one block with its lines where they were
     * written, which is what both shapes look like where they were written. */
    const above = out[out.length - 1]
    if (!ended && above?.kind === "paragraph") above.text += `\n${line}`
    else out.push({ kind: "paragraph", text: line })
    ended = false
  }
  return out
}

export type Span =
  | { kind: "text"; text: string }
  | { kind: "code"; text: string }
  | { kind: "strong"; children: Span[] }
  | { kind: "em"; children: Span[] }
  | { kind: "link"; href: string; children: Span[] }

/** An address a browser may be sent to, and nothing else — never `javascript:`. */
export const reachable = (address: string) => /^(https?:\/\/|\/|mailto:)/i.test(address)

/** Where the code span opening at `from` closes, or -1: on the same line, never empty. */
function codeEnd(text: string, from: number): number {
  const end = text.indexOf("`", from + 1)
  if (end <= from + 1) return -1
  return text.slice(from + 1, end).includes("\n") ? -1 : end
}

/** Where the `delimiter` opened at `from` closes on its line, stepping over code spans. */
function closing(text: string, from: number, delimiter: "**" | "*"): number {
  let at = from + delimiter.length
  while (at < text.length && text[at] !== "\n") {
    if (text[at] === "`") {
      const end = codeEnd(text, at)
      if (end > 0) {
        at = end + 1
        continue
      }
    }
    const bold = delimiter === "**" && text.startsWith("**", at) && at > from + 2
    if (bold && !/\s/.test(text[at - 1])) return at
    if (delimiter === "*" && text[at] === "*") {
      // A `**` inside an emphasis is a bold of its own, not the end of it.
      if (text[at + 1] === "*") {
        const end = closing(text, at, "**")
        if (end > 0) {
          at = end + 2
          continue
        }
      }
      if (!/\s/.test(text[at - 1])) return at
    }
    at += 1
  }
  return -1
}

/* `code`, **bold**, *emphasis* and [a word](behind a link), inside a line.
 *
 * Inside a line and not across two: a paragraph holds the lines it was wrapped
 * over, and a backtick opening a code span on one line has nothing to do with
 * the one that closes something else two lines down. A bold, an emphasis or a
 * link's words are read again for what they hold, so a bold may hold a bit of
 * code or a link; a code span holds nothing but its text. */
export function spans(text: string): Span[] {
  const out: Span[] = []
  let plain = ""
  const push = (span: Span) => {
    if (plain) out.push({ kind: "text", text: plain })
    plain = ""
    out.push(span)
  }
  let at = 0
  while (at < text.length) {
    const char = text[at]
    if (char === "`") {
      const end = codeEnd(text, at)
      if (end > 0) {
        push({ kind: "code", text: text.slice(at + 1, end) })
        at = end + 1
        continue
      }
    }
    if (text.startsWith("**", at) && text[at + 2] && !/[\s*]/.test(text[at + 2])) {
      const end = closing(text, at, "**")
      if (end > 0) {
        push({ kind: "strong", children: spans(text.slice(at + 2, end)) })
        at = end + 2
        continue
      }
    }
    if (char === "*" && text[at + 1] && !/[\s*]/.test(text[at + 1])) {
      const end = closing(text, at, "*")
      if (end > 0) {
        push({ kind: "em", children: spans(text.slice(at + 1, end)) })
        at = end + 1
        continue
      }
    }
    if (char === "[") {
      const link = /^\[([^\]\n]*)\]\(([^)\s]+)\)/.exec(text.slice(at))
      if (link) {
        push({ kind: "link", href: link[2], children: spans(link[1]) })
        at += link[0].length
        continue
      }
    }
    plain += char
    at += 1
  }
  if (plain) out.push({ kind: "text", text: plain })
  return out
}
