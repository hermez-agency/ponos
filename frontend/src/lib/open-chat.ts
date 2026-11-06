import * as React from "react"

/* Which conversation this tab follows.
 *
 * The server holds no "open" conversation: several can be answering at once,
 * and two tabs may follow two different ones. So the choice is the tab's own,
 * kept in `sessionStorage` (it survives a reload, and a new tab does not
 * inherit it), with the browser's last one in `localStorage` for a tab that
 * opens with none. Empty: the server's latest, or a new one when it has none.
 *
 * Imports nothing of the console, so that `use-transcript` and the pages that
 * open a conversation (the history menu, the sessions page) can share it. */

const TAB = "ponos:chat"
const BROWSER = "ponos:chat-last"

const read = (store: () => Storage, key: string) => {
  try {
    return store().getItem(key) ?? ""
  } catch {
    return ""
  }
}

const write = (store: () => Storage, key: string, value: string) => {
  try {
    if (value) store().setItem(key, value)
    else store().removeItem(key)
  } catch {
    // Storage refused (private mode, full): the choice lasts as long as the page.
  }
}

let current = read(() => sessionStorage, TAB) || read(() => localStorage, BROWSER)
const listeners = new Set<() => void>()

/** The conversation this tab follows, or "" when it has not chosen one. */
export const openChatId = () => current

/** Follow another conversation from now on. */
export function setOpenChat(id: string) {
  if (id === current) return
  current = id
  write(() => sessionStorage, TAB, id)
  write(() => localStorage, BROWSER, id)
  for (const listener of listeners) listener()
}

const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** The conversation this tab follows, redrawn when it changes. */
export const useOpenChat = () => React.useSyncExternalStore(subscribe, openChatId, () => "")
