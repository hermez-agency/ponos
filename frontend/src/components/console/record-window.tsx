import * as React from "react"
import { Maximize2, XIcon } from "lucide-react"
import {
  Link,
  open,
  useChildViewRoute,
  useNavigate,
  useViewLink,
  type OpenFrame,
  type OpenFrameProps,
  type ViewResource,
} from "react-resource-view"

import { Button, buttonVariants } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

/* The window a record is opened in over its list: the ticket's over the board,
 * a schedule's over the schedules. One shell, so the two are the same size, on a
 * phone the same whole screen, and have the same two buttons in their header —
 * the record's own page, and the cross. What is inside is the view itself.
 *
 * It is a frame of react-resource-view's (`open.custom`), declared as the
 * `open` of the view it draws: the package writes the record into the address
 * under the list it was opened from (`…/tickets/list/tickets/read/<id>`), so
 * Back closes it, a reload opens it again over the same list, and the stream
 * drawing a card again in another column does not close it. The package's own
 * dialog is not this one: its title is the view's name and nothing else, and a
 * ticket is told by its short id and its whole title. */

/** What the header says about the record on screen. */
export interface RecordWindowHead {
  /** The small line over the title: a ticket's short id. */
  eyebrow?: string
  title: string
  /** The line under the title: a sentence, or a link — a ticket's goal. */
  description?: React.ReactNode
  /** What the record can be made to do, drawn before its page button. */
  actions?: React.ReactNode
}

/* How a form inside the window closes it — its own Cancel button. Nothing on
 * the record's full page, which has no window to close. */
const CloseWindow = React.createContext<(() => void) | null>(null)

/** The window's way out, for what is drawn inside it; null on the record's own page. */
export const useCloseWindow = () => React.use(CloseWindow)

/** The window, as the `open` of a view: `useHead` is asked about the record the address names. */
export function recordWindow({
  type,
  fallbackTitle,
  useHead,
  className,
}: {
  type: string
  /** What the title says while the record is not known (yet), as a key of the dictionary. */
  fallbackTitle: string
  useHead: (id: string) => RecordWindowHead
  /** The window's own size, where the record's form wants another. */
  className?: string
}): OpenFrame {
  function Frame({ close, expandHref, children }: OpenFrameProps) {
    const t = useT()
    const id = String(useChildViewRoute()?.child?.id ?? "")
    const head = useHead(id)
    return (
      <RecordWindow
        onClose={close}
        eyebrow={head.eyebrow}
        title={head.title}
        description={head.description}
        fallbackTitle={t(fallbackTitle)}
        className={className}
        href={expandHref}
        actions={head.actions}
      >
        {children}
      </RecordWindow>
    )
  }
  return open.custom({ type, component: Frame })
}

/**
 * What a link to a record does over its list: a plain click opens it in the
 * window its view declares, and the link stays a link to its page — a middle
 * click or Ctrl+click still opens that page in a tab of its own. `query` goes
 * along in the address, for the view to read: the tab a ticket opens on.
 */
export function useOpensOverTheList(
  resource: ViewResource,
  action: "read" | "update",
  id: string,
  query = ""
) {
  const link = useViewLink({ resource, action, id })
  const navigate = useNavigate()
  return (event: React.MouseEvent<HTMLElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    // So that closing the window is Back, and the focus comes back to the link.
    link.onOpen(event)
    void navigate({ to: query ? `${link.to}${link.to.includes("?") ? "&" : "?"}${query}` : link.to })
  }
}

function RecordWindow({
  onClose,
  eyebrow,
  title,
  description,
  fallbackTitle,
  href,
  actions,
  className,
  children,
}: RecordWindowHead & {
  onClose: () => void
  fallbackTitle: string
  className?: string
  /** The record's full page; no button without one. */
  href?: string
  children: React.ReactNode
}) {
  const t = useT()
  return (
    <Dialog open onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent
        data-ticket-window
        showCloseButton={false}
        // Said out loud, though the page behind is already hidden from a screen
        // reader while it is open: some read the attribute and nothing else.
        aria-modal="true"
        // Described by its line under the title when it has one.
        {...(description ? {} : { "aria-describedby": undefined })}
        className={cn("gap-0 p-0 sm:max-w-3xl", className)}
      >
        <DialogHeader className="flex-row items-start gap-2 border-b px-5 py-3 text-left sm:text-left">
          <div className="min-w-0 flex-1">
            {eyebrow ? <p className="text-muted-foreground font-mono text-xs">{eyebrow}</p> : null}
            <DialogTitle
              className="line-clamp-2 text-base leading-snug break-words"
              title={title}
            >
              {title || fallbackTitle}
            </DialogTitle>
            {description ? (
              <DialogDescription className="mt-0.5 text-sm">{description}</DialogDescription>
            ) : null}
          </div>
          {actions}
          {href ? (
            <Link
              to={href}
              className={buttonVariants({ variant: "ghost", size: "icon-sm" })}
              title={t("Open the full page")}
              aria-label={t("Open the full page")}
            >
              <Maximize2 />
            </Link>
          ) : null}
          <DialogClose asChild>
            <Button variant="ghost" size="icon-sm" title={t("Close")} aria-label={t("Close")}>
              <XIcon />
            </Button>
          </DialogClose>
        </DialogHeader>
        <div className="min-h-0 overflow-y-auto px-5 py-4">
          <CloseWindow value={onClose}>{children}</CloseWindow>
        </div>
      </DialogContent>
    </Dialog>
  )
}
