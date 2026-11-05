import { ArrowUpIcon, Loader2Icon, MicIcon, MicOffIcon, SquareIcon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useT } from "@/lib/i18n"

/* The gestures on the right of the bar's lower edge: the microphone, Stop and
 * the round arrow — or, while it records, Cancel and Stop the recording. */

export function RecordingButtons({
  canStop,
  onCancel,
  onFinish,
}: {
  canStop: boolean
  onCancel: () => void
  onFinish: () => void
}) {
  const t = useT()
  return (
    <>
      <Button type="button" variant="ghost" size="sm" className="rounded-full" onClick={onCancel}>
        <XIcon />
        {t("Cancel")}
      </Button>
      <Button type="button" size="sm" className="rounded-full" disabled={!canStop} onClick={onFinish}>
        <SquareIcon className="fill-current" />
        {t("Stop")}
      </Button>
    </>
  )
}

export function MicButton({
  blocked,
  transcribing,
  onListen,
}: {
  /** Why it is greyed out, or nothing. */
  blocked: string
  transcribing: boolean
  onListen: () => void
}) {
  const t = useT()
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {/* A span around it, because a disabled button says nothing
            on hover — and the reason is the point of greying it. */}
        <span tabIndex={blocked ? 0 : -1} className="inline-flex rounded-full">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground rounded-full"
            aria-label={blocked || `${t("Dictate")} (Alt+Shift+M)`}
            disabled={Boolean(blocked) || transcribing}
            onClick={onListen}
          >
            {transcribing ? <Loader2Icon className="animate-spin" /> : blocked ? <MicOffIcon /> : <MicIcon />}
          </Button>
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-64">
        {blocked || `${t("Dictate")} · Alt+Shift+M`}
      </TooltipContent>
    </Tooltip>
  )
}

/* Beside the arrow and not in its place: Ponos can be told something more
 * while it works, and Stop stays where it was pressed. Pressed twice, it was
 * pressed once: the second click lands on a button already saying it is
 * stopping. */
export function StopButton({ stopping, onStop }: { stopping: boolean; onStop: () => void }) {
  const t = useT()
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          size="icon-sm"
          variant="outline"
          data-slot="composer-stop"
          data-stopping={stopping || undefined}
          className="rounded-full"
          aria-label={stopping ? t("Stopping…") : t("Stop")}
          aria-keyshortcuts="Escape"
          disabled={stopping}
          onClick={onStop}
        >
          {stopping ? <Loader2Icon className="animate-spin" /> : <SquareIcon className="size-3.5 fill-current" />}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="top">{stopping ? t("Stopping…") : `${t("Stop")} · Esc`}</TooltipContent>
    </Tooltip>
  )
}

export function SendButton({
  busy,
  command,
  ready,
  sending,
  onSend,
}: {
  busy: boolean
  command: boolean
  ready: boolean
  sending: boolean
  onSend: () => void
}) {
  const t = useT()
  return (
    <Button
      type="button"
      size="icon-sm"
      data-slot="composer-send"
      data-busy={busy || undefined}
      className="rounded-full"
      aria-label={t("Send")}
      title={busy && !command ? t("Send — it waits for Ponos to finish") : t("Send")}
      disabled={!ready}
      onClick={onSend}
    >
      {sending ? <Loader2Icon className="animate-spin" /> : <ArrowUpIcon className="size-4.5" />}
    </Button>
  )
}
