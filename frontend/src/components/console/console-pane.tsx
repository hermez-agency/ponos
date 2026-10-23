import * as React from "react"
import { PaperclipIcon, SquarePenIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useConsole, type Entry } from "@/hooks/use-console"
import { api } from "@/lib/api"
import { currentLanguage, useT } from "@/lib/i18n"
import { settingsHref } from "@/resources/settings"

import { Composer, type ComposerHandle } from "./composer"
import { ModelPicker } from "./model-picker"
import { Waiting } from "./queued"
import { Flow } from "./text"
import { Thinking } from "./thinking"
import { Line, Transcript } from "./transcript"
import { Turn } from "./turn"

/* A sentence talks to your workspace; a line that starts with `>` runs a
 * ponos command. Both land in the same transcript, because both are
 * things you did to the same machine — and a sentence can carry what you would
 * otherwise have had to describe: a screenshot, a PDF, a clip, your voice.
 *
 * The files can arrive three ways, and the drawer takes all three: the + of the
 * bar, a paste, and a drop anywhere on the drawer — which is why the drop zone
 * is here and not in the bar, a strip too thin to aim a file at. */

const upload = (file: File, name: string) => api.attach(file, name)
const discard = (id: string) => void api.detach(id).catch(() => {})
// The page's own language: what the person talking is reading, and so the
// likeliest one they are speaking. The server prefers `runner.language`.
const transcribe = async (audio: Blob) => (await api.transcribe(audio, currentLanguage())).text

const carriesFiles = (event: React.DragEvent) => event.dataTransfer.types.includes("Files")

export function ConsolePane() {
  const {
    transcript,
    busy,
    stopping,
    queue,
    held,
    submit,
    resetChat,
    stopChat,
    runner,
    reloadState,
  } = useConsole()
  const t = useT()
  const composer = React.useRef<ComposerHandle>(null)
  const [dragging, setDragging] = React.useState(false)
  const chat = runner?.chat
  // A turn of the workspace, and not a `>command`, is what Stop stops: the
  // last open block of steps is that turn.
  const answering = busy && transcript.some((entry) => entry.kind === "steps" && !entry.done)

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
  }, [busy])

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
              onClick={resetChat}
            >
              <SquarePenIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">{t("new conversation")}</TooltipContent>
        </Tooltip>
      </div>

      <Transcript>
        {transcript.map((entry) => (
          <Said key={entry.id} entry={entry} />
        ))}
        {queue.length ? (
          <Line id="queue">
            <Waiting queue={queue} held={held} />
          </Line>
        ) : null}
      </Transcript>

      <div className="px-3 pt-1 pb-3">
        <Composer
          ref={composer}
          busy={busy}
          onSend={submit}
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

/* One entry of the transcript, drawn again only when it changes.
 *
 * An entry is never edited in place: the stream replaces the one that grew — the
 * steps of the turn in progress, the lines of a running command — and hands the
 * others back as they were. So comparing the object is enough to know that the
 * thirty turns above the one being written have nothing new to say. */
const Said = React.memo(function Said({ entry }: { entry: Entry }) {
  const t = useT()
  const id = String(entry.id)
  if (entry.kind === "turn")
    return (
      <Line id={id} anchor={entry.role === "you"}>
        <Turn role={entry.role} text={entry.text} attachments={entry.attachments} />
      </Line>
    )
  if (entry.kind === "steps")
    return (
      <Line id={id}>
        <Thinking
          steps={entry.steps}
          done={entry.done}
          started={entry.started}
          seconds={entry.seconds}
          cost={entry.cost}
          stopping={entry.stopping}
        />
      </Line>
    )
  return (
    <Line id={id} anchor>
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
    </Line>
  )
})
