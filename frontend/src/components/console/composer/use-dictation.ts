import * as React from "react"
import { toast } from "sonner"

import { useRecorder } from "@/hooks/use-recorder"
import { why } from "@/lib/api"
import { isTalkKey, micRefusal } from "@/lib/composer"
import { useT } from "@/lib/i18n"

/* The voice of a message bar: record, transcribe, and hand the words back.
 *
 * What becomes of the words is the bar's — `onHeard` — since only it knows
 * what is already typed and whether to send at once.
 */

export interface Dictation {
  ready: boolean
  why: string
  /** Send as soon as the transcription is back, rather than leave it to be read. */
  send: boolean
}

export function useDictation({
  transcribe,
  dictation,
  onHeard,
}: {
  transcribe?: (audio: Blob) => Promise<string>
  dictation?: Dictation
  onHeard: (said: string) => Promise<void>
}) {
  const t = useT()
  const recorder = useRecorder()
  const [transcribing, setTranscribing] = React.useState(false)
  const recording = recorder.state !== "idle"

  const refusal = micRefusal(Boolean(dictation?.ready), recorder.access)
  const blocked =
    refusal === "dictation"
      ? t(dictation?.why || "Dictation is not available")
      : refusal === "unsupported"
        ? t("This browser gives the page no microphone")
        : refusal === "denied"
          ? t("The microphone is blocked for this page — allow it in the browser's site settings")
          : ""

  const listen = async () => {
    if (blocked || !transcribe) return
    try {
      await recorder.start()
    } catch (error) {
      toast.error(t("The microphone could not be opened"), { description: why(error) })
    }
  }

  const finish = async () => {
    const audio = await recorder.stop()
    if (!audio || !transcribe) return
    setTranscribing(true)
    try {
      const said = await transcribe(audio)
      if (!said.trim()) {
        toast.message(t("Nothing was heard"))
        return
      }
      await onHeard(said)
    } catch (error) {
      toast.error(t("The recording could not be transcribed"), { description: why(error) })
    } finally {
      setTranscribing(false)
    }
  }

  // The keyboard way to talk, and Escape to throw a recording away — caught
  // before the drawer hears it, which would close itself instead.
  const latest = React.useRef({ listen, finish, cancel: recorder.cancel, recording })
  latest.current = { listen, finish, cancel: recorder.cancel, recording }
  React.useEffect(() => {
    if (!transcribe) return
    const listener = (event: KeyboardEvent) => {
      if (isTalkKey(event)) {
        event.preventDefault()
        if (latest.current.recording) void latest.current.finish()
        else void latest.current.listen()
      } else if (event.key === "Escape" && latest.current.recording) {
        event.preventDefault()
        event.stopPropagation()
        latest.current.cancel()
      }
    }
    window.addEventListener("keydown", listener, true)
    return () => window.removeEventListener("keydown", listener, true)
  }, [transcribe])

  return { recorder, recording, transcribing, blocked, listen, finish }
}
