import { CopyIcon, PowerOff } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { copy } from "@/lib/copy"
import { counted, useFrench, useT } from "@/lib/i18n"

/* No daemon running, said once over the columns.
 *
 * It is the machine's state, not a ticket's: said on every ready card, the same
 * amber line ran down the whole column and drowned the board. The count is the
 * cards' own — the server's `held` in `web/board.py`, counted by `RunnerStrip`
 * — so the band and the cards cannot disagree, and it goes the moment a daemon
 * holds the places.
 *
 * A module of its own, with its French beside it: the first load of a French
 * page is held to a budget (tests/test_release.py), and a machine whose daemon
 * runs never draws this band — the same reasoning as `health-french.ts`. */

export const DAEMON_FRENCH: Record<string, string> = {
  "No daemon is running: ready tickets wait.": "Aucun démon ne tourne : les tickets prêts attendent.",
  "{{count}} ticket concerned": "{{count}} ticket concerné",
  "{{count}} tickets concerned": "{{count}} tickets concernés",
  "To start it, type on the machine Ponos runs on:": "Pour le démarrer, tapez sur la machine où tourne Ponos :",
}

const words = () => Promise.resolve(DAEMON_FRENCH)

/* The line that starts the daemon, for the state it is in. The console does
 * not start it itself: `service` is a command it refuses (`REFUSED` in
 * `web/console.py`), since the unit it starts holds the console too. Where
 * systemd is, the unit; where it is not — a container, a machine without it —
 * the daemon itself, in a terminal. */
export function startCommand(state: string | undefined): string {
  return state === "stopped" || state === "no systemd" ? "ponos daemon" : "ponos service on"
}

export default function DaemonBand({ state, waiting }: { state?: string; waiting: number }) {
  const t = useT()
  const worded = useFrench(words)
  if (!worded) return null
  const command = startCommand(state)
  return (
    <Alert className="border-tr-amber/40 bg-tr-amber/10 [&>svg]:text-tr-amber" data-slot="daemon-band">
      <PowerOff aria-hidden />
      <AlertTitle className="line-clamp-none">
        {t("No daemon is running: ready tickets wait.")}{" "}
        <span className="text-muted-foreground font-normal" data-slot="daemon-band-count">
          {counted(waiting, "{{count}} ticket concerned", "{{count}} tickets concerned")}
        </span>
      </AlertTitle>
      <AlertDescription className="flex flex-col gap-1.5">
        <span>{t("To start it, type on the machine Ponos runs on:")}</span>
        <span className="bg-muted flex max-w-full items-center gap-2 self-start rounded-md border py-0.5 pr-0.5 pl-2.5">
          <code className="text-foreground truncate font-mono text-xs">{command}</code>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={() => void copy(command, command)}
            aria-label={t("Copy")}
          >
            <CopyIcon />
          </Button>
        </span>
      </AlertDescription>
    </Alert>
  )
}
