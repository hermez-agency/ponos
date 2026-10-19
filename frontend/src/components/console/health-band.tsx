import * as React from "react"
import { AlertTriangle, ExternalLink, Loader2, OctagonAlert, RefreshCw } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { byGroup, fixParams, shown, type HealthCheck, type HealthGroup, type HealthReport } from "@/lib/health"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

import { ConfirmDialog } from "./confirm-dialog"
import { Panel } from "./frame"

/* What is wrong with the installation, at the top of the dashboard.
 *
 * A badly configured Ponos fails without a word — tickets that do not start,
 * pull requests that never open — so the page that is opened every day says it.
 * The checks are the server's (`health.py`, which `ponos doctor` also prints);
 * this band asks when it is drawn and when "Recheck" is pressed, and draws
 * nothing at all while everything is green: a band that is always there is a
 * band nobody reads.
 *
 * Each failing check says what is wrong, why it likely is, and then one of two
 * things. Where Ponos can mend it itself (a property missing on the Notion
 * board) a "Configure" button opens a window naming what will change, and
 * nothing is changed until it is confirmed. Where it cannot (the integration
 * has to be shared from Notion's own menu), the exact steps come with the link
 * to do them from.
 */

const GROUP: Record<HealthGroup, string> = {
  notion: "Notion",
  github: "GitHub",
  claude: "Claude Code",
  projects: "Projects",
  machine: "Machine",
}

export function HealthBand() {
  const t = useT()
  const [report, setReport] = React.useState<HealthReport | null>(null)
  const [checking, setChecking] = React.useState(false)
  // The newest request wins: an answer that arrives after a later one is stale.
  const asked = React.useRef(0)

  const check = React.useCallback(() => {
    const mine = ++asked.current
    setChecking(true)
    api.health().then(
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

  if (!report || !shown(report.checks)) return null
  const groups = byGroup(report.checks)
  const count = groups.reduce((sum, entry) => sum + entry.checks.length, 0)

  return (
    <section className="px-4 pt-4" data-testid="health-band">
      <Panel
        eyebrow={t("Installation status")}
        title={t("{{count}} thing(s) to fix before tickets can run", { count })}
        action={
          <Button variant="outline" size="sm" onClick={check} disabled={checking} data-testid="health-recheck">
            {checking ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {t("Recheck")}
          </Button>
        }
      >
        <div className="flex flex-col gap-4">
          {groups.map((entry) => (
            <div key={entry.group} className="flex flex-col gap-2">
              <h4 className="text-muted-foreground font-mono text-[0.65rem] font-semibold tracking-[0.14em] uppercase">
                {t(GROUP[entry.group])}
              </h4>
              <ul className="flex flex-col gap-2">
                {entry.checks.map((one) => (
                  <Problem key={`${one.code}:${one.params.project ?? ""}:${one.params.repository ?? ""}`} check={one} onFix={fix} />
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Panel>
    </section>
  )
}

function Problem({ check, onFix }: { check: HealthCheck; onFix: (check: HealthCheck) => Promise<boolean | void> }) {
  const t = useT()
  const error = check.state === "error"
  const Icon = error ? OctagonAlert : AlertTriangle
  const params = fixParams(check)
  return (
    <li
      className={cn(
        "flex flex-col gap-1.5 rounded-lg border px-3 py-2.5 text-sm",
        error ? "border-destructive/40 bg-destructive/5" : "border-amber-500/40 bg-amber-500/5"
      )}
      data-testid="health-check"
      data-code={check.code}
      data-state={check.state}
    >
      <div className="flex items-start gap-2">
        <Icon className={cn("mt-0.5 size-4 shrink-0", error ? "text-destructive" : "text-amber-600")} />
        <div className="min-w-0 flex-1">
          <p className="font-medium">{t(check.title, check.params)}</p>
          <p>{t(check.said, check.params)}</p>
          {check.cause ? (
            <p className="text-muted-foreground">
              {t("Probable cause:")} {t(check.cause, check.params)}
            </p>
          ) : null}
          {check.steps.length ? (
            <ol className="text-muted-foreground mt-1 list-decimal pl-5">
              {check.steps.map((step) => (
                <li key={step}>{t(step, params)}</li>
              ))}
            </ol>
          ) : null}
          {check.evidence ? (
            <pre className="text-muted-foreground mt-1 font-mono text-xs break-words whitespace-pre-wrap">
              {check.evidence}
            </pre>
          ) : null}
        </div>
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
        </div>
      </div>
    </li>
  )
}
