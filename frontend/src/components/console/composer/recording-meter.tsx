import { clock } from "@/lib/composer"
import { useT } from "@/lib/i18n"

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
