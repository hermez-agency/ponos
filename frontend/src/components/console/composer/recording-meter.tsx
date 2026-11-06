import { Loader2Icon } from "lucide-react"
import * as React from "react"

import { clock } from "@/lib/composer"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

/** What takes the field's place while the microphone listens: a clock and the wave. */
export function RecordingMeter({ seconds, levels }: { seconds: number; levels: number[] }) {
  const t = useT()
  return (
    <div className="flex h-12 items-center gap-3 px-4 pt-2" aria-live="polite">
      <span className="bg-destructive size-2.5 shrink-0 animate-pulse rounded-full" />
      <span className="font-mono text-sm tabular-nums">{clock(seconds)}</span>
      <span className="flex h-7 flex-1 items-center justify-between gap-[2px] overflow-hidden" aria-hidden>
        {levels.map((level, index) => (
          <span
            key={index}
            className="bg-primary/80 w-[3px] max-w-[3px] min-w-px flex-1 rounded-full transition-[height] duration-75"
            style={{ height: `${Math.max(12, level * 100)}%` }}
          />
        ))}
      </span>
      <span className="sr-only">{t("Recording")}</span>
    </div>
  )
}

/* The voice mode's own strip, in the recording meter's clothes: the same row,
 * the same bars. While it listens the bars are the microphone's; while Ponos
 * thinks or speaks they move on their own, since there is no level to show. */
export function VoiceMeter({
  mode,
  levels,
  children,
}: {
  mode: "listening" | "thinking" | "speaking"
  levels: number[]
  children?: React.ReactNode
}) {
  const t = useT()
  const label = mode === "listening" ? t("Listening…") : mode === "thinking" ? t("Thinking…") : t("Speaking…")
  return (
    <div
      data-slot="voice-meter"
      data-mode={mode}
      className="bg-card flex h-12 items-center gap-3 rounded-3xl border px-4 shadow-sm"
      role="status"
      aria-live="polite"
    >
      {mode === "thinking" ? (
        <Loader2Icon className="text-muted-foreground size-3.5 shrink-0 animate-spin" />
      ) : (
        <span
          className={cn(
            "size-2.5 shrink-0 animate-pulse rounded-full",
            mode === "listening" ? "bg-destructive" : "bg-primary"
          )}
        />
      )}
      <span className="w-24 shrink-0 text-sm">{label}</span>
      <span className="flex h-7 flex-1 items-center justify-between gap-[2px] overflow-hidden" aria-hidden>
        {levels.map((level, index) => (
          <span
            key={index}
            className={cn(
              "bg-primary/80 w-[3px] max-w-[3px] min-w-px flex-1 rounded-full transition-[height] duration-75",
              mode === "speaking" && "animate-pulse"
            )}
            style={{
              height: `${mode === "listening" ? Math.max(12, level * 100) : mode === "speaking" ? 25 + ((index * 37) % 60) : 12}%`,
              animationDelay: mode === "speaking" ? `${(index % 8) * 90}ms` : undefined,
            }}
          />
        ))}
      </span>
      {children}
    </div>
  )
}
