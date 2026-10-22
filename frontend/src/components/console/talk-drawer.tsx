import * as React from "react"
import { Maximize2, MessageCircle, Minimize2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { hotkeyLabel, useHotkeys } from "@/hooks/use-hotkeys"
import { useT } from "@/lib/i18n"
import { CLOSED, OPENED, TOGGLED } from "@/lib/talk"
import { cn } from "@/lib/utils"

import { ConsolePane } from "./console-pane"

/* The discussion, behind a bubble.
 *
 * It used to be a column: half the screen given to a conversation whether or
 * not there was one, an entry in the menu to reach it on a phone, and a switch
 * in the bar to fold it away — three places to learn for one thing to open. A
 * bubble in the bottom corner is the gesture everybody already knows, and the
 * page keeps its full width until you ask for the conversation.
 *
 * What it opens is the workspace, wherever you are. It used to open a ticket's
 * discussion on that ticket's page, and said so nowhere: a question waiting on
 * you sat behind a bubble that looked the same on every page. The discussion
 * is a tab of the ticket's page now, counted — see `TicketPage` — and the
 * bubble has one role left.
 */

/* How wide the drawer is.
 *
 * It opened at 32rem, the width of a form, and a conversation is not a form: an
 * answer with a table or a block of code in it wrapped every other line. Half
 * the screen by default, between a width that still reads and one past which a
 * line of prose is too long to follow — and whatever you last dragged it to,
 * kept in `localStorage` like the theme, because a width you chose once is the
 * width you want the next time. On a phone none of this applies: the drawer is
 * the whole screen, as it always was. */
const WIDTH_KEY = "ponos-talk-width"
const NARROWEST = 360
/** The board keeps this much of itself visible beside a dragged drawer. */
const MARGIN = 48
/** How far an arrow key moves the edge. */
const STEP = 32

function keptWidth(): number | null {
  try {
    const kept = Number(localStorage.getItem(WIDTH_KEY))
    return Number.isFinite(kept) && kept >= NARROWEST ? kept : null
  } catch {
    // Storage switched off: the drawer opens at its default width every time.
    return null
  }
}

function keepWidth(width: number | null) {
  try {
    if (width === null) localStorage.removeItem(WIDTH_KEY)
    else localStorage.setItem(WIDTH_KEY, String(Math.round(width)))
  } catch {
    // The width holds for as long as the tab is open, which is the whole cost.
  }
}

const within = (width: number) =>
  Math.max(NARROWEST, Math.min(width, window.innerWidth - MARGIN))

/** Alt+Shift+F: a key a textarea does nothing with, and no browser takes for itself. */
const isFullKey = (event: React.KeyboardEvent) =>
  event.altKey && event.shiftKey && !event.ctrlKey && !event.metaKey && event.code === "KeyF"

export function TalkDrawer() {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const [width, setWidth] = React.useState<number | null>(keptWidth)
  const [full, setFull] = React.useState(false)
  // The width a drag started from, and where the pointer was: the edge follows
  // the pointer by the distance it moved, not to wherever it happens to be.
  const drag = React.useRef<{ x: number; width: number } | null>(null)
  const content = React.useRef<HTMLDivElement>(null)
  // What had the focus before the drawer opened — a card, the palette's
  // field, a textarea on the page — and gets it back when the drawer closes.
  // The sheet alone would hand it to the bubble, which was not where you were
  // unless you clicked it.
  const before = React.useRef<HTMLElement | null>(null)

  const resize = (next: number) => {
    const bounded = within(next)
    setWidth(bounded)
    keepWidth(bounded)
  }

  const change = React.useCallback((next: boolean | ((current: boolean) => boolean)) => {
    setOpen((current) => {
      const opening = typeof next === "function" ? next(current) : next
      if (opening && !current)
        before.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
      return opening
    })
  }, [])

  React.useEffect(() => {
    const opened = () => change(true)
    const toggled = () => change((current) => !current)
    window.addEventListener(OPENED, opened)
    const closed = () => change(false)
    window.addEventListener(TOGGLED, toggled)
    window.addEventListener(CLOSED, closed)
    return () => {
      window.removeEventListener(CLOSED, closed)
      window.removeEventListener(OPENED, opened)
      window.removeEventListener(TOGGLED, toggled)
    }
  }, [change])

  useHotkeys({ console: () => change((current) => !current) })
  const shortcut = hotkeyLabel("console")

  const label = t("the console")
  const fullLabel = full ? t("Leave full screen") : t("Full screen")

  return (
    <Sheet open={open} onOpenChange={change}>
      <Tooltip>
        <TooltipTrigger asChild>
          <SheetTrigger asChild>
            {/* Hidden while the drawer is over it: the sheet's own close is
                where a reader looks for it, and a bubble under the overlay is
                a button that answers nothing. Standing on the admin layout's
                navigation on a phone, where it runs along the bottom edge —
                and the page leaves room under its end for both (`index.css`). */}
            <Button
              size="icon-lg"
              aria-label={t("Open {{pane}}", { pane: label })}
              aria-keyshortcuts={shortcut.aria}
              className="fixed right-4 bottom-[calc(var(--bottom-nav)+1rem)] z-40 size-12 rounded-full shadow-lg data-[state=open]:hidden"
            >
              <MessageCircle className="size-5" />
            </Button>
          </SheetTrigger>
        </TooltipTrigger>
        <TooltipContent side="left">{`${t("Open {{pane}}", { pane: label })} · ${shortcut.label}`}</TooltipContent>
      </Tooltip>

      <SheetContent
        ref={content}
        side="right"
        className={cn(
          "w-full gap-0",
          full
            ? "sm:w-screen sm:max-w-none"
            : "sm:w-[var(--talk-width,clamp(32rem,50vw,900px))] sm:max-w-[calc(100vw-3rem)]"
        )}
        style={width ? ({ "--talk-width": `${width}px` } as React.CSSProperties) : undefined}
        closeLabel={t("Close")}
        onKeyDown={(event) => {
          if (!isFullKey(event)) return
          event.preventDefault()
          setFull((current) => !current)
        }}
        // Opened to say something: the cursor goes where the words go, not to
        // the cross in the corner that the dialog would otherwise pick.
        onOpenAutoFocus={(event) => {
          const field = event.currentTarget instanceof HTMLElement
            ? event.currentTarget.querySelector("textarea")
            : null
          if (!field || field.disabled) return
          event.preventDefault()
          field.focus()
        }}
        onCloseAutoFocus={(event) => {
          const back = before.current
          before.current = null
          if (!back || !back.isConnected || back === document.body) return
          event.preventDefault()
          back.focus()
        }}
      >
        {/* The pane under it opens with its own heading — which machine you
            are talking to — so the sheet's is for the readers who are told
            the page rather than shown it. */}
        <SheetHeader className="sr-only">
          <SheetTitle>{label}</SheetTitle>
          <SheetDescription>
            {t("A sentence talks to your workspace; a line that starts with > runs a command.")}
          </SheetDescription>
        </SheetHeader>
        {/* The edge the drawer is pulled by. A separator, in the ARIA sense,
            so the arrow keys move it for whoever does not drag; a double click
            puts it back where it opens by default. Gone in full screen, where
            there is no edge left to pull, and on a phone, where the drawer is
            the screen. */}
        {full ? null : (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label={t("Resize the drawer")}
            aria-valuemin={NARROWEST}
            aria-valuenow={Math.round(width ?? content.current?.offsetWidth ?? 0)}
            tabIndex={0}
            className="hover:bg-primary/40 focus-visible:bg-primary/60 active:bg-primary/60 absolute inset-y-0 -left-1 z-10 hidden w-2 cursor-col-resize touch-none transition-colors outline-none sm:block"
            onPointerDown={(event) => {
              if (event.button !== 0 || !content.current) return
              event.preventDefault()
              event.currentTarget.setPointerCapture(event.pointerId)
              drag.current = { x: event.clientX, width: content.current.offsetWidth }
            }}
            onPointerMove={(event) => {
              if (!drag.current) return
              // Pulled left, wider: the drawer hangs from the right edge.
              setWidth(within(drag.current.width + drag.current.x - event.clientX))
            }}
            onPointerUp={(event) => {
              if (!drag.current) return
              drag.current = null
              event.currentTarget.releasePointerCapture(event.pointerId)
              if (content.current) keepWidth(content.current.offsetWidth)
            }}
            onDoubleClick={() => {
              setWidth(null)
              keepWidth(null)
            }}
            onKeyDown={(event) => {
              const current = content.current?.offsetWidth ?? 0
              if (event.key === "ArrowLeft") resize(current + STEP)
              else if (event.key === "ArrowRight") resize(current - STEP)
              else return
              event.preventDefault()
            }}
          />
        )}
        {/* Beside the sheet's own cross, which the panes leave room for. */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`${fullLabel} (Alt+Shift+F)`}
              aria-pressed={full}
              className="absolute top-2 right-10 z-10 hidden opacity-70 hover:opacity-100 sm:inline-flex"
              onClick={() => setFull((current) => !current)}
            >
              {full ? <Minimize2 /> : <Maximize2 />}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">{`${fullLabel} · Alt+Shift+F`}</TooltipContent>
        </Tooltip>
        <ConsolePane />
      </SheetContent>
    </Sheet>
  )
}
