import * as React from "react"

import { stopsOnEscape, type Pending } from "@/lib/composer"

/* Escape from an empty field stops the turn. Caught on the window before
 * anything else, like the recording's Escape: the drawer listens for it on
 * the document, and would close itself on a key that meant "stop". */
export function useStopOnEscape(
  field: React.RefObject<HTMLTextAreaElement | null>,
  now: { onStop?: () => void; text: string; pending: Pending[]; busy: boolean }
) {
  const stopper = React.useRef(now)
  stopper.current = now
  React.useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.target !== field.current) return
      const now = stopper.current
      const stop = now.onStop
      if (!stop || !stopsOnEscape({ ...now, attachments: now.pending, stoppable: true })) return
      event.preventDefault()
      event.stopPropagation()
      stop()
    }
    window.addEventListener("keydown", listener, true)
    return () => window.removeEventListener("keydown", listener, true)
  }, [field])
}
