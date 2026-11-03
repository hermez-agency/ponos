import * as React from "react"
import { AlertTriangle, ChevronRight, ExternalLink, Loader2, OctagonAlert, RefreshCw } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { api, why } from "@/lib/api"
import { blocking, failing, fixParams, quoted, shown, silent } from "@/lib/health"
import type { HealthCheck, HealthReport } from "@/lib/types"
import { counted, useFrench, useLanguage, useT } from "@/lib/i18n"
import { count } from "@/lib/numbers"
import { cn } from "@/lib/utils"

import { ConfirmDialog } from "./confirm-dialog"

/* What is wrong with the installation, at the top of the dashboard.
 *
 * A badly configured Ponos fails without a word — tickets that do not start,
 * pull requests that never open — so the page that is opened every day says it.
 * The checks are the server's (`health.py`, which `ponos doctor` also prints);
 * this band asks when it is drawn — the server answers what it found a few
 * minutes ago at most — and afresh when "Recheck" is pressed, and draws
 * nothing at all while everything is green: a band that is always there is a
 * band nobody reads.
 *
 * Folded or not, the band takes its place in the page's flow, above the
 * runner's line. It was once laid over the page while folded, in a slot of no
 * height, so that its answer — a second or two after the rest — did not move
 * the dashboard: but the slot was where the runner's line is, and the band hid
 * its sessions and its timer. The server now answers from its last check, so
 * the band comes with the page rather than after it; unfolded, it pushes the
 * statistics down, since laid over its list hid what it was opened above.
 *
 * The band is one line while folded — a count, "Recheck" — so that the
 * statistics under it stay on the first screen; unfolded, each failing check is
 * a line of its own (what is wrong, and the button that mends it), and its own
 * toggle opens why it likely is and the technical detail. Both choices are
 * kept with the browser, the band's like the CI block's of a ticket.
 *
 * Each failing check says what is wrong, why it likely is, and then one of two
 * things. Where Ponos can mend it itself (a property missing on the Notion
 * board) a "Configure" button opens a window naming what will change, and
 * nothing is changed until it is confirmed. Where it cannot (the integration
 * has to be shared from Notion's own menu), the exact steps come with the link
 * to do them from.
 */

const OPEN_KEY = "ponos-health-open"

/* The checks' own sentences, in French: fetched when the band is drawn, see `health-french.ts`. */
const words = () => import("@/lib/health-french").then((module) => module.HEALTH_FRENCH)

/* Whether the list is unfolded: folded until chosen otherwise, and the choice
 * outlives the page. */
function useOpen() {
  const [open, setOpen] = React.useState(() => {
    try {
      return localStorage.getItem(OPEN_KEY) === "open"
    } catch {
      return false
    }
  })
  const choose = React.useCallback((next: boolean) => {
    setOpen(next)
    try {
      localStorage.setItem(OPEN_KEY, next ? "open" : "folded")
    } catch {
      // Storage off: the choice lasts as long as the tab.
    }
  }, [])
  return [open, choose] as const
}

const chevron = (open: boolean) => (
  <ChevronRight
    className={cn("text-muted-foreground size-3.5 shrink-0 transition-transform", open && "rotate-90")}
    aria-hidden
  />
)

export function HealthBand() {
  const t = useT()
  const [report, setReport] = React.useState<HealthReport | null>(null)
  const [checking, setChecking] = React.useState(false)
  const [open, choose] = useOpen()
  const worded = useFrench(words)
  // The newest request wins: an answer that arrives after a later one is stale.
  const asked = React.useRef(0)

  const check = React.useCallback((fresh = false) => {
    const mine = ++asked.current
    setChecking(true)
    api.health(fresh).then(
      (read) => mine === asked.current && (setReport(read), setChecking(false)),
      () => mine === asked.current && setChecking(false)
    )
  }, [])

  React.useEffect(() => check(), [check])

  // An answer past its time is still the one given, and the check it started
  // arrives on the stream. A reconnection replays older ones: the newest wins.
  React.useEffect(() => {
    const listener = (event: Event) => {
      const read = (event as CustomEvent<HealthReport>).detail
      setReport((current) => (current && current.checked_at >= read.checked_at ? current : read))
    }
    window.addEventListener("ponos:health", listener)
    return () => window.removeEventListener("ponos:health", listener)
  }, [])

  const fix = async (one: HealthCheck) => {
    if (!one.fix) return false
    try {
      const read = await api.fixHealth(one.fix.action, one.fix.target)
      asked.current++
      setReport(read)
      toast.success(t("Done."))
    } catch (error) {
      toast.error(why(error))
      return false
    }
  }

  if (!report || !worded || !shown(report.checks)) return null
  const checks = failing(report.checks)
  const stopping = checks.filter(blocking).length
  const channels = silent(checks)
  const errors = stopping > 0
  const Icon = errors ? OctagonAlert : AlertTriangle
  const lost = count(
    channels.length,
    "{{count}} thing to fix: {{channels}} notifications do not arrive",
    "{{count}} things to fix: {{channels}} notifications do not arrive"
  )
  const fixes = checks.filter((one) => one.state === "error").length

  return (
    <section className="py-3" data-testid="health-band">
      <Collapsible open={open} onOpenChange={choose} className="bg-card rounded-xl border shadow-lg">
        <div className="flex items-center justify-between gap-3 px-4 py-2.5">
          <CollapsibleTrigger
            className="focus-visible:ring-ring/50 flex min-w-0 items-center gap-2 rounded-md text-left outline-none focus-visible:ring-2"
            data-testid="health-toggle"
          >
            {chevron(open)}
            <Icon className={cn("size-4 shrink-0", errors ? "text-destructive" : "text-amber-600")} />
            <span className="min-w-0 truncate text-sm font-medium">
              {/* "Before tickets can run" only when something stops them: a
                  warning is a ticket that runs, with something to look at, and
                  a channel in error is a notification lost, not a ticket. */}
              {[
                errors &&
                  counted(
                    stopping,
                    "{{count}} thing to fix before tickets can run",
                    "{{count}} things to fix before tickets can run"
                  ),
                channels.length > 0 && t(lost.key, { ...lost.params, channels: channels.join(", ") }),
                checks.length > fixes && counted(checks.length - fixes, "{{count}} warning", "{{count}} warnings"),
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </CollapsibleTrigger>
          <Button variant="outline" size="sm" onClick={() => check(true)} disabled={checking} data-testid="health-recheck">
            {checking ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {t("Recheck")}
          </Button>
        </div>
        <CollapsibleContent>
          <ul className="flex flex-col gap-2 px-4 pb-3">
            {checks.map((one) => (
              <Problem key={`${one.code}:${Object.values(one.params).join(":")}`} check={one} onFix={fix} />
            ))}
          </ul>
        </CollapsibleContent>
      </Collapsible>
    </section>
  )
}

function Problem({ check, onFix }: { check: HealthCheck; onFix: (check: HealthCheck) => Promise<boolean | void> }) {
  const t = useT()
  const french = useLanguage() === "fr"
  const [more, setMore] = React.useState(false)
  const error = blocking(check)
  const Icon = error ? OctagonAlert : AlertTriangle
  const own = quoted(check.params, french)
  const params = quoted(fixParams(check), french)
  const detailed = Boolean(check.cause || check.steps.length || check.notes.length || check.evidence)
  return (
    <Collapsible asChild open={more} onOpenChange={setMore}>
      <li
        className={cn(
          "flex flex-col gap-1.5 rounded-lg border px-3 py-2 text-sm",
          error ? "border-destructive/40 bg-destructive/5" : "border-amber-500/40 bg-amber-500/5"
        )}
        data-testid="health-check"
        data-code={check.code}
        data-state={check.state}
      >
        <div className="flex items-center gap-2">
          <Icon className={cn("size-4 shrink-0", error ? "text-destructive" : "text-amber-600")} />
          <p className="min-w-0 flex-1">
            <span className="font-medium">{t(check.title, own)}</span>
            <span className="text-muted-foreground"> — {t(check.said, own)}</span>
          </p>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {check.url ? (
              <Button asChild variant="outline" size="sm">
                <a href={check.url} target="_blank" rel="noreferrer">
                  <ExternalLink />
                  {t("Open the link")}
                </a>
              </Button>
            ) : null}
            {check.fix ? (
              <ConfirmDialog
                title={t("Configure automatically?")}
                description={t(check.fix.confirm, params)}
                confirm={t(check.fix.label)}
                onConfirm={() => onFix(check)}
                trigger={
                  <Button size="sm" data-testid="health-fix">
                    {t(check.fix.label)}
                  </Button>
                }
              />
            ) : null}
            {detailed ? (
              <CollapsibleTrigger
                className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 flex items-center gap-1 rounded-md px-1 text-xs outline-none focus-visible:ring-2"
                data-testid="health-detail-toggle"
              >
                {chevron(more)}
                {t("Details")}
              </CollapsibleTrigger>
            ) : null}
          </div>
        </div>
        {detailed ? (
          <CollapsibleContent className="text-muted-foreground flex flex-col gap-1 pl-6 text-xs" data-testid="health-detail">
            {check.cause ? (
              <p>
                {t("Probable cause:")} {t(check.cause, own)}
              </p>
            ) : null}
            {check.steps.length ? (
              <ol className="list-decimal pl-4">
                {check.steps.map((step) => (
                  <li key={step}>{t(step, params)}</li>
                ))}
              </ol>
            ) : null}
            {check.notes.length ? (
              <ul className="list-disc pl-4">
                {check.notes.map((note) => (
                  <li key={note.name}>
                    <span className="font-medium">{french ? `« ${note.name} »` : `“${note.name}”`}</span> : {note.said.map((said) => t(said)).join(" ; ")}
                  </li>
                ))}
              </ul>
            ) : null}
            {check.evidence ? (
              <pre className="font-mono text-[0.7rem] break-words whitespace-pre-wrap opacity-80">{check.evidence}</pre>
            ) : null}
          </CollapsibleContent>
        ) : null}
      </li>
    </Collapsible>
  )
}
