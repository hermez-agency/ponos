import * as React from "react"
import { CheckIcon, PencilIcon, SendIcon, Trash2Icon, XIcon } from "lucide-react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { Queued } from "@/lib/types"

import { AttachedGallery } from "./attachments"

/* What was said while Ponos was still answering, and has not been sent.
 *
 * It sits at the end of the transcript, where the message will land, drawn the
 * way a message of yours is but pale and marked "waiting": the server holds the
 * list, so a reloaded page and a phone that opens the same conversation both
 * see it. Nothing here edits a list of its own — a click posts, and the new
 * list comes back on the stream.
 *
 * After a Stop (or a failure) the queue is not sent by itself: the turn that
 * ended was not the one you were waiting on, and the messages behind it may no
 * longer be what you want to say. A bar above them asks.
 */

async function attempt(action: () => Promise<unknown>, failed: string, done?: string) {
  try {
    await action()
    if (done) toast.success(done)
  } catch (error) {
    toast.error(failed, { description: why(error) })
  }
}

export function Waiting({ queue, held }: { queue: Queued[]; held: boolean }) {
  const t = useT()
  if (!queue.length) return null
  return (
    <div data-slot="queue" className="flex flex-col gap-2">
      {held ? (
        <div
          data-slot="queue-held"
          className="bg-muted flex flex-wrap items-center gap-2 rounded-lg px-3 py-2 text-sm"
        >
          <span className="flex-1">
            {queue.length === 1
              ? t("1 message is waiting. Send it, or throw it away?")
              : t("{{count}} messages are waiting. Send them, or throw them away?", {
                  count: String(queue.length),
                })}
          </span>
          <Button
            size="sm"
            onClick={() => void attempt(api.releaseQueue, t("The waiting messages could not be sent"))}
          >
            <SendIcon />
            {t("Send")}
          </Button>
          <ConfirmDialog
            title={
              queue.length === 1
                ? t("Throw the waiting message away?")
                : t("Throw the {{count}} waiting messages away?", { count: String(queue.length) })
            }
            description={t("They are not sent, and cannot be brought back.")}
            destructive
            confirm={
              <>
                <Trash2Icon />
                {t("Discard")}
              </>
            }
            onConfirm={() =>
              attempt(api.discardQueue, t("The waiting messages could not be discarded"), t("Messages discarded"))
            }
            trigger={
              <Button size="sm" variant="outline">
                <Trash2Icon />
                {t("Discard")}
              </Button>
            }
          />
        </div>
      ) : null}
      {queue.map((item) => (
        <Pending key={item.id} item={item} />
      ))}
    </div>
  )
}

function Pending({ item }: { item: Queued }) {
  const t = useT()
  const [editing, setEditing] = React.useState(false)
  const [text, setText] = React.useState(item.text)

  const save = async () => {
    await attempt(() => api.amend(item.id, text), t("The waiting message could not be changed"))
    setEditing(false)
  }

  return (
    <div data-slot="queued" className="flex flex-col items-end gap-1">
      <div className="text-muted-foreground font-mono text-[0.65rem] font-semibold tracking-[0.14em] uppercase">
        {t("waiting")}
      </div>
      {item.attachments?.length ? <AttachedGallery items={item.attachments} align="end" /> : null}
      {editing ? (
        <div className="flex w-full max-w-[92%] flex-col gap-1.5">
          <textarea
            value={text}
            rows={2}
            autoFocus
            aria-label={t("Edit the waiting message")}
            className="bg-background scroll-thin max-h-48 w-full resize-y rounded-lg border px-3 py-2 text-[0.9375rem] leading-6 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/30"
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.stopPropagation()
                setEditing(false)
              } else if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                void save()
              }
            }}
          />
          <div className="flex justify-end gap-1">
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              <XIcon />
              {t("Cancel")}
            </Button>
            <Button size="sm" disabled={!text.trim() && !item.attachments?.length} onClick={() => void save()}>
              <CheckIcon />
              {t("Save")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex max-w-[92%] items-start gap-1">
          <div className="border-primary/30 text-foreground/70 min-w-0 rounded-2xl border border-dashed px-3 py-2 text-[0.9375rem] leading-6 break-words whitespace-pre-wrap">
            {item.text}
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground shrink-0 rounded-full"
            aria-label={t("Edit the waiting message")}
            onClick={() => {
              setText(item.text)
              setEditing(true)
            }}
          >
            <PencilIcon />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground shrink-0 rounded-full"
            aria-label={t("Remove the waiting message")}
            onClick={() => void attempt(() => api.unqueue(item.id), t("The waiting message could not be removed"))}
          >
            <Trash2Icon />
          </Button>
        </div>
      )}
    </div>
  )
}
