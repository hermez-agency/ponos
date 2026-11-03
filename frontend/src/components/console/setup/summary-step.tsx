import * as React from "react"
import { ArrowRight } from "lucide-react"

import { StepCard } from "@/components/console/setup/bits"
import { Diagnosis } from "@/components/console/setup/diagnosis"
import { TITLES } from "@/components/console/setup/stepper"
import { SetupSummary } from "@/components/console/setup/summary"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { StepKey } from "@/lib/setup"

/* -- 8. the summary --------------------------------------------------------- */

export function SummaryStep({ onStep }: { onStep: (step: StepKey) => void }) {
  const t = useT()
  // Reaching the summary is going through the steps: the bare address of the
  // console stops leading here (see `setup.pending`).
  React.useEffect(() => {
    void api.setupDone().catch(() => undefined)
  }, [])
  return (
    <StepCard
      title={t("What this console runs on")}
      blurb={t(
        "One line per thing that has to work. A line that is missing can be fixed from its step now, or later from the settings — this summary is at the top of them."
      )}
      footer={
        <Button asChild>
          <a href="/?view=console/tickets/list">
            {t("Open the console")}
            <ArrowRight />
          </a>
        </Button>
      }
    >
      <SetupSummary
        change={(row) =>
          row.step === "summary" ? (
            <a href={`/?view=console/settings/read/config/${row.section}`}>{t("Settings")}</a>
          ) : (
            <button type="button" onClick={() => onStep(row.step)}>
              {t(TITLES[row.step])}
            </button>
          )
        }
      />
      <Diagnosis />
    </StepCard>
  )
}
