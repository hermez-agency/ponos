import * as React from "react"
import { ArrowRight, Play } from "lucide-react"

import { Said, StepCard } from "@/components/console/setup/bits"
import { DemoProgress } from "@/components/console/setup/demo-progress"
import { PROJECT_KEY } from "@/components/console/setup/project-step"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { useLanguage, useT } from "@/lib/i18n"
import { demoOutcome, type StepKey } from "@/lib/setup"
import type { Demo } from "@/lib/types"

/* -- 7. the first ticket ---------------------------------------------------- */

/** The demonstration ticket being played, so that a reload finds it again. */
const DEMO_KEY = "ponos-setup-demo"

export function DemoStep({ onNext, onStep }: { onNext: () => void; onStep: (step: StepKey) => void }) {
  const t = useT()
  const language = useLanguage()
  const [id, setId] = React.useState(() => window.localStorage.getItem(DEMO_KEY) ?? "")
  const [demo, setDemo] = React.useState<Demo | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [problem, setProblem] = React.useState("")

  const outcome = demo ? demoOutcome(demo) : null

  React.useEffect(() => {
    if (!id || (outcome && outcome !== "waiting")) return
    let live = true
    const ask = () =>
      api.demo(id).then(
        (read) => live && setDemo(read),
        (error) => {
          if (!live) return
          // A ticket deleted since, or a board changed: start over.
          window.localStorage.removeItem(DEMO_KEY)
          setId("")
          setProblem(why(error))
        }
      )
    void ask()
    const timer = window.setInterval(() => void ask(), 3000)
    return () => {
      live = false
      window.clearInterval(timer)
    }
  }, [id, outcome])

  const start = async () => {
    setBusy(true)
    setProblem("")
    setDemo(null)
    try {
      const project = window.localStorage.getItem(PROJECT_KEY) ?? ""
      const made = await api.startDemo({ project, language })
      window.localStorage.setItem(DEMO_KEY, made.id)
      setId(made.id)
    } catch (error) {
      setProblem(why(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <StepCard
      title={t("A first ticket, played now")}
      blurb={t(
        "The proof that everything holds: Ponos writes a short ticket on your board and runs it at once — Claude reads it, answers, and the answer lands on the ticket. It takes a minute or two."
      )}
      footer={
        <Button type="button" variant={outcome === "done" ? "default" : "outline"} onClick={onNext}>
          {t("Continue")}
          <ArrowRight />
        </Button>
      }
    >
      {!id ? (
        <div>
          <Button type="button" disabled={busy} onClick={() => void start()} data-testid="demo-start">
            <Play />
            {busy ? t("Writing the ticket…") : t("Create and play the demonstration ticket")}
          </Button>
        </div>
      ) : null}
      {id && !demo ? <p className="text-muted-foreground text-sm">{t("Reading the board…")}</p> : null}
      {demo ? (
        <DemoProgress
          demo={demo}
          outcome={outcome}
          onStep={onStep}
          onAgain={() => {
            window.localStorage.removeItem(DEMO_KEY)
            setId("")
            setDemo(null)
          }}
        />
      ) : null}
      <Said ok={false} text={problem} />
    </StepCard>
  )
}
