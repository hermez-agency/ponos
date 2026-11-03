import * as React from "react"
import { toast } from "sonner"

import { why } from "@/lib/api"
import { carried, kindOf, nameFor, screen, settled, withAdded, without, type Pending } from "@/lib/composer"
import { useT } from "@/lib/i18n"
import type { Attached } from "@/lib/types"

/* The files of a message bar, from the moment they are added.
 *
 * Files are uploaded the moment they are added, not when the message goes: a
 * video takes a while, and the time to take it is the time spent writing the
 * sentence that comes with it. What the server keeps is held here, by the key
 * of its tile, until the message carries it away.
 */

let counter = 0

export function useAttachments({
  upload,
  discard,
  limitMb,
}: {
  upload?: (file: File, name: string) => Promise<Attached>
  discard?: (id: string) => void
  limitMb: number
}) {
  const t = useT()
  const [pending, setPending] = React.useState<Pending[]>([])
  const kept = React.useRef(new Map<string, Attached>())
  // The list as it stands, for the callbacks that outlive the render they were
  // made in: an upload that ends, the page that closes.
  const current = React.useRef(pending)
  current.current = pending

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

  const remove = (item: Pending) => {
    if (item.preview) URL.revokeObjectURL(item.preview)
    if (item.id) discard?.(item.id)
    kept.current.delete(item.key)
    setPending((list) => without(list, item.key))
  }

  /** The files kept, as a message would carry them with these words. */
  const carriedWith = (text: string) => carried(text, pending, kept.current)

  /** Gone with the message that carried them. */
  const clear = (sent: Pending[]) => {
    sent.forEach((item) => item.preview && URL.revokeObjectURL(item.preview))
    kept.current.clear()
    setPending([])
  }

  // The previews are object URLs, which the page keeps until told otherwise.
  React.useEffect(
    () => () => current.current.forEach((item) => item.preview && URL.revokeObjectURL(item.preview)),
    []
  )

  return { pending, add, remove, carriedWith, clear }
}
