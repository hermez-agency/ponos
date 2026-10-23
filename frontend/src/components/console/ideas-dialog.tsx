import * as React from "react"
import { Heart, Sparkles, Undo2, X } from "lucide-react"
import { useNavigate } from "react-resource-view"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { exitOffset, lean, sideOfKey, stamp, verdict, type Side } from "@/lib/swipe"
import type { Idea } from "@/lib/types"
import { cn } from "@/lib/utils"
import { projectHref } from "@/resources/projects"
import { ticketHref } from "@/resources/tickets"

import { IdeaOrigin } from "./idea-origin"
import { Byline, CategoryBadge, ScoreBadge } from "./idea-cards"
import { Robot } from "./robot"
import { ScopedIdeas } from "./scoped-ideas"

/* Ideas, one card at a time.
 *
 * A pile of cards in a dialog — full screen on a phone, where it is meant to
 * be used with a thumb. Right keeps, left throws away: dragged with a finger or
 * the mouse, pressed on the two buttons under the pile, or the arrow keys, which
 * are the same decision made four ways and go through the same `decide`.
 *
 * A decision is optimistic. The card leaves at once and the server is told after
 * it, one request at a time and in the order the cards left: keeping writes a
 * page to the board, which takes as long as the board takes, and a pile you have
 * to wait on is not one you can swipe through. A request that fails puts the
 * card back and says why.
 *
 * Who opens it says the scope: the dashboard's button asks for the workspace's
 * ideas, a project's page for that project's. Opening it is asking for ideas, so
 * a pile with nothing in it is filled before anything else is shown.
 *
 * Keeping a card here turns it into a ticket at once — the deck is for deciding
 * quickly. Keeping one for later without a ticket, throwing it away, making it
 * new again, or writing one by hand is the list's, the deck's second tab (see
 * `scoped-ideas.tsx`), which holds every idea of the scope, thrown ones included.
 */

type Phase = "loading" | "finding" | "ready" | "failed"

/** The flight of a card that has been decided, in ms: long enough to be seen. */
const FLIGHT = 220

export function IdeasDialog({
  project,
  name,
  onClose,
}: {
  project: string
  name: string
  onClose: () => void
}) {
  const t = useT()
  const navigate = useNavigate()
  const [phase, setPhase] = React.useState<Phase>("loading")
  const [problem, setProblem] = React.useState("")
  const [pile, setPile] = React.useState<Idea[]>([])
  const [canUndo, setCanUndo] = React.useState(false)
  const [tab, setTab] = React.useState("ideas")
  // The card in flight, and where to.
  const [leaving, setLeaving] = React.useState<{ id: number; side: Side } | null>(null)
  const focus = React.useRef<HTMLDivElement>(null)
  const requests = React.useRef<Promise<unknown>>(Promise.resolve())
  const alive = React.useRef(true)
  React.useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  /** The next batch, added to what is left of the pile. */
  const find = React.useCallback(async () => {
    setPhase("finding")
    setProblem("")
    try {
      const found = await api.findIdeas(project)
      if (!alive.current) return
      setPile((now) => [...now, ...found.ideas])
      setProblem(found.ideas.length ? "" : found.error)
      setPhase(found.ideas.length || !found.error ? "ready" : "failed")
    } catch (error) {
      if (!alive.current) return
      setProblem(why(error))
      setPhase("failed")
    }
    refreshHistory()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project])

  const refreshHistory = React.useCallback(async () => {
    try {
      const read = await api.ideas(project)
      if (!alive.current) return
      setCanUndo(read.undo !== null)
    } catch {
      // Whether Undo is offered is a nicety: the pile does not wait on it.
    }
  }, [project])

  React.useEffect(() => {
    void (async () => {
      try {
        const read = await api.ideas(project)
        if (!alive.current) return
        setPile(read.ideas)
        setCanUndo(read.undo !== null)
        if (read.ideas.length) setPhase("ready")
        else void find()
      } catch (error) {
        if (!alive.current) return
        setProblem(why(error))
        setPhase("failed")
      }
    })()
  }, [project, find])

  // The arrows work as soon as the pile is there, with no card to click first.
  React.useEffect(() => {
    if (phase === "ready" && tab === "ideas") focus.current?.focus({ preventScroll: true })
  }, [phase, tab, pile.length === 0])

  /** Tells the server, after whatever was decided before this. */
  const tell = (run: () => Promise<unknown>, fail: () => void) => {
    requests.current = requests.current.then(run).catch((error) => {
      toast.error(t("The decision could not be saved"), { description: why(error) })
      if (alive.current) fail()
    })
  }

  const decide = (side: Side) => {
    const card = pile[0]
    if (!card || leaving) return
    setLeaving({ id: card.id, side })
    window.setTimeout(() => {
      setLeaving(null)
      setPile((now) => now.filter((idea) => idea.id !== card.id))
      setCanUndo(true)
    }, FLIGHT)
    if (side === "keep") {
      tell(
        async () => {
          const kept = await api.ticketIdea(card.id)
          const target = card.kind === "project" ? kept.created : kept.ticket
          toast.success(
            card.kind === "project"
              ? t("Project created: {{title}}", { title: card.title })
              : t("Ticket created: {{title}}", { title: card.title }),
            target
              ? {
                  action: {
                    label: card.kind === "project" ? t("Open the project") : t("Open the ticket"),
                    onClick: () => {
                      onClose()
                      void navigate({
                        to: card.kind === "project" ? projectHref(target) : ticketHref(target),
                      })
                    },
                  },
                }
              : undefined
          )
          void refreshHistory()
        },
        () => {
          setPile((now) => [card, ...now])
          void refreshHistory()
        }
      )
    } else {
      tell(
        async () => {
          await api.discardIdea(card.id)
          void refreshHistory()
        },
        () => setPile((now) => [card, ...now])
      )
    }
  }

  const undo = () => {
    if (leaving) return
    tell(
      async () => {
        const back = await api.undoIdea(project)
        if (!alive.current) return
        setPile((now) => [back.idea, ...now.filter((idea) => idea.id !== back.idea.id)])
        setPhase("ready")
        await refreshHistory()
      },
      () => undefined
    )
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (tab !== "ideas" || phase !== "ready") return
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault()
      if (canUndo) undo()
      return
    }
    if (event.ctrlKey || event.metaKey || event.altKey) return
    // A tab trigger has its own use for the arrows.
    if ((event.target as HTMLElement).closest('[role="tab"]')) return
    const side = sideOfKey(event.key)
    if (!side) return
    event.preventDefault()
    decide(side)
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        data-slot="ideas-dialog"
        className="flex flex-col gap-3 max-sm:top-0 max-sm:left-0 max-sm:h-dvh max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none max-sm:border-0 sm:h-[85dvh] sm:max-h-[85dvh] sm:max-w-[44rem]"
        closeLabel={t("Close")}
        onKeyDown={onKeyDown}
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          focus.current?.focus({ preventScroll: true })
        }}
      >
        <DialogTitle className="flex items-center gap-2 pr-6">
          <Sparkles className="size-4" />
          {project && name ? t("Ideas for {{name}}", { name }) : t("Ideas")}
        </DialogTitle>
        <DialogDescription className="sr-only">
          {t("Swipe right to keep an idea, left to throw it away.")}
        </DialogDescription>
        <Tabs value={tab} onValueChange={setTab} className="min-h-0 flex-1 gap-3">
          <TabsList className="w-full">
            <TabsTrigger value="ideas" data-slot="ideas-pile-tab">
              {t("Swipe")}
            </TabsTrigger>
            <TabsTrigger value="history" data-slot="ideas-history-tab">
              {t("All ideas")}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="ideas" className="flex min-h-0 flex-1 flex-col outline-none">
            <div
              ref={focus}
              tabIndex={-1}
              className="flex min-h-0 flex-1 flex-col gap-3 outline-none"
            >
              {phase === "loading" || phase === "finding" ? (
                <Waiting />
              ) : phase === "failed" ? (
                <Failed problem={problem} onRetry={() => void find()} />
              ) : pile.length === 0 ? (
                <Finished onMore={() => void find()} />
              ) : (
                <Pile pile={pile} name={name} leaving={leaving} onDecide={decide} />
              )}
              {phase === "ready" && pile.length ? (
                <p className="text-muted-foreground text-center text-xs">
                  {t("Swipe right to keep, left to throw away.")}
                </p>
              ) : null}
              <Controls
                disabled={phase !== "ready" || pile.length === 0 || leaving !== null}
                canUndo={canUndo && !leaving}
                onDecide={decide}
                onUndo={undo}
              />
              {phase === "ready" && pile.length ? (
                <p
                  data-slot="ideas-shortcuts"
                  className="text-muted-foreground hidden text-center text-xs sm:block"
                >
                  {t("← throw away · → keep · Ctrl/Cmd+Z undo")}
                </p>
              ) : null}
            </div>
          </TabsContent>
          <TabsContent value="history" className="min-h-0 flex-1 overflow-y-auto">
            <ScopedIdeas project={project} name={name} every />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}

/* -- the states of the pile ------------------------------------------------ */

function Waiting() {
  const t = useT()
  return (
    <div
      data-slot="ideas-waiting"
      role="status"
      className="flex flex-1 flex-col items-center justify-center gap-3 py-8"
    >
      {/* Eyes up, the flame in a draught: the mascot's own "thinking". */}
      <Robot state="thinking" size={96} />
      <p className="text-muted-foreground text-sm">{t("Ponos is looking for ideas…")}</p>
    </div>
  )
}

function Failed({ problem, onRetry }: { problem: string; onRetry: () => void }) {
  const t = useT()
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 py-8 text-center">
      <Robot state="error" size={80} />
      <p className="text-destructive text-sm">{t("No ideas could be found.")}</p>
      {problem ? <p className="text-muted-foreground font-mono text-xs">{problem}</p> : null}
      <Button size="sm" onClick={onRetry}>
        {t("Try again")}
      </Button>
    </div>
  )
}

function Finished({ onMore }: { onMore: () => void }) {
  const t = useT()
  return (
    <div
      data-slot="ideas-finished"
      className="flex flex-1 flex-col items-center justify-center gap-3 py-8 text-center"
    >
      <Robot state="sleep" size={96} />
      <p className="text-lg font-medium">{t("No more ideas")}</p>
      <Button onClick={onMore} data-slot="ideas-more">
        {t("Ten more")}
      </Button>
    </div>
  )
}

/* -- the cards ------------------------------------------------------------- */

function Pile({
  pile,
  name,
  leaving,
  onDecide,
}: {
  pile: Idea[]
  name: string
  leaving: { id: number; side: Side } | null
  onDecide: (side: Side) => void
}) {
  // Three at most are drawn: the others are under them and cannot be seen.
  const shown = pile.slice(0, 3)
  return (
    <div
      data-slot="ideas-pile"
      className="relative mx-auto min-h-72 w-full max-w-xl flex-1"
    >
      {shown
        .map((idea, depth) => (
          <Card
            key={idea.id}
            idea={idea}
            name={name}
            depth={depth}
            leaving={leaving?.id === idea.id ? leaving.side : null}
            onDecide={onDecide}
          />
        ))
        .reverse()}
    </div>
  )
}

function Card({
  idea,
  name,
  depth,
  leaving,
  onDecide,
}: {
  idea: Idea
  name: string
  depth: number
  leaving: Side | null
  onDecide: (side: Side) => void
}) {
  const t = useT()
  const element = React.useRef<HTMLDivElement>(null)
  const start = React.useRef<{ x: number; y: number; at: number; id: number } | null>(null)
  const last = React.useRef({ x: 0, at: 0, speed: 0 })
  const [drag, setDrag] = React.useState({ x: 0, y: 0 })
  const [held, setHeld] = React.useState(false)
  const top = depth === 0
  const width = () => element.current?.offsetWidth ?? 0

  const onPointerDown = (event: React.PointerEvent) => {
    if (!top || leaving) return
    start.current = { x: event.clientX, y: event.clientY, at: event.timeStamp, id: event.pointerId }
    last.current = { x: event.clientX, at: event.timeStamp, speed: 0 }
    element.current?.setPointerCapture(event.pointerId)
    setHeld(true)
  }
  const onPointerMove = (event: React.PointerEvent) => {
    const from = start.current
    if (!from) return
    const elapsed = event.timeStamp - last.current.at
    if (elapsed > 0) {
      // Smoothed, so that one late frame does not read as a flick.
      const speed = (event.clientX - last.current.x) / elapsed
      last.current = { x: event.clientX, at: event.timeStamp, speed: last.current.speed * 0.5 + speed * 0.5 }
    }
    setDrag({ x: event.clientX - from.x, y: (event.clientY - from.y) * 0.3 })
  }
  const release = (event: React.PointerEvent) => {
    const from = start.current
    if (!from) return
    start.current = null
    setHeld(false)
    if (element.current?.hasPointerCapture(from.id)) element.current.releasePointerCapture(from.id)
    const side = event.type === "pointercancel" ? null : verdict(drag.x, width(), last.current.speed)
    if (side) onDecide(side)
    else setDrag({ x: 0, y: 0 })
  }

  const flying = leaving !== null
  const x = flying ? exitOffset(leaving, width(), window.innerWidth) : drag.x
  const angle = flying ? (leaving === "keep" ? 22 : -22) : lean(drag.x, width())
  const mark = flying ? { side: leaving, strength: 1 } : stamp(drag.x, width())
  // The cards underneath come forward a little as the one on top leaves.
  const scale = 1 - depth * 0.05
  const rise = depth * 10

  return (
    <div
      ref={element}
      data-slot="ideas-card"
      data-depth={depth}
      data-idea={idea.id}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={release}
      onPointerCancel={release}
      className={cn(
        "bg-card text-card-foreground absolute inset-0 flex touch-pan-y flex-col gap-3 overflow-hidden rounded-xl border p-5 shadow-md select-none",
        top && "cursor-grab active:cursor-grabbing",
        !top && "pointer-events-none"
      )}
      style={{
        transform: top
          ? `translate(${x}px, ${drag.y}px) rotate(${angle}deg)`
          : `translateY(${rise}px) scale(${scale})`,
        transition: held ? "none" : `transform ${FLIGHT}ms ease-out`,
        zIndex: 3 - depth,
      }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <ScoreBadge idea={idea} />
        <Badge variant={idea.kind === "project" ? "default" : "secondary"} data-slot="ideas-kind">
          {idea.kind === "project" ? t("New project") : t("Ticket")}
        </Badge>
        <CategoryBadge category={idea.category} />
        <IdeaOrigin project={idea.kind === "project" ? "" : idea.project} name={name} />
      </div>
      {/* The idea in full: what does not fit scrolls here, and only here — the
          badges above stay in view. The card keeps `touch-pan-y`, so a finger moving
          up or down scrolls this and a finger moving sideways drags the card. */}
      <div
        data-slot="ideas-card-body"
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain"
      >
        <h3 className="text-xl leading-snug font-semibold tracking-tight">{idea.title}</h3>
        <p className="text-muted-foreground text-sm leading-relaxed whitespace-pre-line">
          {idea.description}
        </p>
        {idea.score !== null && idea.score_reason ? (
          <p className="text-muted-foreground text-xs italic" data-slot="ideas-card-score-reason">
            {idea.score_reason}
          </p>
        ) : null}
        <div className="mt-auto">
          <Byline author={idea.author} when={idea.created_at} />
        </div>
      </div>
      {top ? (
        <>
          <Stamp side="keep" shown={mark.side === "keep" ? mark.strength : 0} />
          <Stamp side="discard" shown={mark.side === "discard" ? mark.strength : 0} />
        </>
      ) : null}
    </div>
  )
}

/** The mark that appears on a card as it is dragged: green to keep, red to throw away. */
function Stamp({ side, shown }: { side: Side; shown: number }) {
  const t = useT()
  const keep = side === "keep"
  return (
    <span
      data-slot={keep ? "ideas-stamp-keep" : "ideas-stamp-discard"}
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute top-14 rounded-md border-4 px-2 py-0.5 text-lg font-extrabold tracking-wider uppercase",
        keep
          ? "left-4 -rotate-12 border-green-500 text-green-500"
          : "right-4 rotate-12 border-red-500 text-red-500"
      )}
      style={{ opacity: shown }}
    >
      {keep ? t("Kept") : t("Thrown")}
    </span>
  )
}

/* -- the buttons ------------------------------------------------------------ */

function Controls({
  disabled,
  canUndo,
  onDecide,
  onUndo,
}: {
  disabled: boolean
  canUndo: boolean
  onDecide: (side: Side) => void
  onUndo: () => void
}) {
  const t = useT()
  return (
    <div className="flex items-center justify-center gap-4 pb-1">
      <Button
        variant="outline"
        size="icon"
        className="size-14 rounded-full border-red-500/50 text-red-500 hover:text-red-500"
        data-slot="ideas-discard"
        aria-label={t("Throw away")}
        disabled={disabled}
        onClick={() => onDecide("discard")}
      >
        <X className="size-6" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        data-slot="ideas-undo"
        disabled={!canUndo}
        onClick={onUndo}
      >
        <Undo2 />
        {t("Undo")}
      </Button>
      <Button
        variant="outline"
        size="icon"
        className="size-14 rounded-full border-green-500/50 text-green-500 hover:text-green-500"
        data-slot="ideas-keep"
        aria-label={t("Keep")}
        disabled={disabled}
        onClick={() => onDecide("keep")}
      >
        <Heart className="size-6" />
      </Button>
    </div>
  )
}
