import * as React from "react"
import {
  ArrowUp,
  CheckIcon,
  CircleIcon,
  CopyIcon,
  ExternalLinkIcon,
  Loader2Icon,
  TriangleAlertIcon,
} from "lucide-react"
import { toast } from "sonner"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useConsole } from "@/hooks/use-console"
import { api, why } from "@/lib/api"
import { copy } from "@/lib/copy"
import { useT } from "@/lib/i18n"
import type { RunnerState, Upgrade } from "@/lib/types"
import { badgeMode, STEPS, stepState } from "@/lib/upgrade"
import { cn } from "@/lib/utils"
import { when } from "./ticket-bits"

/* The number this console is running, and — the one day it matters — the
 * update waiting behind it.
 *
 * The version is the release number followed by the commit it runs, and its
 * tooltip says which commit: the hash, its date, its subject. With a newer one
 * waiting a button joins it, with how many commits behind, and the subjects of
 * those commits in its tooltip: a click opens what is installed, what would be,
 * where the release notes are, and asks before doing anything. The server does the rest (`web/upgrade.py`) — waiting for a
 * ticket in flight, installing, restarting — and says each step down the
 * stream, which is how every open tab follows the same update.
 */
export function VersionBadge({ offerOnly = false }: { offerOnly?: boolean }) {
  const { runner } = useConsole()
  const t = useT()
  const [open, setOpen] = React.useState(false)
  if (!runner) return null

  const upgrade = runner.upgrade
  const mode = badgeMode(upgrade)
  const label =
    mode === "working"
      ? t("Updating…")
      : mode === "failed"
        ? t("Update failed")
        : t("Version {{version}} → {{target}}, click to update", {
            version: runner.version,
            target: target(upgrade),
          })

  return (
    <>
      {/* On a phone the number is said in the bar's one status pill (see
          `shell`): here, only the button, the day there is one. */}
      {offerOnly ? null : (
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              tabIndex={0}
              className="text-muted-foreground flex items-center gap-1 rounded-md px-2 font-mono text-[0.7rem] outline-hidden focus-visible:ring-ring/30 focus-visible:ring-2"
            >
              v{runner.version}
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-sm text-left">
            <Commit runner={runner} />
          </TooltipContent>
        </Tooltip>
      )}
      {mode === "version" ? null : (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={() => setOpen(true)}
              aria-label={label}
              className={cn(
                "flex items-center gap-1 rounded-md px-2 py-1 text-[0.7rem] font-medium outline-hidden transition-colors",
                "hover:bg-accent focus-visible:ring-ring/30 focus-visible:ring-2",
                mode === "failed" ? "text-tr-red" : "text-tr-amber"
              )}
            >
              {mode === "working" ? (
                <Loader2Icon className="size-3 shrink-0 animate-spin" />
              ) : mode === "failed" ? (
                <TriangleAlertIcon className="size-3 shrink-0" />
              ) : (
                <ArrowUp className="size-3 shrink-0" />
              )}
              {mode === "offer" ? (
                <span className="hidden md:inline">{t("Update")}</span>
              ) : null}
              {/* How many commits behind: the one figure worth the room. */}
              {mode === "offer" && upgrade?.behind ? (
                <span className="bg-tr-amber/15 rounded-full px-1.5 font-mono tabular-nums">
                  {upgrade.behind}
                </span>
              ) : null}
            </button>
          </TooltipTrigger>
          <TooltipContent className="max-w-sm text-left">
            <span>{label}</span>
            {mode === "offer" && upgrade?.commits?.length ? (
              <Coming upgrade={upgrade} />
            ) : null}
          </TooltipContent>
        </Tooltip>
      )}
      {/* Mounted whatever the badge is: the dialog that watched the restart
          stays open on "up to date" once the version stops being an offer. */}
      {upgrade ? (
        <UpgradeDialog open={open} onOpenChange={setOpen} runner={runner} upgrade={upgrade} />
      ) : null}
    </>
  )
}

/** Which code answers: the commit the version names, when it was made, and what it said. */
function Commit({ runner }: { runner: RunnerState }) {
  const t = useT()
  const commit = runner.commit
  if (!commit?.commit) return <span>{t("the version this console runs")}</span>
  return (
    <span className="flex flex-col gap-1">
      <span className="font-mono text-[0.65rem] break-all">{commit.commit}</span>
      <span className="opacity-70">{when(commit.date)}</span>
      <span className="font-medium">{commit.subject}</span>
    </span>
  )
}

/** What an update brings: the subjects of the commits it is behind, newest first. */
function Coming({ upgrade }: { upgrade: Upgrade }) {
  const t = useT()
  const more = upgrade.behind - upgrade.commits.length
  return (
    <ul className="mt-1.5 flex list-disc flex-col gap-0.5 pl-4">
      {upgrade.commits.map((subject, index) => (
        <li key={index} className="line-clamp-2">
          {subject}
        </li>
      ))}
      {more > 0 ? (
        <li className="list-none opacity-70">{t("and {{count}} more", { count: String(more) })}</li>
      ) : null}
    </ul>
  )
}

/** The version a person reads for the newest one: its release, or its commit. */
function target(upgrade: Upgrade | undefined): string {
  if (!upgrade) return ""
  return upgrade.tag || upgrade.latest || upgrade.target
}

function UpgradeDialog({
  open,
  onOpenChange,
  runner,
  upgrade,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  runner: RunnerState
  upgrade: Upgrade
}) {
  const t = useT()
  const [sending, setSending] = React.useState(false)
  const mode = badgeMode(upgrade)
  const done = upgrade.phase === "done"

  const start = async () => {
    setSending(true)
    try {
      await api.upgrade()
    } catch (error) {
      toast.error(t("The update did not start"), { description: why(error) })
    } finally {
      setSending(false)
    }
  }

  const callOff = async () => {
    try {
      await api.cancelUpgrade()
    } catch (error) {
      toast.error(why(error))
    }
  }

  const title = done
    ? t("Ponos is up to date")
    : mode === "working"
      ? t("Updating Ponos")
      : mode === "failed"
        ? t("The update failed")
        : t("Update Ponos")

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" closeLabel={t("Close")}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription asChild>
            <div className="flex flex-col gap-1">
              {done ? (
                <span>{t("restarted on {{version}}", { version: upgrade.target })}</span>
              ) : (
                <span className="text-foreground font-mono text-xs">
                  v{runner.version}
                  {upgrade.current ? ` · ${upgrade.current}` : ""}
                  {" → "}
                  <span className="text-tr-amber">
                    {upgrade.tag ? `${upgrade.tag} · ${upgrade.latest}` : upgrade.latest || upgrade.target}
                  </span>
                </span>
              )}
              {upgrade.notes && !done ? (
                <a
                  href={upgrade.notes}
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary inline-flex w-fit items-center gap-1 text-sm underline-offset-4 hover:underline"
                >
                  {upgrade.tag ? t("Release notes") : t("What changed")}
                  <ExternalLinkIcon className="size-3" />
                </a>
              ) : null}
            </div>
          </DialogDescription>
        </DialogHeader>

        {mode === "offer" && !done ? (
          upgrade.automatic ? (
            <Offer running={runner.running} />
          ) : (
            <Manual upgrade={upgrade} />
          )
        ) : null}

        {mode === "working" ? <Progress upgrade={upgrade} /> : null}

        {mode === "failed" ? (
          <>
            <Alert variant="destructive">
              <TriangleAlertIcon />
              <AlertTitle>{t("Ponos stayed on its previous version")}</AlertTitle>
              <AlertDescription className="break-words">{upgrade.error}</AlertDescription>
            </Alert>
            <Log upgrade={upgrade} />
          </>
        ) : null}

        <DialogFooter>
          {upgrade.phase === "waiting" ? (
            <Button type="button" variant="ghost" onClick={callOff}>
              {t("Call it off")}
            </Button>
          ) : null}
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            {mode === "offer" && upgrade.automatic && !done ? t("Cancel") : t("Close")}
          </Button>
          {(mode === "offer" || mode === "failed") && upgrade.available && upgrade.automatic && !done ? (
            <Button type="button" disabled={sending} onClick={start}>
              {sending ? <Loader2Icon className="animate-spin" /> : null}
              {mode === "failed"
                ? t("Try again")
                : runner.running
                  ? t("Update after the ticket")
                  : t("Update now")}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** What a click will do — and, with a ticket running, that it will wait for it. */
function Offer({ running }: { running: boolean }) {
  const t = useT()
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p className="text-muted-foreground">
        {t(
          "Ponos downloads the new version, checks that it starts, then restarts the console. The page reconnects on its own; if anything fails, the current version stays."
        )}
      </p>
      {running ? (
        <Alert>
          <Loader2Icon className="animate-spin" />
          <AlertTitle>{t("A ticket is running")}</AlertTitle>
          <AlertDescription>
            {t(
              "The update will start once it has finished: nothing is interrupted, and no ticket starts in between."
            )}
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  )
}

/** Where the console cannot do it: why, and the line to type instead. */
function Manual({ upgrade }: { upgrade: Upgrade }) {
  const t = useT()
  const copyIt = () => {
    void copy(upgrade.command, upgrade.command)
  }
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p className="text-muted-foreground">
        {t("This console cannot update Ponos itself: {{why}}. On the machine it runs on, type:", {
          why: t(upgrade.manual),
        })}
      </p>
      <div className="bg-muted flex items-center gap-2 rounded-md border py-1 pr-1 pl-3">
        <code className="flex-1 truncate font-mono text-xs">{upgrade.command}</code>
        <Button type="button" variant="ghost" size="icon-sm" onClick={copyIt} aria-label={t("Copy")}>
          <CopyIcon />
        </Button>
      </div>
    </div>
  )
}

const STEP_LABELS: Record<(typeof STEPS)[number], string> = {
  downloading: "Downloading the new version",
  installing: "Checking that it starts, and installing it",
  restarting: "Restarting the console",
}

/** The steps, the one under way, and what the server wrote about them. */
function Progress({ upgrade }: { upgrade: Upgrade }) {
  const t = useT()
  return (
    <div className="flex flex-col gap-3 text-sm">
      {upgrade.phase === "waiting" ? (
        <Alert>
          <Loader2Icon className="animate-spin" />
          <AlertTitle>{t("Update scheduled")}</AlertTitle>
          <AlertDescription>
            {upgrade.detail
              ? t("It starts as soon as this is over: {{what}}. No ticket starts in between.", {
                  what: t(upgrade.detail),
                })
              : t("Starting…")}
          </AlertDescription>
        </Alert>
      ) : null}
      <ol className="flex flex-col gap-2">
        {STEPS.map((step) => {
          const state = stepState(step, upgrade.phase)
          return (
            <li
              key={step}
              className={cn(
                "flex items-center gap-2",
                state === "pending" ? "text-muted-foreground" : "text-foreground"
              )}
            >
              {state === "done" ? (
                <CheckIcon className="text-tr-green size-4 shrink-0" />
              ) : state === "current" ? (
                <Loader2Icon className="text-tr-amber size-4 shrink-0 animate-spin" />
              ) : (
                <CircleIcon className="size-4 shrink-0 opacity-40" />
              )}
              {t(STEP_LABELS[step])}
            </li>
          )
        })}
      </ol>
      {upgrade.phase === "restarting" ? (
        <p className="text-muted-foreground">
          {t("The page reconnects by itself once the new version answers.")}
        </p>
      ) : null}
      <Log upgrade={upgrade} />
    </div>
  )
}

/** The update's own log: the lines of this one, and the file that keeps them all. */
function Log({ upgrade }: { upgrade: Upgrade }) {
  const t = useT()
  if (!upgrade.log.length) return null
  return (
    <details className="text-xs">
      <summary className="text-muted-foreground cursor-pointer select-none">{t("Log")}</summary>
      <pre className="bg-muted mt-2 max-h-40 overflow-auto rounded-md p-2 font-mono text-[0.7rem] whitespace-pre-wrap">
        {upgrade.log.join("\n")}
      </pre>
      {upgrade.log_path ? (
        <p className="text-muted-foreground mt-1 font-mono text-[0.65rem] break-all">{upgrade.log_path}</p>
      ) : null}
    </details>
  )
}
