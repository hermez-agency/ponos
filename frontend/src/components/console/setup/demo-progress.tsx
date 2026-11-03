import { CircleAlert, CircleCheck, ExternalLink, LoaderCircle, RefreshCw, Stethoscope } from "lucide-react"

import { Said } from "@/components/console/setup/bits"
import { Button } from "@/components/ui/button"
import { useT } from "@/lib/i18n"
import type { demoOutcome, StepKey } from "@/lib/setup"
import type { Demo } from "@/lib/types"

/** The demonstration ticket's column, in the console's word for it: the board's own is spelt for the board. */
function statusWord(demo: Pick<Demo, "column" | "status">, t: (key: string) => string): string {
  const ours: Record<string, string> = {
    draft: "Draft",
    ready: "Ready",
    running: "In progress",
    blocked: "Blocked",
    review: "In review",
    validated: "Validated",
    failed: "Failed",
    done: "Done",
    cancelled: "Cancelled",
  }
  return ours[demo.column] ? t(ours[demo.column]) : demo.status
}

/** Where the demonstration ticket is, and — once it stops — what it came to. */
export function DemoProgress({
  demo,
  outcome,
  onStep,
  onAgain,
}: {
  demo: Demo
  outcome: ReturnType<typeof demoOutcome> | null
  onStep: (step: StepKey) => void
  onAgain: () => void
}) {
  const t = useT()
  return (
    <div className="flex flex-col gap-3" data-testid="demo-state" data-outcome={outcome ?? ""}>
      <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm">
        {outcome === "waiting" ? (
          <LoaderCircle className="text-primary size-4 animate-spin" />
        ) : outcome === "done" ? (
          <CircleCheck className="text-tr-green size-4" />
        ) : (
          <CircleAlert className="text-destructive size-4" />
        )}
        <span className="min-w-0 flex-1">
          <span className="font-medium">{demo.title}</span>
          <span className="text-muted-foreground block text-xs">
            {demo.status ? statusWord(demo, t) : t("no status")}
            {demo.progress ? ` — ${demo.progress}` : ""}
          </span>
        </span>
        {demo.url ? (
          <Button asChild size="sm" variant="outline">
            <a href={demo.url} target="_blank" rel="noreferrer">
              {t("Open the ticket")}
              <ExternalLink />
            </a>
          </Button>
        ) : null}
      </div>
      {outcome === "done" ? (
        <Said ok text={t("It works: the ticket ran, and its answer is on the ticket. Ponos is ready.")} />
      ) : outcome === "stuck" ? (
        <Said ok={false} text={t("The ticket stopped on a question — open it to read what it needs.")} />
      ) : outcome === "failed" ? (
        <>
          <Said
            ok={false}
            text={t("The ticket did not run. What it said is below; the summary and its full diagnosis say which part is missing.")}
          />
          {demo.cause ? (
            <div className="flex flex-col gap-1" data-testid="demo-cause">
              <p className="text-sm font-medium">{t(demo.cause)}</p>
              {demo.command ? (
                <code className="bg-muted rounded-lg border p-2 font-mono text-xs">{demo.command}</code>
              ) : null}
            </div>
          ) : null}
          {demo.said ? (
            <pre className="bg-muted max-h-64 overflow-auto rounded-lg border p-3 font-mono text-xs whitespace-pre-wrap">
              {demo.said}
            </pre>
          ) : null}
        </>
      ) : (
        <p className="text-muted-foreground text-sm" role="status">
          {demo.running ? t("Claude is working on it…") : t("Waiting for the run to start…")}
        </p>
      )}
      {outcome && outcome !== "waiting" && outcome !== "done" ? (
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={() => onStep("summary")}>
            <Stethoscope />
            {t("See what is missing")}
          </Button>
          <Button type="button" variant="outline" onClick={onAgain}>
            <RefreshCw />
            {t("Try again")}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
