/* Putting a text on the clipboard, wherever the console is opened from.
 *
 * `navigator.clipboard` only exists in a secure context: a console opened by
 * `http://<lan-ip>:8787`, or a Docker install behind a bare IP, has none —
 * and those are the very pages a command is copied from to be typed on
 * another machine. So the clipboard is asked first, and where it is missing or
 * refuses (a permission denied), the page copies the text itself, the old way:
 * a field off screen, selected, `execCommand("copy")`. Deprecated, and still
 * the one way an insecure page has. Where both fail the caller says so — a
 * button that copies nothing in silence is worse than one that admits it.
 *
 * Nothing imported, and the page passed in: `node --test` reads this file as it
 * stands and hands it a page without `navigator.clipboard`.
 */

/** What `toClipboard` reads of the window: `globalThis` in the browser. */
export interface Place {
  navigator?: { clipboard?: { writeText(text: string): Promise<void> } }
  document?: Document
}

/** Whether `text` reached the clipboard. */
export async function toClipboard(text: string, place: Place = globalThis as Place): Promise<boolean> {
  const clipboard = place.navigator?.clipboard
  if (clipboard) {
    try {
      await clipboard.writeText(text)
      return true
    } catch {
      // A permission refused, a page out of focus: the old way may still work.
    }
  }
  return byThePage(text, place.document)
}

/** The text copied from a field the page selects, then drops. */
function byThePage(text: string, document: Document | undefined): boolean {
  if (!document?.body) return false
  const focused = document.activeElement as HTMLElement | null
  const area = document.createElement("textarea")
  area.value = text
  area.setAttribute("readonly", "")
  Object.assign(area.style, { position: "fixed", top: "0", left: "-9999px", opacity: "0" })
  document.body.appendChild(area)
  try {
    area.select()
    return document.execCommand("copy")
  } catch {
    return false
  } finally {
    document.body.removeChild(area)
    focused?.focus?.()
  }
}
