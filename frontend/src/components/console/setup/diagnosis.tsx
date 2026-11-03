import * as React from "react"
import { Check, Copy, LoaderCircle, RefreshCw, ScrollText, Stethoscope } from "lucide-react"

import { Rich } from "@/components/console/text"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { copy } from "@/lib/copy"
import { useT } from "@/lib/i18n"

/** `ponos doctor`, run here: the terminal's full diagnosis, to read — or to
 * copy whole into a message to whoever is helping. The same text, so that
 * support never has to ask somebody to open a terminal for it. */
export function Diagnosis() {
  const t = useT()
  const [answer, setAnswer] = React.useState<{ code: number; text: string } | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [copied, setCopied] = React.useState(false)

  const run = async () => {
    setBusy(true)
    setCopied(false)
    try {
      setAnswer(await api.doctor())
    } catch (error) {
      setAnswer({ code: -1, text: why(error) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="flex flex-col gap-2" aria-labelledby="diagnosis">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="diagnosis" className="flex-1 text-sm font-semibold">
          {t("Something does not work?")}
        </h3>
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void run()} data-testid="run-doctor">
          {busy ? <LoaderCircle className="animate-spin" /> : <Stethoscope />}
          {busy ? t("Running the diagnosis…") : t("Run the full diagnosis")}
        </Button>
        {answer ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => void copy(answer.text).then(setCopied)}
          >
            {copied ? <Check /> : <Copy />}
            {t("Copy it for support")}
          </Button>
        ) : null}
      </div>
      <p className="text-muted-foreground text-xs leading-relaxed">
        <Rich text={t("The same as `ponos doctor` in a terminal: every check, and what to do about each one that fails.")} />
      </p>
      {answer ? (
        <pre
          className="bg-muted max-h-96 overflow-auto rounded-lg border p-3 font-mono text-xs whitespace-pre-wrap"
          data-testid="doctor-output"
        >
          {answer.text}
        </pre>
      ) : null}
    </section>
  )
}

/** The end of ponos.log — what the runner and this console said, and the trace
 * of every error they caught — for whoever has no terminal for
 * `ponos logs --service`. Masked on the server, as the file is. */
export function ServiceLog() {
  const t = useT()
  const [answer, setAnswer] = React.useState<{ path: string; lines: string[] } | null>(null)
  const [failed, setFailed] = React.useState("")
  const [busy, setBusy] = React.useState(false)

  const read = async () => {
    setBusy(true)
    setFailed("")
    try {
      setAnswer(await api.serviceLog())
    } catch (error) {
      setFailed(why(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="flex flex-col gap-2" aria-labelledby="service-log">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="service-log" className="flex-1 text-sm font-semibold">
          {t("The runner's journal")}
        </h3>
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void read()} data-testid="read-service-log">
          {busy ? <LoaderCircle className="animate-spin" /> : answer ? <RefreshCw /> : <ScrollText />}
          {answer ? t("Read it again") : t("Read the journal")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs leading-relaxed">
        <Rich text={t("The same as `ponos logs --service` in a terminal: its last lines, with the trace of every error.")} />
      </p>
      {failed ? <p className="text-destructive text-xs">{failed}</p> : null}
      {answer ? (
        <pre
          className="bg-muted max-h-96 overflow-auto rounded-lg border p-3 font-mono text-xs whitespace-pre"
          data-testid="service-log-output"
          title={answer.path}
        >
          {answer.lines.length ? answer.lines.join("\n") : t("Nothing written yet.")}
        </pre>
      ) : null}
    </section>
  )
}
