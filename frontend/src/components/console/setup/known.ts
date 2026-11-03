import * as React from "react"

import type { Summary } from "@/lib/types"

/** The summary, read once for the visit and shared by every step that shows a
 * part of it — each read costs Notion, GitHub and `claude` a second or more.
 * A step that writes something says so with `reread`, and the summary is read
 * again then, not at each change of step. */
export interface Known {
  summary: Summary | null
  failed: string
  reread: () => void
}

export const KnownContext = React.createContext<Known | null>(null)

/** A step's own reading of the summary: empty until it is read. */
export function useKnown(): Known {
  return React.useContext(KnownContext) ?? { summary: null, failed: "", reread: () => undefined }
}
