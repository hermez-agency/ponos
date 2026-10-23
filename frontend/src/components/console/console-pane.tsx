import * as React from "react"
import { useChat, type UIMessage } from "@tanstack/ai-react"
import { PaperclipIcon, SquarePenIcon } from "lucide-react"

import { ChatConversation } from "@/components/chat/chat-conversation"
import { ChatMessage } from "@/components/chat/chat-message"
import type { ChatMessageData } from "@/components/chat/chat-types"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useConsole, type Entry } from "@/hooks/use-console"
import { hotkeyLabel, useHotkeys } from "@/hooks/use-hotkeys"
import { connection, ponosOf } from "@/lib/agui"
import { api, why } from "@/lib/api"
import { clock } from "@/lib/composer"
import { currentLanguage, useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import type { Attached } from "@/lib/types"
import { settingsHref } from "@/resources/settings"

import { AttachedGallery } from "./attachments"
import { Composer, type ComposerHandle } from "./composer"
import { ModelPicker } from "./model-picker"
import { Waiting } from "./queued"
import { Robot } from "./robot"
import { TalkHistory } from "./talk-history"
import { Flow } from "./text"
import { Turn } from "./turn"

/* A sentence talks to your workspace; a line that starts with `>` runs a
 * ponos command. Both land in the same transcript, because both are
 * things you did to the same machine — and a sentence can carry what you would
 * otherwise have had to describe: a screenshot, a PDF, a clip, your voice.
 *
 * The conversation is TanStack AI's `useChat`, on the server's AG-UI door
 * (`lib/agui.ts`), and drawn by Brand Assets' chat components: what Ponos
 * says, thinks and does arrives part by part — its words, each tool it calls
 * and what the tool answered — and is kept that way, so a conversation reopened
 * from the history reads as it was watched. The commands and the problems met
 * on the way are this page's own (`use-console`), drawn among the messages by
 * the time they were said.
 *
 * The files can arrive three ways, and the drawer takes all three: the + of the
 * bar, a paste, and a drop anywhere on the drawer — which is why the drop zone
 * is here and not in the bar, a strip too thin to aim a file at. */

/* One literal rather than two joined: it is also the key it is looked up by,
 * and a key nobody can search for is a key nobody translates. */
const WELCOME =
  "Ask me anything about your workspace — I can read your repositories, look at the board and create tickets. Type > followed by a command (>status, >list, >doctor) to use the CLI directly."

const upload = (file: File, name: string) => api.attach(file, name)
const discard = (id: string) => void api.detach(id).catch(() => {})
// The page's own language: what the person talking is reading, and so the
// likeliest one they are speaking. The server prefers `runner.language`.
const transcribe = async (audio: Blob) => (await api.transcribe(audio, currentLanguage())).text

const carriesFiles = (event: React.DragEvent) => event.dataTransfer.types.includes("Files")

export function ConsolePane() {
  const { busy, resetChat, runner, reloadState } = useConsole()
  const t = useT()
  const composer = React.useRef<ComposerHandle>(null)
  // A turn in flight is not interrupted by a new conversation: the button is
  // disabled then, and so is the shortcut.
  const startOver = React.useCallback(async () => {
    if (busy) return
    await resetChat()
    composer.current?.focus()
  }, [busy, resetChat])
  useHotkeys({ newChat: () => void startOver() })
  const shortcut = hotkeyLabel("newChat")
  const [dragging, setDragging] = React.useState(false)
  const chat = runner?.chat

  return (
    <div
      className="relative flex min-h-0 flex-1 flex-col"
      onDragEnter={(event) => {
        if (!carriesFiles(event)) return
        event.preventDefault()
        setDragging(true)
      }}
      onDragOver={(event) => {
        if (!carriesFiles(event)) return
        event.preventDefault()
        event.dataTransfer.dropEffect = "copy"
      }}
      onDragLeave={(event) => {
        // Leaving for a child is not leaving the drawer.
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return
        setDragging(false)
      }}
      onDrop={(event) => {
        if (!carriesFiles(event)) return
        event.preventDefault()
        setDragging(false)
        composer.current?.add(Array.from(event.dataTransfer.files))
      }}
    >
      {/* Only what can be done from here: the drawer already says where it
          is. Room at the right for the drawer's own close and its full-screen
          switch, which float over this corner. Creating a ticket is the
          board's job; here Ponos makes one when asked. */}
      <div className="flex items-center gap-2 border-b py-2 pr-12 pl-3.5 sm:pr-20">
        <span
          className="text-muted-foreground min-w-0 flex-1 truncate text-sm font-medium"
          title={chat?.title || undefined}
        >
          {chat?.title || "Ponos"}
        </span>
        <ModelPicker
          model={chat?.model_in_use ?? ""}
          onChosen={() => void reloadState()}
          settingsTo={settingsHref("models")}
        />
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              className="opacity-70 hover:opacity-100"
              aria-label={t("Start a new conversation")}
              disabled={busy}
              aria-keyshortcuts={shortcut.aria}
              onClick={() => void startOver()}
              data-new-chat
            >
              <SquarePenIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">{`${t("Start a new conversation")} · ${shortcut.label}`}</TooltipContent>
        </Tooltip>
        <TalkHistory disabled={busy} />
      </div>

      {/* One `useChat` per conversation: opening another one from the history,
          or starting a new one, hydrates a fresh one from the server. */}
      {chat?.id ? <Talk key={chat.id} threadId={chat.id} composer={composer} /> : <div className="flex-1" />}

      {dragging ? (
        <div className="bg-background/80 pointer-events-none absolute inset-2 z-30 grid place-items-center rounded-2xl border-2 border-dashed border-primary backdrop-blur-sm">
          <div className="flex flex-col items-center gap-2 text-center">
            <PaperclipIcon className="text-primary size-8" />
            <p className="text-sm font-semibold">{t("Drop to attach to your message")}</p>
            <p className="text-muted-foreground text-xs">
              {t("Photos, videos and documents, up to {{limit}} MB each", {
                limit: String(chat?.attachments?.max_mb ?? 25),
              })}
            </p>
          </div>
        </div>
      ) : null}
    </div>
  )
}

/* The conversation and its message bar: `useChat`, and what is drawn of it. */
function Talk({
  threadId,
  composer,
}: {
  threadId: string
  composer: React.RefObject<ComposerHandle | null>
}) {
  const { transcript, busy, stopping, queue, held, submit, stopChat, runner, say } = useConsole()
  const t = useT()
  const chat = runner?.chat
  const { messages, sendMessage } = useChat({
    connection,
    threadId,
    persistence: true,
    live: true,
    onError: (error) => say("error", why(error)),
  })

  /* Back to the field once a stop has landed — in the tab that pressed it:
   * whoever pressed Stop was about to say what they meant instead. */
  const stoppedHere = React.useRef(false)
  const stop = React.useCallback(() => {
    stoppedHere.current = true
    void stopChat()
  }, [stopChat])
  React.useEffect(() => {
    if (busy || !stoppedHere.current) return
    stoppedHere.current = false
    composer.current?.focus()
  }, [busy, composer])

  /* Said now, through `useChat`, when nothing else is: its message appears at
   * once and the turn streams under it. A command, a message while Ponos is
   * still answering, and files without words go the way they always went —
   * the server's queue is where a message waits, so every tab sees it wait. */
  const send = React.useCallback(
    async (text: string, attachments: Attached[] = []) => {
      const line = text.trim()
      if (!line || line.startsWith(">") || busy || queue.length) return submit(text, attachments)
      // Not waited for: it settles when the turn ends, and the field is free
      // as soon as the message has left. A refusal is said by `onError`.
      sendMessage(line, { body: { attachments: attachments.map((item) => item.id) } }).catch(
        () => {}
      )
      return true
    },
    [busy, queue.length, submit, sendMessage]
  )

  const said = React.useMemo(() => interleaved(messages, transcript), [messages, transcript])
  const last = messages[messages.length - 1]
  const answering = busy && !transcript.some((entry) => entry.kind === "command" && entry.code === null)

  return (
    <>
      <ChatConversation
        empty={<Turn role="workspace" text={t(WELCOME)} />}
      >
        {said.map((item) =>
          "parts" in item ? (
            <Said
              key={item.id}
              message={item}
              streaming={answering && item === last && item.role === "assistant"}
            />
          ) : (
            <Local key={`local-${item.id}`} entry={item} />
          )
        )}
        {answering ? <Working stopping={stopping} /> : null}
        {queue.length ? <Waiting queue={queue} held={held} /> : null}
      </ChatConversation>

      <div className="px-3 pt-1 pb-3">
        <Composer
          ref={composer}
          busy={busy}
          onSend={send}
          onStop={answering ? stop : undefined}
          stopping={stopping}
          placeholder={t("Ask the workspace, or type >status")}
          commands={runner?.commands ?? []}
          upload={upload}
          discard={discard}
          limitMb={chat?.attachments?.max_mb ?? 25}
          transcribe={transcribe}
          dictation={
            chat?.dictation ?? { ready: false, why: t("Dictation is not available"), send: false }
          }
        />
      </div>
    </>
  )
}

/* The messages and this page's own entries, in the order they were said.
 *
 * A message carries the time it was said (the server's, or the page's for one
 * just sent); an entry the time this page saw it. A message without one takes
 * the time of the one before it, so the conversation is never reordered. */
function interleaved(messages: ReadonlyArray<UIMessage>, entries: Entry[]): (UIMessage | Entry)[] {
  let previous = 0
  const timed = messages.map((message) => {
    const at = message.createdAt ? new Date(message.createdAt).getTime() : NaN
    previous = Number.isFinite(at) ? Math.max(at, previous) : previous
    return { at: previous, item: message as UIMessage | Entry }
  })
  const merged = [...timed]
  for (const entry of entries) {
    const index = merged.findIndex((other) => other.at > entry.at)
    merged.splice(index < 0 ? merged.length : index, 0, { at: entry.at, item: entry })
  }
  return merged.map((one) => one.item)
}

/* One message of the conversation: Brand Assets' `ChatMessage`, with what
 * Ponos adds around it — its name and face over what it says, the files over
 * what you said, and under a turn how long it took and what it cost, or that
 * it was stopped, or what went wrong. */
const Said = React.memo(function Said({
  message,
  streaming,
}: {
  message: UIMessage
  streaming: boolean
}) {
  const t = useT()
  const ponos = ponosOf(message)
  if (message.role !== "user" && message.role !== "assistant") return null
  const drawn = message as unknown as ChatMessageData
  const words = message.parts.length > 0

  if (message.role === "user")
    return (
      <div data-slot="said" data-role="you" className="flex flex-col items-end gap-1.5">
        {ponos.attachments?.length ? (
          <AttachedGallery items={ponos.attachments as Attached[]} align="end" />
        ) : null}
        {words ? <ChatMessage message={drawn} /> : null}
      </div>
    )

  const footer = [
    ponos.role === "stopped" ? t("stopped by you") : "",
    ponos.seconds !== undefined ? clock(ponos.seconds) : "",
    ponos.cost ? money(ponos.cost, 4) : "",
  ].filter(Boolean)

  return (
    <div data-slot="said" data-role={ponos.role ?? "workspace"} className="flex flex-col gap-2">
      <div className="text-muted-foreground flex items-center gap-1.5 font-mono text-[0.65rem] font-semibold tracking-[0.14em] uppercase">
        <span className="bg-muted flex size-6 shrink-0 items-center justify-center rounded-full">
          <Robot state="idle" size={18} still />
        </span>
        Ponos
      </div>
      {words ? <ChatMessage message={drawn} streaming={streaming} /> : null}
      {ponos.error ? (
        <p role="alert" className="border-destructive/40 bg-destructive/10 text-destructive rounded-xl border px-3 py-2 text-sm">
          {ponos.error}
        </p>
      ) : null}
      {footer.length ? (
        <p data-slot="said-footer" className="text-muted-foreground font-mono text-xs">
          {footer.join(" · ")}
        </p>
      ) : null}
    </div>
  )
})

/** Ponos at work, while a turn runs: what streams is above it. */
function Working({ stopping }: { stopping: boolean }) {
  const t = useT()
  return (
    <div data-slot="working" role="status" className="text-muted-foreground flex items-center gap-2 text-sm">
      <Robot state="thinking" size={36} className="shrink-0" />
      {stopping ? t("stopping…") : t("Ponos is working…")}
    </div>
  )
}

/* A command run from the bar, or a problem the page met: this page's own, and
 * never part of the conversation the server keeps. */
const Local = React.memo(function Local({ entry }: { entry: Entry }) {
  const t = useT()
  if (entry.kind === "turn") return <Turn role={entry.role} text={entry.text} />
  return (
    <div className="bg-card rounded-lg border px-3 py-2">
      <div className="text-muted-foreground mb-1 font-mono text-[0.7rem]">
        ponos {entry.argv.join(" ")}
      </div>
      <pre className="scroll-thin max-h-96 overflow-auto font-mono text-xs leading-relaxed whitespace-pre-wrap">
        {entry.lines.map((line, index) => (
          <React.Fragment key={index}>
            <Flow text={line} />
            {"\n"}
          </React.Fragment>
        ))}
        {entry.code ? `\n[${t("exit {{code}}", { code: String(entry.code) })}]` : ""}
      </pre>
    </div>
  )
})
