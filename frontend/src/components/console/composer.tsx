import * as React from "react"

import { canSend, completed, inserted, isCommand, pastedFiles } from "@/lib/composer"
import { useT } from "@/lib/i18n"
import type { Attached } from "@/lib/types"
import { cn } from "@/lib/utils"

import { AttachButton, AttachmentStrip } from "./composer/attachment-strip"
import { MicButton, RecordingButtons, SendButton, StopButton } from "./composer/buttons"
import { CommandMenu, useCommands } from "./composer/command-menu"
import { Field } from "./composer/field"
import { RecordingMeter } from "./composer/recording-meter"
import { useAttachments } from "./composer/use-attachments"
import { useDictation, type Dictation } from "./composer/use-dictation"
import { useStopOnEscape } from "./composer/use-stop-on-escape"

export type { Dictation }

/* The bar a message is written in — one block, everything it can carry inside.
 *
 * It used to be a form: a field, a row of buttons under it, a line of help
 * under that. A conversation bar is one rounded block that the words, the
 * files and the voice all go into, with the gestures on its lower edge — a +
 * to attach on the left, the microphone and a round arrow on the right. Those
 * are where everybody who has used a chat application looks for them.
 *
 * What it can do depends on what it is given, which is what makes it reusable:
 * no `upload`, no +; no `transcribe`, no microphone; no `commands`, no `>` mode.
 * A ticket's thread can take it as it is and offer only the words.
 *
 * Each of these is its own part, under `composer/`: the files
 * (`use-attachments`, `attachment-strip`), the voice (`use-dictation`,
 * `recording-meter`), the `>` mode (`command-menu`) and the buttons. What is
 * left here is the field, and what binds them to it.
 */

/** About eight lines of the field, past which it scrolls instead of growing. */
const TALLEST = 200

export interface ComposerHandle {
  /** Files handed in from outside the bar — dropped on the drawer around it. */
  add: (files: File[]) => void
  /** Back to the field — after a stop, say. */
  focus: () => void
}

export interface ComposerProps {
  ref?: React.Ref<ComposerHandle>
  /** Says whether the message was taken, so the bar is emptied only then. */
  onSend: (text: string, attachments: Attached[]) => Promise<boolean>
  /** Given while there is something to stop: the arrow becomes Stop, and Escape presses it. */
  onStop?: () => void
  /** Stop was pressed; the end of the turn is on its way. */
  stopping?: boolean
  busy: boolean
  placeholder: string
  commands?: string[]
  upload?: (file: File, name: string) => Promise<Attached>
  discard?: (id: string) => void
  limitMb?: number
  transcribe?: (audio: Blob) => Promise<string>
  dictation?: Dictation
  /** What else the bar holds, beside the + : a ticket's model, chosen for the session its answer starts. */
  tools?: React.ReactNode
  className?: string
}

export function Composer({
  ref,
  onSend,
  onStop,
  stopping = false,
  busy,
  placeholder,
  commands,
  upload,
  discard,
  limitMb = 25,
  transcribe,
  dictation,
  tools,
  className,
}: ComposerProps) {
  const t = useT()
  const [text, setText] = React.useState("")
  const [sending, setSending] = React.useState(false)
  const field = React.useRef<HTMLTextAreaElement>(null)
  const files = useAttachments({ upload, discard, limitMb })
  const { pending } = files
  const menu = useCommands(text, setText, commands)
  const ready = canSend({ text, attachments: pending, busy, sending })

  const send = async (words = text) => {
    if (!canSend({ text: words, attachments: pending, busy, sending })) return
    const carried = files.carriedWith(words)
    setSending(true)
    try {
      if (await onSend(words, carried)) {
        setText((current) => (current === words ? "" : current))
        if (!isCommand(words)) files.clear(pending)
      }
    } finally {
      setSending(false)
      field.current?.focus()
    }
  }

  const voice = useDictation({
    transcribe,
    dictation,
    onHeard: async (said) => {
      const next = inserted(text, said)
      setText(next)
      if (dictation?.send) await send(next)
      else field.current?.focus()
    },
  })
  const { recorder, recording, transcribing } = voice

  useStopOnEscape(field, { onStop, text, pending, busy })

  React.useImperativeHandle(ref, () => ({ add: files.add, focus: () => field.current?.focus() }), [files.add])

  // The field grows with what is written, up to a point.
  React.useLayoutEffect(() => {
    const element = field.current
    if (!element) return
    element.style.height = "auto"
    element.style.height = `${Math.min(element.scrollHeight, TALLEST)}px`
  }, [text, recording])

  const { command } = menu

  return (
    <div className={cn("relative mx-auto w-full max-w-3xl", className)}>
      <CommandMenu
        offered={menu.offered}
        choice={menu.choice}
        onPick={(verb) => {
          setText(completed(verb))
          field.current?.focus()
        }}
      />

      <div
        data-slot="composer"
        data-command={command || undefined}
        className={cn(
          "bg-card flex flex-col rounded-3xl border shadow-sm transition-[border-color,box-shadow]",
          "focus-within:border-ring/60 focus-within:ring-ring/20 focus-within:ring-[3px]",
          recording && "border-destructive/40"
        )}
      >
        <AttachmentStrip pending={pending} onRemove={files.remove} />

        {recording ? (
          <RecordingMeter seconds={recorder.seconds} levels={recorder.levels} />
        ) : (
          <Field
            ref={field}
            value={text}
            command={command}
            aria-label={placeholder}
            placeholder={transcribing ? t("Transcribing…") : placeholder}
            disabled={transcribing}
            onChange={(event) => {
              setText(event.target.value)
              menu.reopen()
            }}
            onPaste={(event) => {
              const pasted = pastedFiles(event.clipboardData)
              if (!pasted.length || !upload) return
              // A capture carries no text worth pasting; a copied file may
              // carry its name, which is not what was meant either.
              event.preventDefault()
              files.add(pasted, true)
            }}
            onKeyDown={(event) => {
              if (menu.onKey(event)) return
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                void send()
              }
            }}
          />
        )}

        <div className="flex items-center gap-1 px-2 pt-1 pb-2">
          {upload ? <AttachButton disabled={recording} onFiles={files.add} /> : null}
          {tools}
          <span className="flex-1" />

          {recording ? (
            <RecordingButtons
              canStop={recorder.state === "recording"}
              onCancel={recorder.cancel}
              onFinish={() => void voice.finish()}
            />
          ) : (
            <>
              {transcribe ? (
                <MicButton blocked={voice.blocked} transcribing={transcribing} onListen={() => void voice.listen()} />
              ) : null}
              {busy && onStop ? <StopButton stopping={stopping} onStop={onStop} /> : null}
              <SendButton busy={busy} command={command} ready={ready} sending={sending} onSend={() => void send()} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
