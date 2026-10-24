import * as React from "react"
import { AlertTriangle, ChevronRight, ExternalLink, Loader2, OctagonAlert, RefreshCw } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { api, why } from "@/lib/api"
import { failing, fixParams, shown } from "@/lib/health"
import type { HealthCheck, HealthReport } from "@/lib/types"
import { counted, useFrench, useT } from "@/lib/i18n"
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
 * The answer comes a second or two after the rest of the page, so the folded
 * band is laid over the page, in a slot of no height, rather than in its flow:
 * pushed in, it moved the whole dashboard down while somebody was aiming at a
 * card. Unfolded, it takes its place in the flow and pushes the statistics
 * down: laid over, its list hid the cards and the charts it was opened above.
 * The page moves then because somebody asked it to — or, the list kept open,
 * once when the answer arrives, which is what keeping it open chose.
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
  const errors = checks.some((one) => one.state === "error")
  const Icon = errors ? OctagonAlert : AlertTriangle

  return (
    <div className={cn("relative z-30", !open && "h-0")}>
      <section className={cn("py-3", !open && "absolute inset-x-0 top-0")} data-testid="health-band">
        <Collapsible open={open} onOpenChange={choose} className="bg-card rounded-xl border shadow-lg">
          <div className="flex items-center justify-between gap-3 px-4 py-2.5">
            <CollapsibleTrigger
              className="focus-visible:ring-ring/50 flex min-w-0 items-center gap-2 rounded-md text-left outline-none focus-visible:ring-2"
              data-testid="health-toggle"
            >
              {chevron(open)}
              <Icon className={cn("size-4 shrink-0", errors ? "text-destructive" : "text-amber-600")} />
              <span className="min-w-0 truncate text-sm font-medium">
                {counted(
                  checks.length,
                  "{{count}} thing to fix before tickets can run",
                  "{{count}} things to fix before tickets can run"
                )}
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
    </div>
  )
}

function Problem({ check, onFix }: { check: HealthCheck; onFix: (check: HealthCheck) => Promise<boolean | void> }) {
  const t = useT()
  const [more, setMore] = React.useState(false)
  const error = check.state === "error"
  const Icon = error ? OctagonAlert : AlertTriangle
  const params = fixParams(check)
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
            <span className="font-medium">{t(check.title, check.params)}</span>
            <span className="text-muted-foreground"> — {t(check.said, check.params)}</span>
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
                {t("Probable cause:")} {t(check.cause, check.params)}
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
                    <span className="font-medium">“{note.name}”</span> : {note.said.map((said) => t(said)).join(" ; ")}
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
