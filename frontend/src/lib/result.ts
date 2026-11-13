/* A ticket's result, as the page hands it on: copied, downloaded, named.
 *
 * Without a DOM and importing nothing, so that `node --test` reads it as it is
 * — the drawing is `components/console/ticket-result.tsx`. */

/** The result as plain words: what « Copy the text » puts in the clipboard.
 *
 * A post pasted into LinkedIn or an email must not carry its asterisks; its
 * lines, its paragraphs and its list markers are what the text is, and stay. */
export function plainText(markdown: string): string {
  const out: string[] = []
  let fenced = false
  for (const line of markdown.replace(/\r\n/g, "\n").split("\n")) {
    if (/^\s*(```|~~~)/.test(line)) {
      fenced = !fenced
      continue
    }
    if (fenced) {
      out.push(line)
      continue
    }
    // A table's rule says nothing; its rows, their cells between tabs.
    if (/^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line) && line.includes("-")) continue
    let said = line
    if (/^\s*\|.*\|\s*$/.test(said)) {
      said = said
        .trim()
        .replace(/^\||\|$/g, "")
        .split("|")
        .map((cell) => cell.trim())
        .join("\t")
    }
    said = said
      .replace(/^(\s*)#{1,6}\s+/, "$1")
      .replace(/^(\s*)>\s?/, "$1")
      .replace(/^(\s*)[-*+]\s+\[( |x|X)\]\s+/, "$1- ")
      .replace(/^(\s*)[*+]\s+/, "$1- ")
      .replace(/!\[([^\]]*)\]\(([^)\s]+)[^)]*\)/g, (_, alt: string, src: string) => alt || src)
      .replace(/\[([^\]]+)\]\(([^)\s]+)[^)]*\)/g, (_, words: string, href: string) =>
        words === href ? href : `${words} (${href})`
      )
      .replace(/(\*\*|__)(.+?)\1/g, "$2")
      .replace(/(^|[^\w*])[*_]([^*_\n]+)[*_](?=[^\w*]|$)/g, "$1$2")
      .replace(/`([^`]+)`/g, "$1")
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(said)) said = ""
    out.push(said)
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim()
}

/** A file name for the result of a ticket: its title, as letters and dashes. */
export function fileName(title: string, extension: string): string {
  const stem = title
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/, "")
  return `${stem || "result"}.${extension}`
}

/** Whether a ticket's result is a document worth a PDF — a report, a text — rather than a change. */
export function isDocument(type: string, kind: string): boolean {
  const said = type.toLowerCase()
  if (said) return !/^code$/.test(said)
  return kind !== "code"
}

/** The columns where the work is over, for now: the ticket has its Result tab there. */
const FINISHED = ["review", "validated", "done"]

/** Whether a ticket in `column` has finished its work — the moment its result is one to read. */
export function isFinished(column: string): boolean {
  return FINISHED.includes(column)
}

// A heading of Markdown, its words apart: « ## 1. Mission : » says « mission ».
const HEADING = /^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/
const said = (line: string): string | undefined => {
  const found = HEADING.exec(line)
  return found
    ? found[1]
        .replace(/^\s*\d+[.)]\s*/, "")
        .replace(/^[*_\s]+|[*_\s:]+$/g, "")
        .toLowerCase()
    : undefined
}

/** The mission as its tab draws it: without a heading « Mission » on top.
 *
 * The server drops the one the page's template opens with (`ticket_page.split`),
 * but a mission written by an agent often opens on its own — under a tab, and a
 * title, that both say it already. Dropped where it is drawn only: the page keeps it. */
export function missionText(mission: string): string {
  const lines = mission.replace(/\r\n/g, "\n").split("\n")
  let start = 0
  while (start < lines.length && (!lines[start].trim() || said(lines[start]) === "mission")) start++
  return lines.slice(start).join("\n").trim()
}

/** What a session said it changed, out of the journal: its report without the
 * history under it, nor the pull request's line — its card is drawn beside. */
export function changes(journal: string): string {
  const lines = journal.replace(/\r\n/g, "\n").split("\n")
  const end = lines.findIndex((line) => ["history", "historique"].includes(said(line) ?? ""))
  return (end < 0 ? lines : lines.slice(0, end))
    .filter((line) => !/^\s*\*\*(Pull request)\s*:?\*\*\s*:?/i.test(line))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}
