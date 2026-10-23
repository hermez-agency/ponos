import * as React from "react"
import { ArrowDown } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

/** Under this many pixels from the bottom of the list, it is being followed. */
const STICK_THRESHOLD = 48

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
}

/* The messages of a conversation — Brand Assets' `chat-conversation`, its words
 * through `t()`. It follows the bottom as long as you have not scrolled up (a
 * stream makes it grow), and offers a way back to the last message otherwise.
 * The messages are its children; the message bar goes under it. */
function ChatConversation({
  children,
  empty,
  className,
}: {
  children?: React.ReactNode
  /** What is shown when there is no message. */
  empty?: React.ReactNode
  className?: string
}) {
  const t = useT()
  const scroller = React.useRef<HTMLDivElement>(null)
  const content = React.useRef<HTMLDivElement>(null)
  const stuck = React.useRef(true)
  const [atBottom, setAtBottom] = React.useState(true)

  const toBottom = React.useCallback((smooth: boolean) => {
    const element = scroller.current
    if (element)
      element.scrollTo({
        top: element.scrollHeight,
        behavior: smooth && !prefersReducedMotion() ? "smooth" : "auto",
      })
  }, [])

  React.useEffect(() => {
    const element = content.current
    if (!element || typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver(() => {
      if (stuck.current) toBottom(false)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [toBottom])

  function onScroll() {
    const element = scroller.current
    if (!element) return
    const near = element.scrollHeight - element.scrollTop - element.clientHeight <= STICK_THRESHOLD
    stuck.current = near
    setAtBottom(near)
  }

  const hasMessages = React.Children.toArray(children).length > 0

  return (
    <div data-slot="chat-conversation" className={cn("relative flex min-h-0 flex-1 flex-col", className)}>
      <div
        ref={scroller}
        role="log"
        tabIndex={0}
        aria-label={t("Conversation")}
        aria-live="polite"
        aria-relevant="additions text"
        onScroll={onScroll}
        className="scroll-thin focus-visible:ring-ring/30 flex-1 overflow-y-auto outline-none focus-visible:ring-3"
      >
        <div ref={content} className="mx-auto flex min-h-full w-full max-w-3xl flex-col gap-6 px-4 py-6">
          {hasMessages ? children : empty}
        </div>
      </div>
      {!atBottom && (
        <Button
          variant="outline"
          size="sm"
          className="absolute bottom-3 left-1/2 -translate-x-1/2 shadow-md"
          onClick={() => {
            stuck.current = true
            toBottom(true)
          }}
        >
          <ArrowDown />
          {t("Last message")}
        </Button>
      )}
    </div>
  )
}

export { ChatConversation }
