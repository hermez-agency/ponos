import * as React from "react"
import { toast } from "sonner"
import {
  BookmarkPlusIcon,
  CheckIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
  FileIcon,
  FilmIcon,
  ImageIcon,
  Loader2Icon,
  TriangleAlertIcon,
  XIcon,
} from "lucide-react"

import {
  Attachment,
  AttachmentContent,
  AttachmentDescription,
  AttachmentGroup,
  AttachmentMedia,
  AttachmentTitle,
  AttachmentTrigger,
} from "@/components/ui/attachment"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { api, attachmentUrl, why } from "@/lib/api"
import { extensionOf, humanSize, type Pending } from "@/lib/composer"
import { useT } from "@/lib/i18n"
import { openChatId } from "@/lib/open-chat"
import type { Attached } from "@/lib/types"
import { cn } from "@/lib/utils"

/* What a message carries, drawn twice: in the bar while it is being written,
 * and in the transcript once it was said.
 *
 * An image or a video is a thumbnail — the picture itself, or the first frame
 * of the clip — because that is what one recognises it by; a document is a
 * chip with its icon, its name and its size, because a PDF's first page at
 * forty pixels says nothing. The chip is shadcn's `Attachment`; the thumbnail
 * is a square of the picture, which that component's sizes shrink to an icon.
 */

function DocumentIcon({ name }: { name: string }) {
  const extension = extensionOf(name)
  if (extension === "xlsx" || extension === "csv") return <FileSpreadsheetIcon />
  if (["pdf", "txt", "md", "docx", "json"].includes(extension)) return <FileTextIcon />
  return <FileIcon />
}

/** The picture of an image or a clip, from wherever it is: an object URL or the server. */
function Still({ kind, src, name }: { kind: "image" | "video"; src: string; name: string }) {
  const [broken, setBroken] = React.useState(false)
  // A file the conversation no longer keeps — it was reset, or aged out — is
  // an icon rather than a broken image.
  if (broken) return kind === "image" ? <ImageIcon /> : <FilmIcon />
  if (kind === "image")
    return (
      <img
        src={src}
        alt={name}
        loading="lazy"
        draggable={false}
        className="size-full object-cover"
        onError={() => setBroken(true)}
      />
    )
  return (
    <>
      {/* `#t=0.1`: without a moment to seek to, a browser draws a black
          rectangle rather than the first frame. */}
      <video
        src={`${src}#t=0.1`}
        muted
        playsInline
        preload="metadata"
        className="size-full object-cover"
        onError={() => setBroken(true)}
      />
      <FilmIcon className="absolute right-1 bottom-1 size-3.5! text-white drop-shadow" />
    </>
  )
}

/** One file in the bar, with its cross. */
export function PendingTile({ item, onRemove }: { item: Pending; onRemove: () => void }) {
  const t = useT()
  const cross = (
    <button
      type="button"
      aria-label={t("Remove {{name}}", { name: item.name })}
      onClick={onRemove}
      className="bg-background text-foreground hover:bg-muted absolute -top-1.5 -right-1.5 z-20 grid size-5 place-items-center rounded-full border shadow-sm"
    >
      <XIcon className="size-3" />
    </button>
  )
  // An image or a clip is a square of itself: that is what it is known by.
  if (item.kind !== "document" && item.preview)
    return (
      <div
        data-slot="attachment"
        data-state={item.state}
        title={item.error || item.name}
        className={cn(
          "bg-muted relative size-16 shrink-0 rounded-xl border",
          item.state === "error" && "border-destructive"
        )}
      >
        <div className="relative size-full overflow-hidden rounded-[inherit]">
          <Still kind={item.kind} src={item.preview} name={item.name} />
          {item.state === "uploading" ? (
            <span className="bg-background/60 absolute inset-0 grid place-items-center">
              <Loader2Icon className="size-4 animate-spin" />
            </span>
          ) : item.state === "error" ? (
            <span className="bg-destructive/40 text-destructive-foreground absolute inset-0 grid place-items-center">
              <TriangleAlertIcon className="size-4" />
            </span>
          ) : null}
        </div>
        {cross}
      </div>
    )
  const state = item.state === "done" ? "done" : item.state === "error" ? "error" : "uploading"
  return (
    <Attachment
      state={state}
      size="sm"
      className="relative h-16 max-w-56 min-w-40 overflow-visible"
      title={item.error || item.name}
    >
      <AttachmentMedia>
        {item.state === "uploading" ? (
          <Loader2Icon className="animate-spin" />
        ) : item.state === "error" ? (
          <TriangleAlertIcon />
        ) : (
          <DocumentIcon name={item.name} />
        )}
      </AttachmentMedia>
      <AttachmentContent>
        <AttachmentTitle>{item.name}</AttachmentTitle>
        <AttachmentDescription>
          {item.state === "error" ? item.error : humanSize(item.size)}
        </AttachmentDescription>
      </AttachmentContent>
      {cross}
    </Attachment>
  )
}

/** One click to keep a file of the conversation in the library, where it does not expire. */
function KeepButton({ item }: { item: Attached }) {
  const t = useT()
  const [kept, setKept] = React.useState(false)
  const label = kept ? t("Kept in the library") : t("Keep in the library")
  return (
    <button
      type="button"
      data-slot="keep-in-library"
      aria-label={`${label}: ${item.name}`}
      title={label}
      disabled={kept}
      onClick={() => {
        api
          .keepAttachment(openChatId(), item.id)
          .then(() => setKept(true))
          .catch((error) => toast.error(t("The file could not be kept"), { description: why(error) }))
      }}
      className="bg-background/90 text-foreground absolute -top-2 -right-2 z-10 flex size-6 items-center justify-center rounded-full border opacity-0 shadow-xs transition-opacity group-focus-within/keep:opacity-100 group-hover/keep:opacity-100 focus-visible:opacity-100"
    >
      {kept ? <CheckIcon className="size-3.5" /> : <BookmarkPlusIcon className="size-3.5" />}
    </button>
  )
}

/** The files of a message already said: thumbnails that open in full. */
export function AttachedGallery({ items, align }: { items: Attached[]; align: "start" | "end" }) {
  const t = useT()
  const [open, setOpen] = React.useState<Attached | null>(null)
  return (
    <>
      <AttachmentGroup className={cn("max-w-full flex-wrap items-center", align === "end" && "justify-end")}>
        {items.map((item) => (
          <span key={item.id} className="group/keep relative inline-flex">
            <KeepButton item={item} />
            {item.kind === "document" ? (
            <Attachment size="sm" className="max-w-60 min-w-40">
              <AttachmentMedia>
                <DocumentIcon name={item.name} />
              </AttachmentMedia>
              <AttachmentContent>
                <AttachmentTitle>{item.name}</AttachmentTitle>
                <AttachmentDescription>{humanSize(item.size)}</AttachmentDescription>
              </AttachmentContent>
              {/* A document opens where the browser reads it best: a tab. */}
              <AttachmentTrigger asChild>
                <a
                  href={attachmentUrl(item.id)}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={t("Open {{name}}", { name: item.name })}
                />
              </AttachmentTrigger>
            </Attachment>
          ) : (
            <button
              type="button"
              data-slot="attachment"
              aria-label={t("Open {{name}}", { name: item.name })}
              title={item.name}
              onClick={() => setOpen(item)}
              className="bg-muted focus-visible:ring-ring/50 relative size-28 shrink-0 cursor-zoom-in overflow-hidden rounded-xl border outline-none focus-visible:ring-[3px]"
            >
              <Still kind={item.kind} src={attachmentUrl(item.id)} name={item.name} />
            </button>
            )}
          </span>
        ))}
      </AttachmentGroup>
      <Dialog open={open !== null} onOpenChange={(next) => (next ? null : setOpen(null))}>
        <DialogContent
          closeLabel={t("Close")}
          className="w-auto max-w-[min(92vw,1400px)] gap-2 border-none bg-transparent p-0 shadow-none sm:max-w-[min(92vw,1400px)] [&>button]:bg-background/80 [&>button]:rounded-full [&>button]:p-1"
        >
          <DialogTitle className="sr-only">{open?.name}</DialogTitle>
          <DialogDescription className="sr-only">{t("A file sent to the workspace")}</DialogDescription>
          {open?.kind === "image" ? (
            <img
              src={attachmentUrl(open.id)}
              alt={open.name}
              className="max-h-[85vh] max-w-full rounded-lg object-contain"
            />
          ) : open?.kind === "video" ? (
            <video
              src={attachmentUrl(open.id)}
              controls
              autoPlay
              className="max-h-[85vh] max-w-full rounded-lg bg-black"
            />
          ) : null}
          {open ? (
            <p className="text-center font-mono text-xs text-white/80">
              {open.name} · {humanSize(open.size)}
            </p>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  )
}
