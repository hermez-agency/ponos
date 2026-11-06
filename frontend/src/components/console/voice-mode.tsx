import { AudioLinesIcon, SquareIcon, Volume2Icon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useT } from "@/lib/i18n"
import type { Mode } from "@/lib/voice-mode"

import { VoiceMeter } from "./composer/recording-meter"

/* The two ways in to the voice: the bar's Voice mode button, which holds the
 * conversation without the keyboard, and a Listen button under each answer
 * (`Said`), which reads that one answer. Both are greyed out with their reason
 * rather than hidden — a button that was not there says nothing about Piper. */

/** In the message bar, beside the +: pressed, the strip below takes over. */
export function VoiceModeButton({
  on,
  blocked,
  onToggle,
}: {
  on: boolean
  /** Why it is greyed out, or nothing. */
  blocked: string
  onToggle: () => void
}) {
  const t = useT()
  const label = on ? t("Leave voice mode") : t("Voice mode")
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={blocked ? 0 : -1} className="inline-flex rounded-full">
          <Button
            type="button"
            variant={on ? "default" : "ghost"}
            size="icon-sm"
            data-slot="voice-mode-button"
            data-on={on || undefined}
            className={on ? "rounded-full" : "text-muted-foreground rounded-full"}
            aria-label={blocked || label}
            aria-pressed={on}
            disabled={Boolean(blocked) && !on}
            onClick={onToggle}
          >
            <AudioLinesIcon />
          </Button>
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-64">
        {blocked || label}
      </TooltipContent>
    </Tooltip>
  )
}

/** The strip that stands over the bar while the mode is on: the state, and the two ways out. */
export function VoicePanel({
  mode,
  levels,
  onInterrupt,
  onLeave,
}: {
  mode: Exclude<Mode, "off">
  levels: number[]
  onInterrupt: () => void
  onLeave: () => void
}) {
  const t = useT()
  return (
    <VoiceMeter mode={mode} levels={levels}>
      {mode === "speaking" ? (
        <Button type="button" variant="outline" size="sm" className="rounded-full" onClick={onInterrupt}>
          <SquareIcon className="fill-current" />
          {t("Interrupt")}
        </Button>
      ) : null}
      <Button type="button" variant="ghost" size="sm" className="rounded-full" onClick={onLeave}>
        <XIcon />
        {t("Leave")}
      </Button>
    </VoiceMeter>
  )
}

/** Under an answer: read it aloud, or stop reading it. */
export function ListenButton({ active, onClick }: { active: boolean; onClick: () => void }) {
  const t = useT()
  const label = active ? t("Stop listening") : t("Listen")
  return (
    <Button
      type="button"
      variant="ghost"
      size="xs"
      data-slot="listen"
      className="text-muted-foreground -ml-2 w-fit rounded-full"
      aria-label={label}
      onClick={onClick}
    >
      {active ? <SquareIcon className="fill-current" /> : <Volume2Icon />}
      {label}
    </Button>
  )
}
