import * as React from "react"

/* The width under which the console is a phone's: the bar along the bottom,
 * no sidebar — the breakpoint `scope.tsx` draws the menu by. The dashboard
 * reads it to open on what waits for you (`to-handle.tsx`), with its figures
 * folded and its board one column at a time. */
export const PHONE = "(width < 48rem)"

/** Whether the screen is a phone's right now. */
export const isPhone = (): boolean => typeof window !== "undefined" && window.matchMedia(PHONE).matches

/** Whether the screen is a phone's, drawn again when it turns or is resized past the breakpoint. */
export function usePhone(): boolean {
  return React.useSyncExternalStore(
    (listener) => {
      const query = window.matchMedia(PHONE)
      query.addEventListener("change", listener)
      return () => query.removeEventListener("change", listener)
    },
    isPhone
  )
}
