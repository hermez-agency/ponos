import * as React from "react"
import {
  Bell,
  Bot,
  CircleAlert,
  CircleCheck,
  FolderGit2,
  GitPullRequest,
  KeyRound,
  Languages,
  ListChecks,
  NotebookText,
  Play,
} from "lucide-react"

import { useT } from "@/lib/i18n"
import type { StepKey } from "@/lib/setup"
import type { SetupHealth } from "@/lib/types"
import { cn } from "@/lib/utils"

const ICONS: Record<StepKey, React.ComponentType<{ className?: string }>> = {
  language: Languages,
  access: KeyRound,
  provider: Bot,
  notion: NotebookText,
  github: GitPullRequest,
  project: FolderGit2,
  channels: Bell,
  demo: Play,
  summary: ListChecks,
}

export const TITLES: Record<StepKey, string> = {
  language: "Language",
  access: "Access",
  provider: "Claude provider",
  notion: "Notion",
  github: "GitHub",
  project: "First project",
  channels: "Channels",
  demo: "First ticket",
  summary: "Summary",
}

/** A step's mark: done, or still something to see to. */
const MARKS: Record<SetupHealth, { label: string; icon: React.ComponentType<{ className?: string }>; tone: string }> = {
  ok: { label: "OK", icon: CircleCheck, tone: "text-tr-green" },
  missing: { label: "Missing", icon: CircleAlert, tone: "text-tr-amber" },
  error: { label: "Error", icon: CircleAlert, tone: "text-destructive" },
}

export function Stepper({
  steps,
  current,
  reachable,
  marks,
  onStep,
}: {
  steps: StepKey[]
  current: StepKey
  reachable: boolean
  marks: Partial<Record<StepKey, SetupHealth>>
  onStep: (step: StepKey) => void
}) {
  const t = useT()
  const at = steps.indexOf(current)
  return (
    <ol className="mb-6 flex flex-wrap gap-1.5" aria-label={t("Steps")}>
      {steps.map((step, index) => {
        const Icon = ICONS[step]
        const here = step === current
        const mark = marks[step] ? MARKS[marks[step]] : null
        const Mark = mark?.icon
        return (
          <li key={step}>
            <button
              type="button"
              disabled={!reachable}
              aria-current={here ? "step" : undefined}
              data-state={marks[step]}
              onClick={() => (here ? undefined : onStep(step))}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                here
                  ? "bg-primary text-primary-foreground border-primary"
                  : index < at
                    ? "text-foreground hover:bg-muted"
                    : "text-muted-foreground hover:bg-muted",
                "disabled:cursor-default"
              )}
            >
              <span className="tabular-nums">{index + 1}</span>
              <Icon className="size-3.5" />
              {t(TITLES[step])}
              {mark && Mark ? (
                <>
                  <Mark className={cn("size-3.5", here ? undefined : mark.tone)} aria-hidden />
                  <span className="sr-only">{t(mark.label)}</span>
                </>
              ) : null}
            </button>
          </li>
        )
      })}
    </ol>
  )
}
