import * as React from "react"
import {
  Bell,
  Bot,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  GitPullRequest,
  HardDrive,
  ListChecks,
  NotebookText,
  Route,
  Terminal,
} from "lucide-react"

import { Explaining, Said } from "@/components/console/setup/bits"
import { KnownContext } from "@/components/console/setup/known"
import { Badge } from "@/components/ui/badge"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { rows, type Row } from "@/lib/setup"
import type { SetupHealth, Summary } from "@/lib/types"

/* -- the summary, wherever it is drawn -------------------------------------- */

const STATES: Record<SetupHealth, { label: string; icon: React.ComponentType<{ className?: string }>; tone: string }> = {
  ok: { label: "OK", icon: CircleCheck, tone: "text-tr-green border-tr-green/40" },
  missing: { label: "Missing", icon: CircleDashed, tone: "text-tr-amber border-tr-amber/40" },
  error: { label: "Error", icon: CircleAlert, tone: "text-destructive border-destructive/40" },
}

const ROW_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  machine: HardDrive,
  provider: Bot,
  model: Route,
  board: NotebookText,
  github: GitPullRequest,
  projects: ListChecks,
  channels: Bell,
  environment: Terminal,
}

/** A line's sentence, its linked parameter drawn as a link where the translation put it. */
function RowValue({ row }: { row: Row }) {
  const t = useT()
  const { link } = row
  if (!link) return <>{t(row.value, row.params)}</>
  const mark = "\u0000"
  const [before, after = ""] = t(row.value, { ...row.params, [link.param]: mark }).split(mark)
  return (
    <>
      {before}
      <a href={link.url} target="_blank" rel="noreferrer" title={link.title} className="underline underline-offset-2">
        {row.params[link.param]}
      </a>
      {after}
    </>
  )
}

/** The installation at a glance, as a record: one line per field, its state, and where it changes. */
export function SetupSummary({ change }: { change: (row: Row) => React.ReactNode }) {
  const t = useT()
  // In the first connection, the summary it has already read; elsewhere, its own.
  const known = React.useContext(KnownContext)
  const [own, setSummary] = React.useState<Summary | null>(null)
  const [ownFailed, setFailed] = React.useState("")
  const summary = known ? known.summary : own
  const failed = known ? known.failed : ownFailed

  React.useEffect(() => {
    if (known) return
    let live = true
    api.summary().then(
      (read) => live && setSummary(read),
      (error) => live && setFailed(why(error))
    )
    return () => {
      live = false
    }
  }, [known])

  if (failed && !summary) return <Said ok={false} text={failed} />
  if (!summary) return <p className="text-muted-foreground text-sm">{t("Checking…")}</p>

  return (
    <dl className="divide-border flex flex-col divide-y rounded-xl border" data-testid="summary-rows">
      {rows(summary).map((row) => {
        const state = STATES[row.state]
        const Icon = ROW_ICONS[row.key] ?? ListChecks
        const StateIcon = state.icon
        return (
          <div
            key={row.key}
            data-row={row.key}
            data-state={row.state}
            className="grid grid-cols-[auto_1fr_auto] items-start gap-x-3 gap-y-1 px-4 py-3 sm:grid-cols-[auto_11rem_1fr_auto]"
          >
            <Icon className="text-muted-foreground mt-0.5 size-4" />
            <dt className="text-sm font-medium">{t(row.label)}</dt>
            <dd className="col-start-2 min-w-0 text-sm sm:col-start-3 sm:row-start-1">
              <span className="break-words">
                <RowValue row={row} />
              </span>
              {row.notes.map((note, index) => (
                <span key={index} className="text-muted-foreground block text-xs break-words">
                  <Explaining note={note} />
                </span>
              ))}
            </dd>
            <div className="col-start-3 row-span-2 row-start-1 flex flex-col items-end gap-1 sm:col-start-4 sm:row-span-1">
              <Badge variant="outline" className={state.tone}>
                <StateIcon />
                {t(state.label)}
              </Badge>
              <span className="text-xs underline-offset-2 [&>a]:underline [&>button]:cursor-pointer [&>button]:underline">
                {change(row)}
              </span>
            </div>
          </div>
        )
      })}
    </dl>
  )
}
