import * as React from "react"
import {
  ArrowUpIcon,
  Loader2Icon,
  MicIcon,
  MicOffIcon,
  PlusIcon,
  SquareIcon,
  TerminalIcon,
  XIcon,
} from "lucide-react"
import { toast } from "sonner"

import { AttachmentGroup } from "@/components/ui/attachment"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useRecorder } from "@/hooks/use-recorder"
import { why } from "@/lib/api"
import {
  ACCEPT_ATTRIBUTE,
  canSend,
  clock,
  completed,
  completions,
  inserted,
  isCommand,
  kindOf,
  nameFor,
  pastedFiles,
  screen,
  settled,
  stopsOnEscape,
  withAdded,
  without,
  type Pending,
} from "@/lib/composer"
import { useT } from "@/lib/i18n"
import type { Attached } from "@/lib/types"
import { cn } from "@/lib/utils"

import { PendingTile } from "./attachments"

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
 * Files are uploaded the moment they are added, not when the message goes: a
 * video takes a while, and the time to take it is the time spent writing the
 * sentence that comes with it.
 */

/** Alt+Shift+M: the microphone, the way Alt+Shift+F is the full screen. */
const isTalkKey = (event: KeyboardEvent) =>
  event.altKey && event.shiftKey && !event.ctrlKey && !event.metaKey && event.code === "KeyM"

/** About eight lines of the field, past which it scrolls instead of growing. */
const TALLEST = 200

export interface ComposerHandle {
  /** Files handed in from outside the bar — dropped on the drawer around it. */
  add: (files: File[]) => void
  /** Back to the field — after a stop, say. */
  focus: () => void
}

export interface Dictation {
  ready: boolean
  why: string
  /** Send as soon as the transcription is back, rather than leave it to be read. */
  send: boolean
}

let counter = 0

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
}: {
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
}) {
  const t = useT()
  const [text, setText] = React.useState("")
  const [pending, setPending] = React.useState<Pending[]>([])
  const [sending, setSending] = React.useState(false)
  const [transcribing, setTranscribing] = React.useState(false)
  const [choice, setChoice] = React.useState(0)
  const [menuClosed, setMenuClosed] = React.useState(false)
  const field = React.useRef<HTMLTextAreaElement>(null)
  const picker = React.useRef<HTMLInputElement>(null)
  const kept = React.useRef(new Map<string, Attached>())
  // The list as it stands, for the callbacks that outlive the render they were
  // made in: an upload that ends, the page that closes.
  const current = React.useRef(pending)
  current.current = pending
  const recorder = useRecorder()

  const command = commands !== undefined && isCommand(text)
  const offered = commands && !menuClosed ? completions(text, commands) : []
  const ready = canSend({ text, attachments: pending, busy, sending })
  const recording = recorder.state !== "idle"

  /* -- the field grows with what is written, up to a point ----------------- */

  React.useLayoutEffect(() => {
    const element = field.current
    if (!element) return
    element.style.height = "auto"
    element.style.height = `${Math.min(element.scrollHeight, TALLEST)}px`
  }, [text, recording])

  React.useEffect(() => setChoice(0), [text])

  /* -- files ---------------------------------------------------------------- */

  const add = React.useCallback(
    (files: File[], pasted = false) => {
      if (!upload || !files.length) return
      const { taken, refused } = screen(files, limitMb)
      for (const refusal of refused)
        toast.error(
          refusal.why === "size"
            ? t("“{{name}}” is over {{limit}} MB", { name: refusal.name, limit: String(limitMb) })
            : t("“{{name}}” is not a file the workspace can take", { name: refusal.name }),
          {
            description:
              refusal.why === "size"
                ? t("The limit is web.attachment_max_mb, in the settings.")
                : t("Images (png, jpg, webp, gif), videos (mp4, webm, mov) and documents (pdf, txt, md, csv, json, docx, xlsx)."),
          }
        )
      const added: Pending[] = taken.map((file) => {
        const kind = kindOf(file) ?? "document"
        return {
          key: `file-${++counter}`,
          name: nameFor(file, pasted),
          kind,
          size: file.size,
          state: "uploading",
          preview: kind === "document" ? undefined : URL.createObjectURL(file),
        }
      })
      setPending((list) => withAdded(list, added))
      added.forEach((item, index) => {
        upload(taken[index], item.name)
          .then((attached) => {
            // Removed while it was on its way: the server's copy goes too.
            if (!current.current.some((entry) => entry.key === item.key)) {
              discard?.(attached.id)
              return
            }
            kept.current.set(item.key, attached)
            setPending((list) => settled(list, item.key, { state: "done", id: attached.id }))
          })
          .catch((error) => {
            setPending((list) => settled(list, item.key, { state: "error", error: why(error) }))
            toast.error(t("“{{name}}” could not be attached", { name: item.name }), {
              description: why(error),
            })
          })
      })
    },
    [upload, discard, limitMb, t]
  )

  React.useImperativeHandle(ref, () => ({ add, focus: () => field.current?.focus() }), [add])

  const remove = (item: Pending) => {
    if (item.preview) URL.revokeObjectURL(item.preview)
    if (item.id) discard?.(item.id)
    kept.current.delete(item.key)
    setPending((list) => without(list, item.key))
  }

  // The previews are object URLs, which the page keeps until told otherwise.
  React.useEffect(
    () => () => current.current.forEach((item) => item.preview && URL.revokeObjectURL(item.preview)),
    []
  )

  /* -- sending -------------------------------------------------------------- */

  const send = async (words = text) => {
    if (!canSend({ text: words, attachments: pending, busy, sending })) return
    const carried = isCommand(words)
      ? []
      : pending.flatMap((item) => {
          const attached = item.state === "done" ? kept.current.get(item.key) : undefined
          return attached ? [attached] : []
        })
    setSending(true)
    try {
      if (await onSend(words, carried)) {
        setText((current) => (current === words ? "" : current))
        if (!isCommand(words)) {
          pending.forEach((item) => item.preview && URL.revokeObjectURL(item.preview))
          kept.current.clear()
          setPending([])
        }
      }
    } finally {
      setSending(false)
      field.current?.focus()
    }
  }

  /* -- the voice ------------------------------------------------------------ */

  const micBlocked =
    !dictation?.ready
      ? t(dictation?.why || "Dictation is not available")
      : recorder.access === "unsupported"
        ? t("This browser gives the page no microphone")
        : recorder.access === "denied"
          ? t("The microphone is blocked for this page — allow it in the browser's site settings")
          : ""

  const listen = async () => {
    if (micBlocked || !transcribe) return
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
      const next = inserted(text, said)
      setText(next)
      if (dictation?.send) await send(next)
      else field.current?.focus()
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

  /* Escape from an empty field stops the turn. Caught on the window before
   * anything else, like the recording's Escape: the drawer listens for it on
   * the document, and would close itself on a key that meant "stop". */
  const stopper = React.useRef({ onStop, text, pending, busy })
  stopper.current = { onStop, text, pending, busy }
  React.useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.target !== field.current) return
      const now = stopper.current
      const stop = now.onStop
      if (!stop || !stopsOnEscape({ ...now, attachments: now.pending, stoppable: true })) return
      event.preventDefault()
      event.stopPropagation()
      stop()
    }
    window.addEventListener("keydown", listener, true)
    return () => window.removeEventListener("keydown", listener, true)
  }, [])

  /* -- drawing -------------------------------------------------------------- */

  const micLabel = `${t("Dictate")} (Alt+Shift+M)`

  return (
    <div className={cn("relative mx-auto w-full max-w-3xl", className)}>
      {offered.length ? (
        <div
          role="listbox"
          aria-label={t("Commands")}
          className="bg-popover text-popover-foreground absolute inset-x-0 bottom-full z-20 mb-2 max-h-64 overflow-auto rounded-xl border p-1 shadow-md"
        >
          {offered.map((verb, index) => (
            <button
              key={verb}
              type="button"
              role="option"
              aria-selected={index === choice}
              className={cn(
                "flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left font-mono text-sm",
                index === choice ? "bg-accent text-accent-foreground" : "hover:bg-muted"
              )}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                setText(completed(verb))
                field.current?.focus()
              }}
            >
              <TerminalIcon className="text-muted-foreground size-3.5" />
              <span className="text-tr-amber">&gt;</span>
              {verb}
            </button>
          ))}
        </div>
      ) : null}

      <div
        data-slot="composer"
        data-command={command || undefined}
        className={cn(
          "bg-card flex flex-col rounded-3xl border shadow-sm transition-[border-color,box-shadow]",
          "focus-within:border-ring/60 focus-within:ring-ring/20 focus-within:ring-[3px]",
          recording && "border-destructive/40"
        )}
      >
        {/* Room above and to the right for the crosses, which sit on the
            corners and a scrolling row would otherwise cut. */}
        {pending.length ? (
          <AttachmentGroup className="px-3 pt-4 pr-4 pb-0.5">
            {pending.map((item) => (
              <PendingTile key={item.key} item={item} onRemove={() => remove(item)} />
            ))}
          </AttachmentGroup>
        ) : null}

        {recording ? (
          <div className="flex h-12 items-center gap-3 px-4 pt-2" aria-live="polite">
            <span className="bg-destructive size-2.5 shrink-0 animate-pulse rounded-full" />
            <span className="font-mono text-sm tabular-nums">{clock(recorder.seconds)}</span>
            <span className="flex h-7 flex-1 items-center justify-between gap-[2px] overflow-hidden" aria-hidden>
              {recorder.levels.map((level, index) => (
                <span
                  key={index}
                  className="bg-primary/80 w-[3px] max-w-[3px] min-w-px flex-1 rounded-full transition-[height] duration-75"
                  style={{ height: `${Math.max(12, level * 100)}%` }}
                />
              ))}
            </span>
            <span className="sr-only">{t("Recording")}</span>
          </div>
        ) : (
          <div className="flex items-start gap-2 px-4 pt-3">
            {command ? (
              <span className="bg-tr-amber/10 text-tr-amber mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[0.65rem] font-semibold tracking-wider uppercase">
                <TerminalIcon className="size-3" />
                {t("command")}
              </span>
            ) : null}
            <textarea
              ref={field}
              value={text}
              rows={1}
              spellCheck={!command}
              autoComplete="off"
              aria-label={placeholder}
              placeholder={transcribing ? t("Transcribing…") : placeholder}
              disabled={transcribing}
              onChange={(event) => {
                setText(event.target.value)
                setMenuClosed(false)
              }}
              onPaste={(event) => {
                const files = pastedFiles(event.clipboardData)
                if (!files.length || !upload) return
                // A capture carries no text worth pasting; a copied file may
                // carry its name, which is not what was meant either.
                event.preventDefault()
                add(files, true)
              }}
              onKeyDown={(event) => {
                if (offered.length) {
                  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                    event.preventDefault()
                    const step = event.key === "ArrowDown" ? 1 : -1
                    setChoice((current) => (current + step + offered.length) % offered.length)
                    return
                  }
                  if (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey)) {
                    event.preventDefault()
                    setText(completed(offered[choice] ?? offered[0]))
                    return
                  }
                  if (event.key === "Escape") {
                    event.preventDefault()
                    event.stopPropagation()
                    setMenuClosed(true)
                    return
                  }
                }
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault()
                  void send()
                }
              }}
              className={cn(
                "placeholder:text-muted-foreground max-h-[200px] min-h-6 w-full flex-1 resize-none bg-transparent text-[0.9375rem] leading-6 outline-none disabled:opacity-60",
                "scroll-thin",
                command && "text-tr-amber font-mono text-sm"
              )}
            />
          </div>
        )}

        <div className="flex items-center gap-1 px-2 pt-1 pb-2">
          {upload ? (
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="text-muted-foreground rounded-full"
                    aria-label={t("Attach a file")}
                    disabled={recording}
                    onClick={() => picker.current?.click()}
                  >
                    <PlusIcon className="size-5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top">
                  {t("Attach a photo, a video or a document — or drop it, or paste it")}
                </TooltipContent>
              </Tooltip>
              <input
                ref={picker}
                type="file"
                multiple
                hidden
                accept={ACCEPT_ATTRIBUTE}
                onChange={(event) => {
                  add(Array.from(event.target.files ?? []))
                  event.target.value = ""
                }}
              />
            </>
          ) : null}
          {tools}
          <span className="flex-1" />

          {recording ? (
            <>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="rounded-full"
                onClick={recorder.cancel}
              >
                <XIcon />
                {t("Cancel")}
              </Button>
              <Button
                type="button"
                size="sm"
                className="rounded-full"
                disabled={recorder.state !== "recording"}
                onClick={() => void finish()}
              >
                <SquareIcon className="fill-current" />
                {t("Stop")}
              </Button>
            </>
          ) : (
            <>
              {transcribe ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    {/* A span around it, because a disabled button says nothing
                        on hover — and the reason is the point of greying it. */}
                    <span tabIndex={micBlocked ? 0 : -1} className="inline-flex rounded-full">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        className="text-muted-foreground rounded-full"
                        aria-label={micBlocked || micLabel}
                        disabled={Boolean(micBlocked) || transcribing}
                        onClick={() => void listen()}
                      >
                        {transcribing ? (
                          <Loader2Icon className="animate-spin" />
                        ) : micBlocked ? (
                          <MicOffIcon />
                        ) : (
                          <MicIcon />
                        )}
                      </Button>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-64">
                    {micBlocked || `${t("Dictate")} · Alt+Shift+M`}
                  </TooltipContent>
                </Tooltip>
              ) : null}
              {busy && onStop ? (
                /* Beside the arrow and not in its place: Ponos can be told
                   something more while it works, and Stop stays where it was
                   pressed. Pressed twice, it was pressed once: the second click
                   lands on a button already saying it is stopping. */
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
                      {stopping ? (
                        <Loader2Icon className="animate-spin" />
                      ) : (
                        <SquareIcon className="size-3.5 fill-current" />
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    {stopping ? t("Stopping…") : `${t("Stop")} · Esc`}
                  </TooltipContent>
                </Tooltip>
              ) : null}
              <Button
                type="button"
                size="icon-sm"
                data-slot="composer-send"
                data-busy={busy || undefined}
                className="rounded-full"
                aria-label={t("Send")}
                title={busy && !command ? t("Send — it waits for Ponos to finish") : t("Send")}
                disabled={!ready}
                onClick={() => void send()}
              >
                {sending ? <Loader2Icon className="animate-spin" /> : <ArrowUpIcon className="size-4.5" />}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
