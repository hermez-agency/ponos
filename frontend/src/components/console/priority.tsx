import * as React from "react"
import type { InputControllerComponentInterface } from "react-data-form"

import { Input } from "@/components/ui/input"
import { t, useT } from "@/lib/i18n"
import { DEFAULT_SCORE, HIGHEST_SCORE, LOWEST_SCORE, readScore, scoreTone } from "@/lib/priority"
import { cn } from "@/lib/utils"

/* A ticket's priority, as a badge with its score in it: in the gradient
 * `scoreTone` gives, so a glance down a column tells the urgent from what can
 * wait without reading a number. The tone is the score's; how light the
 * background and the figure are is the theme's — a pale badge with a dark
 * figure in light, a deep one with a bright figure in dark, each of them
 * readable on every hue of the gradient, yellow included. */
export function PriorityBadge({ score, className }: { score: number; className?: string }) {
  const t = useT()
  const { hue, saturation } = scoreTone(score)
  const said = t("Priority {{score}} out of 100", { score: String(score) })
  return (
    <span
      data-slot="priority-badge"
      title={said}
      style={{ "--score-hue": hue, "--score-saturation": `${saturation}%` } as React.CSSProperties}
      className={cn(
        "inline-flex min-w-7 items-center justify-center rounded-md border px-1.5 py-0.5 text-[0.7rem] leading-none font-semibold whitespace-nowrap tabular-nums",
        "border-[hsl(var(--score-hue)_var(--score-saturation)_78%)] bg-[hsl(var(--score-hue)_var(--score-saturation)_92%)] text-[hsl(var(--score-hue)_var(--score-saturation)_24%)]",
        "dark:border-[hsl(var(--score-hue)_var(--score-saturation)_32%)] dark:bg-[hsl(var(--score-hue)_var(--score-saturation)_18%)] dark:text-[hsl(var(--score-hue)_var(--score-saturation)_78%)]",
        className
      )}
    >
      {score}
    </span>
  )
}

/* The score, slid or typed — said once, not again in a badge beside it. Empty is
 * an answer, and the field says which: the middle score, 50, the one a ticket
 * nobody ranked waits its turn at. What is not a score from 0 to 100 is said
 * under the field as it is typed, and refused when the form is sent. */
export const PriorityInputController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const raw = formInput.value === null || formInput.value === undefined ? "" : String(formInput.value)
  const score = readScore(raw)
  const tone = scoreTone(score ?? DEFAULT_SCORE)
  const set = (value: string) => onChange({ ...formInput, value, violations: [] })
  const label = t(String(formInput.label ?? ""))
  return (
    <div className="flex flex-col gap-1.5" data-slot="priority-input">
      <div className="flex items-center gap-2">
        <input
          type="range"
          min={LOWEST_SCORE}
          max={HIGHEST_SCORE}
          step={5}
          aria-label={label}
          value={score ?? DEFAULT_SCORE}
          onChange={(event) => set(event.target.value)}
          className="min-w-0 flex-1"
          style={{ accentColor: `hsl(${tone.hue} ${tone.saturation}% 45%)` }}
        />
        <Input
          type="number"
          inputMode="numeric"
          min={LOWEST_SCORE}
          max={HIGHEST_SCORE}
          step={1}
          aria-label={t("{{label}}, from 0 to 100", { label })}
          aria-invalid={score === undefined || undefined}
          placeholder={String(DEFAULT_SCORE)}
          value={raw}
          onChange={(event) => set(event.target.value)}
          className="h-8 w-16 px-2 text-center tabular-nums"
        />
      </div>
      <p className={cn("text-xs", score === undefined ? "text-destructive" : "text-muted-foreground")}>
        {score === undefined
          ? t("A priority is a number from 0 to 100.")
          : t("0: not important at all · 100: right now. Empty, it is 50.")}
      </p>
    </div>
  )
}
