import * as React from "react"
import { toast } from "sonner"

import { api } from "@/lib/api"
import { t } from "@/lib/i18n"
import type { Running, RunnerState, Upgrade, UpgradeProgress } from "@/lib/types"
import { justUpdated, type UpgradePhase } from "@/lib/upgrade"

/* The runner as the header draws it, and the update that restarts it.
 *
 * An update is the one event that reloads the page: the page is the old
 * version's, so once the console is back it is loaded again from the new one,
 * and says so when it opens (`greetUpdate`).
 */

/** Where a page reloaded after an update leaves the version it came back on. */
const UPDATED = "ponos:updated"

/** Reloaded by the update it watched (see `upgrade` below): said once, at opening. */
export function greetUpdate() {
  const updated = sessionStorage.getItem(UPDATED)
  if (updated === null) return
  sessionStorage.removeItem(UPDATED)
  toast.success(t("Ponos is up to date"), {
    description: t("restarted on {{version}}", { version: updated }),
  })
}

/** `catchUp`: where the sessions `/api/state` lists go (`useCatchUp`). */
export function useRunner(catchUp: (sessions: Running[]) => void) {
  const [runner, setRunner] = React.useState<RunnerState | null>(null)
  // The phase this page last saw, to tell a restart it watched from one it did not.
  const upgradePhase = React.useRef<UpgradePhase | undefined>(undefined)

  const reloadState = React.useCallback(async () => {
    try {
      const fresh = await api.state()
      setRunner(fresh)
      if (fresh.sessions) catchUp(fresh.sessions)
    } catch {
      // The header going stale is not worth a message: the stream is still up,
      // and the next event asks again.
    }
  }, [catchUp])

  const on = {
    settings: () => {
      // Another tab saved, or `ponos config` did. The settings pane
      // reloads itself when it is not in the middle of an edit; the header is
      // redrawn either way.
      window.dispatchEvent(new CustomEvent("ponos:settings"))
      void reloadState()
    },

    // An update's progress, from the click to the console coming back. The
    // process that answers after the restart is a new one: its first word is
    // `done`, and the header is read again for the version it runs.
    // The console's own check says so too, with what it found: the button
    // appears in every open page without one of them being reloaded.
    upgrade: (event: UpgradeProgress & Partial<Upgrade>) => {
      const before = upgradePhase.current
      upgradePhase.current = event.phase
      setRunner((current) =>
        current?.upgrade ? { ...current, upgrade: { ...current.upgrade, ...event } } : current
      )
      // The first one is the state the stream replays to every new connection,
      // which the header read at opening already holds: asked again, it was a
      // second /api/state at every load.
      if (before !== undefined && (event.phase === "done" || event.phase === "idle")) {
        void reloadState()
      }
      // The page itself is the old version's: once the console is back, it is
      // loaded again from the new one, and says so when it opens.
      if (justUpdated(before, event.phase)) {
        sessionStorage.setItem(UPDATED, event.target)
        window.location.reload()
      }
    },
  }

  return { runner, reloadState, on }
}
