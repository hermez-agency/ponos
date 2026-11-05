import * as React from "react"
import { PlusIcon } from "lucide-react"

import { AttachmentGroup } from "@/components/ui/attachment"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { ACCEPT_ATTRIBUTE, type Pending } from "@/lib/composer"
import { useT } from "@/lib/i18n"

import { PendingTile } from "../attachments"

/** The files on their way into the message, above the words. */
export function AttachmentStrip({ pending, onRemove }: { pending: Pending[]; onRemove: (item: Pending) => void }) {
  if (!pending.length) return null
  return (
    // Room above and to the right for the crosses, which sit on the corners
    // and a scrolling row would otherwise cut.
    <AttachmentGroup className="px-3 pt-4 pr-4 pb-0.5">
      {pending.map((item) => (
        <PendingTile key={item.key} item={item} onRemove={() => onRemove(item)} />
      ))}
    </AttachmentGroup>
  )
}

/** The + on the lower edge, and the file picker it opens. */
export function AttachButton({ disabled, onFiles }: { disabled: boolean; onFiles: (files: File[]) => void }) {
  const t = useT()
  const picker = React.useRef<HTMLInputElement>(null)
  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground rounded-full"
            aria-label={t("Attach a file")}
            disabled={disabled}
            onClick={() => picker.current?.click()}
          >
            <PlusIcon className="size-5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="top">{t("Attach a photo, a video or a document — or drop it, or paste it")}</TooltipContent>
      </Tooltip>
      <input
        ref={picker}
        type="file"
        multiple
        hidden
        accept={ACCEPT_ATTRIBUTE}
        onChange={(event) => {
          onFiles(Array.from(event.target.files ?? []))
          event.target.value = ""
        }}
      />
    </>
  )
}
