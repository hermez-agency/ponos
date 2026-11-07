import * as React from "react"

const KEY = "ponos-theme"

export type Theme = "dark" | "light"

/** Which of the two the console is in, and the switch that changes it.
 *
 * Dark is the default because the console it replaces had no other: it sits
 * beside a terminal and an editor, and the thing it shows most of the time
 * is a log. The choice is one line in `localStorage`, read before the first
 * paint by the script in `index.html` so the page never flashes white.
 */
export function useTheme() {
  const [theme, setTheme] = React.useState<Theme>(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light"
  )

  React.useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
    try {
      localStorage.setItem(KEY, theme)
    } catch {
      // A browser with storage switched off still gets the theme it asked for,
      // for as long as the tab is open. That is the whole cost.
    }
  }, [theme])

  const toggle = React.useCallback(
    () => setTheme((current) => (current === "dark" ? "light" : "dark")),
    []
  )

  return { theme, setTheme, toggle }
}

/* The theme the page is in right now, for what has to follow it rather than
 * change it — the robots, of which a board draws a hundred.
 *
 * `useTheme` holds its own copy, which is right for the one switch that sets
 * it and wrong for anything else: a copy per robot would not hear the switch.
 * This reads the class on <html> the switch writes, through one observer for
 * the whole page. */
const watchers = new Set<() => void>()
let observer: MutationObserver | null = null

function watch(listener: () => void) {
  watchers.add(listener)
  if (!observer) {
    observer = new MutationObserver(() => watchers.forEach((watcher) => watcher()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] })
  }
  return () => {
    watchers.delete(listener)
    if (!watchers.size) {
      observer?.disconnect()
      observer = null
    }
  }
}

const shown = (): Theme => (document.documentElement.classList.contains("dark") ? "dark" : "light")

export function useShownTheme(): Theme {
  return React.useSyncExternalStore(watch, shown)
}
