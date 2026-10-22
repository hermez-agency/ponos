import * as React from "react"
import { ImagePlus, Link2, Smile, Trash2, Upload } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { Picture, Pictures, Project } from "@/lib/types"
import { cn } from "@/lib/utils"
import { forgetProject } from "@/resources/projects"

/* A project's pictures: the cover of its page, and its icon.
 *
 * They are Notion's own — the banner across the top of a page and the mark in
 * front of its title — so the pictures people already chose for their pages
 * are the ones the console shows, and a picture changed here is the one Notion
 * shows. On a board of files, they are files beside the project's.
 *
 * Three places draw them. Wherever a project is named — a card, a row, the
 * picker of a new ticket, the corner of its own page — as its mark: the icon,
 * since that is what was chosen to stand for it; the cover cropped square where
 * there is no icon; and for a project that has neither, its initial on a
 * colour of its own, so that eleven projects are not eleven identical grey
 * squares. The page, as a banner with that mark set on it. And the dialog that
 * changes them, which shrinks an image before sending it: a photo straight off
 * a phone is ten megabytes, and a banner needs a fraction of that.
 */

type Slot = "cover" | "icon"

/** How wide a cover is kept, and how large an icon: what Notion draws them at, and no more. */
const LONGEST: Record<Slot, number> = { cover: 1500, icon: 280 }

/** A colour of the project's own, from its name — the same one every time. */
function hueOf(name: string): number {
  let hash = 0
  for (const character of name) hash = (hash * 31 + character.codePointAt(0)!) % 360
  return hash
}

/** The letter a project without a picture is recognised by. */
function initialOf(name: string): string {
  return [...name.trim()][0]?.toUpperCase() ?? "?"
}

/** An image that says so when it cannot be drawn, so what is under it shows instead. */
function Img({ src, className, onMissing }: { src: string; className?: string; onMissing: () => void }) {
  return <img src={src} alt="" loading="lazy" draggable={false} className={className} onError={onMissing} />
}

/* -- the mark ----------------------------------------------------------- */

/* What a project is recognised by: its icon, or its cover, or its initial.
 *
 * The icon first. The thumbnail used to be the cover cropped square, with an
 * emoji icon as a small badge over its corner and an image icon not at all —
 * so the icon somebody chose to stand for a project was the one picture the
 * list did not show. The cover is what is left when there is no icon. */
export function ProjectThumb({
  project,
  className,
}: {
  project: Pick<Project, "name" | "icon" | "cover">
  className?: string
}) {
  // Every image that could not be drawn, so the next one in line shows instead.
  const [broken, setBroken] = React.useState<string[]>([])
  const drawable = (picture?: Picture) =>
    picture?.kind === "image" && picture.src && !broken.includes(picture.src) ? picture.src : ""
  const icon = project.icon
  const image = drawable(icon) || (icon?.kind === "emoji" && icon.emoji ? "" : drawable(project.cover))
  const hue = hueOf(project.name)
  const initial = !image && !(icon?.kind === "emoji" && icon.emoji)
  return (
    <span
      aria-hidden
      className={cn(
        "bg-muted @container relative inline-flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-lg border",
        className
      )}
      style={initial ? { background: `oklch(0.9 0.06 ${hue})`, color: `oklch(0.38 0.12 ${hue})` } : undefined}
    >
      {image ? (
        <Img src={image} className="size-full object-cover" onMissing={() => setBroken([...broken, image])} />
      ) : icon?.kind === "emoji" && icon.emoji ? (
        // Sized by the mark rather than by the text around it: the same
        // emoji is a corner of a select and the corner of a page.
        <span className="text-[62cqw] leading-none">{icon.emoji}</span>
      ) : (
        <span className="text-[45cqw] leading-none font-semibold">{initialOf(project.name)}</span>
      )}
    </span>
  )
}

/* -- the banner ----------------------------------------------------------- */

/** What is said under the banner: a change waiting, or a conflict settled. Quietly. */
function PictureNote({ pictures }: { pictures: Pick<Pictures, "cover" | "icon"> }) {
  const t = useT()
  const both = [pictures.cover, pictures.icon]
  const failed = both.find((picture) => picture.pending && picture.error)
  const waiting = both.some((picture) => picture.pending)
  const conflict = both.find((picture) => picture.conflict)?.conflict
  if (!failed && !waiting && !conflict) return null
  return (
    <p className="text-muted-foreground mt-1 text-xs" role="status">
      {failed
        ? t("Not in Notion yet — kept here, and sent again at the next reading: {{why}}", {
            why: failed.error || "?",
          })
        : waiting
          ? t("Not in Notion yet — sent again at the next reading.")
          : conflict === "notion"
            ? t("Changed on both sides: Notion's picture was newer, and it won.")
            : t("Changed on both sides: this one was newer, and it won in Notion too.")}
    </p>
  )
}

/**
 * The top of a project's page: the cover across it, the icon set on its lower
 * edge, and the button that changes both. The page's header is the layout's —
 * the way back, the name, the edit button — and this is the first thing under
 * it, not a second header.
 */
export function ProjectCover({
  project,
  editable,
  compact = false,
}: {
  project: Project
  editable: boolean
  /** Lower, in the panel beside the list of projects. */
  compact?: boolean
}) {
  const t = useT()
  const [pictures, setPictures] = React.useState<Pick<Pictures, "cover" | "icon">>({
    cover: project.cover ?? { kind: "" },
    icon: project.icon ?? { kind: "" },
  })
  const [open, setOpen] = React.useState(false)
  const [broken, setBroken] = React.useState("")
  React.useEffect(() => {
    setPictures({ cover: project.cover ?? { kind: "" }, icon: project.icon ?? { kind: "" } })
  }, [project])

  const cover = pictures.cover.kind === "image" && pictures.cover.src !== broken ? pictures.cover : null
  const hue = hueOf(project.name)

  return (
    <div className={compact ? "mb-6" : "mb-8"}>
      <div
        className={cn(
          "group relative w-full overflow-visible rounded-xl border",
          compact ? "h-24 sm:h-28" : "h-32 sm:h-44"
        )}
        style={
          cover
            ? undefined
            : {
                background: `linear-gradient(120deg, oklch(0.9 0.05 ${hue}), oklch(0.82 0.08 ${(hue + 40) % 360}))`,
              }
        }
      >
        {cover ? (
          <Img
            src={cover.src!}
            className="size-full rounded-xl object-cover"
            onMissing={() => setBroken(cover.src!)}
          />
        ) : null}
        {editable ? (
          <Button
            size="sm"
            variant="secondary"
            className="absolute top-2 right-2 shadow-sm"
            onClick={() => setOpen(true)}
          >
            <ImagePlus />
            {t("Change the image")}
          </Button>
        ) : null}
        <ProjectThumb
          project={{ name: project.name, ...pictures }}
          className="bg-background absolute -bottom-7 left-4 size-16 rounded-xl shadow-sm sm:size-20"
        />
      </div>
      <div className="min-h-8 pt-1 pl-24 sm:pl-28">
        <PictureNote pictures={pictures} />
      </div>
      {editable ? (
        <PictureDialog
          open={open}
          onOpenChange={setOpen}
          project={project}
          pictures={pictures}
          onChange={setPictures}
        />
      ) : null}
    </div>
  )
}

/* -- changing them -------------------------------------------------------- */

/** An image, made no larger than it is drawn: WebP where the browser writes it, JPEG or PNG otherwise. */
async function shrink(file: Blob, slot: Slot): Promise<Blob> {
  const address = URL.createObjectURL(file)
  try {
    const image = new Image()
    image.src = address
    await image.decode()
    const width = image.naturalWidth || LONGEST[slot]
    const height = image.naturalHeight || LONGEST[slot]
    const scale = Math.min(1, LONGEST[slot] / (slot === "cover" ? width : Math.max(width, height)))
    // Already small, and already a kind that is drawn as it is — a GIF would
    // lose its movement on a canvas, and nothing is gained by redrawing it.
    if (scale === 1 && file.size < 300 * 1024 && /^image\/(webp|jpeg|png|gif)$/.test(file.type)) return file
    const canvas = document.createElement("canvas")
    canvas.width = Math.max(1, Math.round(width * scale))
    canvas.height = Math.max(1, Math.round(height * scale))
    canvas.getContext("2d")!.drawImage(image, 0, 0, canvas.width, canvas.height)
    // An icon may be transparent, and JPEG would paint that black.
    for (const kind of ["image/webp", slot === "icon" ? "image/png" : "image/jpeg"]) {
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, kind, 0.85))
      if (blob && blob.type === kind) return blob
    }
    return file
  } finally {
    URL.revokeObjectURL(address)
  }
}

const EXTENSIONS: Record<string, string> = {
  "image/webp": "webp",
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/gif": "gif",
}

/** A handful to pick from; any other is typed or pasted in the field beside them. */
const EMOJIS = ["🚀", "📦", "🛠️", "🧪", "📝", "🎨", "🐾", "🌱", "💡", "📈", "🛢️", "🤖", "🏠", "🎯", "📚", "🔒"]

/** What is about to be set, before it is: the preview is drawn from this. */
type Draft =
  | { kind: "file"; blob: Blob; name: string; preview: string }
  | { kind: "url"; url: string }
  | { kind: "emoji"; emoji: string }

function PictureDialog({
  open,
  onOpenChange,
  project,
  pictures,
  onChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  project: Project
  pictures: Pick<Pictures, "cover" | "icon">
  onChange: (pictures: Pick<Pictures, "cover" | "icon">) => void
}) {
  const t = useT()
  const [slot, setSlot] = React.useState<Slot>("cover")
  const [draft, setDraft] = React.useState<Draft | null>(null)
  const [address, setAddress] = React.useState("")
  const [typed, setTyped] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const input = React.useRef<HTMLInputElement>(null)

  // Each tab starts from what that picture is now.
  React.useEffect(() => {
    setDraft(null)
    setAddress(pictures[slot].url ?? "")
    setTyped(slot === "icon" && pictures.icon.kind === "emoji" ? (pictures.icon.emoji ?? "") : "")
    // Only on opening and on changing tabs: `pictures` changes under the
    // dialog when a change lands, and what is being typed must survive that.
  }, [slot, open])

  React.useEffect(() => () => {
    if (draft?.kind === "file") URL.revokeObjectURL(draft.preview)
  }, [draft])

  function takeFile(file: File | Blob | null | undefined, name = "") {
    if (!file || !file.type.startsWith("image/")) {
      if (file) toast.error(t("That file is not an image."))
      return
    }
    setDraft({
      kind: "file",
      blob: file,
      name: name || ("name" in file ? file.name : "") || `${slot}`,
      preview: URL.createObjectURL(file),
    })
  }

  function onPaste(event: React.ClipboardEvent) {
    const file = [...event.clipboardData.files].find((one) => one.type.startsWith("image/"))
    if (file) {
      event.preventDefault()
      takeFile(file, file.name || `pasted-${slot}`)
    }
  }

  async function apply(send: () => Promise<Pictures>, optimistic: Picture) {
    const before = pictures
    // Shown at once, as if it had landed: the server's answer replaces it.
    onChange({ ...pictures, [slot]: optimistic })
    setBusy(true)
    try {
      const answer = await send()
      onChange({ cover: answer.cover, icon: answer.icon })
      // The panel and the page alone draw the same read: neither draws the old picture again.
      forgetProject(project.id)
      if (answer[slot].pending) {
        toast.warning(t("Kept here, not yet in Notion"), {
          description: answer[slot].error || t("It is sent again at the next reading of the board."),
        })
      } else {
        toast.success(slot === "cover" ? t("The cover is changed") : t("The icon is changed"))
      }
      onOpenChange(false)
    } catch (error) {
      onChange(before)
      toast.error(t("The image was not changed"), { description: why(error) })
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    const chosen = draft
    if (!chosen) return
    if (chosen.kind === "file") {
      let blob: Blob
      try {
        blob = await shrink(chosen.blob, slot)
      } catch {
        toast.error(t("This image could not be read."))
        return
      }
      const stem = chosen.name.replace(/\.[^.]+$/, "") || slot
      const name = `${stem}.${EXTENSIONS[blob.type] ?? "img"}`
      return apply(() => api.uploadPicture(project.id, slot, blob, name), {
        kind: "image",
        src: chosen.preview,
        pending: true,
      })
    }
    if (chosen.kind === "url")
      return apply(() => api.setPicture(project.id, slot, { url: chosen.url }), {
        kind: "image",
        src: chosen.url,
        url: chosen.url,
        pending: true,
      })
    return apply(() => api.setPicture(project.id, slot, { emoji: chosen.emoji }), {
      kind: "emoji",
      emoji: chosen.emoji,
      pending: true,
    })
  }

  const current = pictures[slot]
  // The draft when there is one, what is set otherwise.
  const showsEmoji = slot === "icon" && (draft ? draft.kind === "emoji" : current.kind === "emoji")
  const emoji = draft?.kind === "emoji" ? draft.emoji : (current.emoji ?? "")
  const preview = draft
    ? draft.kind === "file"
      ? draft.preview
      : draft.kind === "url"
        ? draft.url
        : ""
    : current.kind === "image"
      ? (current.src ?? "")
      : ""

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className="sm:max-w-lg" onPaste={onPaste}>
        <DialogHeader>
          <DialogTitle>{t("Change the image")}</DialogTitle>
          <DialogDescription>
            {t("The cover and the icon of the project's page, in Notion as well as here.")}
          </DialogDescription>
        </DialogHeader>

        <Tabs value={slot} onValueChange={(value) => setSlot(value as Slot)}>
          <TabsList className="w-full">
            <TabsTrigger value="cover">{t("Cover")}</TabsTrigger>
            <TabsTrigger value="icon">{t("Icon")}</TabsTrigger>
          </TabsList>

          <TabsContent value={slot} className="mt-3 flex flex-col gap-4">
            {/* The preview: what will be set, as it will be drawn. */}
            <div
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                takeFile(event.dataTransfer.files[0])
              }}
              className={cn(
                "bg-muted/40 relative flex items-center justify-center overflow-hidden rounded-lg border border-dashed",
                slot === "cover" ? "h-32 w-full" : "mx-auto size-24"
              )}
            >
              {showsEmoji ? (
                <span className="text-5xl leading-none">{emoji}</span>
              ) : preview ? (
                <img src={preview} alt="" className="size-full object-cover" />
              ) : (
                <span className="text-muted-foreground px-3 text-center text-xs">
                  {t("Drop an image here, or paste one.")}
                </span>
              )}
            </div>

            <div className="flex flex-wrap gap-2">
              <input
                ref={input}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(event) => {
                  takeFile(event.target.files?.[0])
                  event.target.value = ""
                }}
              />
              <Button type="button" variant="outline" size="sm" onClick={() => input.current?.click()}>
                <Upload />
                {t("Choose a file")}
              </Button>
              {current.kind ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-destructive"
                  disabled={busy}
                  onClick={() => apply(() => api.setPicture(project.id, slot, { remove: true }), { kind: "" })}
                >
                  <Trash2 />
                  {slot === "cover" ? t("Remove the cover") : t("Remove the icon")}
                </Button>
              ) : null}
            </div>

            <label className="flex flex-col gap-1.5 text-sm">
              <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
                <Link2 className="size-3.5" />
                {t("Or the address of an image")}
              </span>
              <Input
                type="url"
                inputMode="url"
                placeholder="https://images.unsplash.com/…"
                value={address}
                onChange={(event) => {
                  setAddress(event.target.value)
                  const url = event.target.value.trim()
                  setDraft(/^https?:\/\/\S+$/.test(url) ? { kind: "url", url } : null)
                }}
              />
            </label>

            {slot === "icon" ? (
              <div className="flex flex-col gap-1.5">
                <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
                  <Smile className="size-3.5" />
                  {t("Or an emoji")}
                </span>
                <div className="flex flex-wrap items-center gap-1">
                  {EMOJIS.map((one) => (
                    <button
                      key={one}
                      type="button"
                      aria-label={one}
                      aria-pressed={emoji === one}
                      className={cn(
                        "hover:bg-muted flex size-9 items-center justify-center rounded-md text-xl",
                        emoji === one && "bg-muted ring-ring ring-1"
                      )}
                      onClick={() => {
                        setTyped(one)
                        setDraft({ kind: "emoji", emoji: one })
                      }}
                    >
                      {one}
                    </button>
                  ))}
                  <Input
                    aria-label={t("Another emoji")}
                    className="h-9 w-16 text-center text-lg"
                    maxLength={16}
                    value={typed}
                    onChange={(event) => {
                      setTyped(event.target.value)
                      const value = event.target.value.trim()
                      setDraft(value ? { kind: "emoji", emoji: value } : null)
                    }}
                  />
                </div>
              </div>
            ) : null}
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button type="button" variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>
            {t("Cancel")}
          </Button>
          <Button type="button" disabled={busy || !draft} onClick={save}>
            {busy ? t("Sending…") : t("Use this image")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
