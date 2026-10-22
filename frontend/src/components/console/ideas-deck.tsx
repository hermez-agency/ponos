import * as React from "react"
import { Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

import { Robot } from "./robot"

/* The button that opens Ponos's pile of ideas, on the dashboard and on a
 * project's page. The pile itself is fetched the first time it is opened
 * rather than with the console (see `ideas-dialog.tsx`): it weighs enough to
 * push the first load past its budget (see
 * `the_console_is_downloaded_once_and_compressed`), and a board you only work
 * on never opens it.
 */

const IdeasDialog = React.lazy(() => import("./ideas-dialog").then((module) => ({ default: module.IdeasDialog })))

/** The dashboard's look for a button that starts something with Ponos: the one
 * every page shares, so that none of them has a style of its own. */
export const ponosActionLook =
  "border-primary/30 text-primary bg-card hover:bg-accent hover:text-primary dark:border-primary/30 dark:bg-primary/10 dark:hover:bg-primary/20 h-8 gap-1.5"

export function IdeasButton({
  project = "",
  name = "",
  onClose,
  inline = false,
  className,
}: {
  /** The project's page; none for the workspace. */
  project?: string
  /** And its name, for the cards. */
  name?: string
  /** Once the deck is closed: what it decided may change a list drawn behind it. */
  onClose?: () => void
  /** Drawn at the end of the runner's strip: a quiet icon button the strip's
   * height, the mascot alone and its words in a tooltip — so the strip's one
   * line stays the figures', not a second call for attention beside them. */
  inline?: boolean
  className?: string
}) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  // Ponos "thinks" while the button is hovered or focused. Under
  // prefers-reduced-motion it keeps its resting pose: the mascot freezes its
  // own animations, but a pose that changes is still a movement.
  const [eager, setEager] = React.useState(false)
  const wake = (on: boolean) =>
    setEager(on && !window.matchMedia("(prefers-reduced-motion: reduce)").matches)
  const label = t("Ponos, find me ideas")
  const mascot = (
    <span className="relative inline-flex shrink-0">
      <Robot state={eager ? "thinking" : "idle"} size={inline ? 20 : 24} />
      <Sparkles
        aria-hidden="true"
        className="absolute -top-0.5 -right-1 size-3 opacity-0 group-hover/ideas:opacity-100 group-focus-visible/ideas:opacity-100 motion-safe:group-hover/ideas:animate-pulse motion-safe:group-focus-visible/ideas:animate-pulse"
      />
    </span>
  )
  const shared = {
    "data-slot": project ? "project-ideas-button" : "ideas-button",
    onClick: () => setOpen(true),
    onPointerEnter: () => wake(true),
    onPointerLeave: () => wake(false),
    onFocus: () => wake(true),
    onBlur: () => wake(false),
  } as const
  const button = inline ? (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          size="icon-sm"
          variant="ghost"
          className={cn("group/ideas text-primary hover:text-primary hover:bg-primary/10", className)}
          aria-label={label}
          {...shared}
        >
          {mascot}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  ) : (
    <Button
      size="sm"
      variant="outline"
      className={cn("group/ideas", ponosActionLook, "pr-3 pl-1", className)}
      {...shared}
    >
      {mascot}
      <span>{label}</span>
    </Button>
  )
  return (
    <>
      {button}
      {open ? (
        <React.Suspense fallback={null}>
          <IdeasDialog
            project={project}
            name={name}
            onClose={() => {
              setOpen(false)
              onClose?.()
            }}
          />
        </React.Suspense>
      ) : null}
    </>
  )
}

