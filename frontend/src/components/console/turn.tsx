import * as React from "react"

import { Bubble, BubbleContent } from "@/components/ui/bubble"
import { Message, MessageContent, MessageHeader } from "@/components/ui/message"
import { useT } from "@/lib/i18n"
import type { Attached, Role } from "@/lib/types"
import { cn } from "@/lib/utils"

import { AttachedGallery } from "./attachments"
import { Markdown } from "./markdown"
import { Robot } from "./robot"

/** Who said it, before translation — but Ponos is a name, and is not translated. */
const WHO: Record<Role, string> = {
  you: "you",
  workspace: "Ponos",
  runner: "Ponos",
  error: "problem",
  command: "command",
  stopped: "stopped by you",
}

/** The surface a turn is said on, in shadcn's own palette. */
const SURFACE: Record<Role, "tinted" | "outline" | "destructive"> = {
  you: "tinted",
  workspace: "outline",
  runner: "outline",
  error: "destructive",
  command: "outline",
  stopped: "outline",
}

/* One thing that was said, by you or by the other side.
 *
 * shadcn's `Message` lays it out — yours against the right edge, theirs against
 * the left — and `Bubble` draws the surface it is said on, so the palette is the
 * one the components already carry: a problem reads red, the workspace reads as
 * a card, and what you said is tinted with the accent so a transcript can be
 * skimmed for your own turns.
 *
 * What is inside is markdown, because both sides write markdown: a session
 * answers in headings and lists and fenced code, and a bubble that showed the
 * source of that would be asking a reader to parse it themselves.
 *
 * Who said it and when are one line, set in the mono face: they are a stamp on
 * the message, not a sentence in it. What Ponos says — in the console as on a
 * ticket — is signed with its name and its face, the one the sidebar wears:
 * at that size the robot draws its head alone.
 *
 * The words are a step larger and heavier than the console's small print:
 * they are what a reader came for, and the regular weight read thin in the
 * dark theme.
 *
 * What came with it — a screenshot, a clip, a PDF — sits above the words, the
 * way it was written: the file first, then what is to be said about it.
 *
 * Memoised, because a turn once said does not change: the board redraws the
 * console every few seconds, and a transcript of forty turns used to be drawn
 * again with it, every one of them, to say the same thing.
 */
export const Turn = React.memo(function Turn({
  role,
  text,
  attachments,
  who,
  when,
  className,
}: {
  role: Role
  text: string
  attachments?: Attached[]
  who?: string
  when?: string
  className?: string
}) {
  const t = useT()
  const mine = role === "you"
  const ponos = role === "workspace" || role === "runner"
  return (
    <Message align={mine ? "end" : "start"} className={className}>
      <MessageContent>
        <MessageHeader
          className={cn(
            "font-mono text-[0.65rem] font-semibold",
            role === "error" && "text-destructive"
          )}
        >
          {ponos ? (
            <span data-slot="turn-avatar" className="bg-muted mr-1.5 flex size-6 shrink-0 items-center justify-center rounded-full">
              <Robot state="idle" size={18} still />
            </span>
          ) : null}
          {who ?? (ponos ? WHO[role] : t(WHO[role] ?? role))}
          {when ? <span className="font-normal normal-case">{` · ${when}`}</span> : null}
        </MessageHeader>
        {attachments?.length ? (
          <AttachedGallery items={attachments} align={mine ? "end" : "start"} />
        ) : null}
        {text ? (
          <Bubble
            variant={SURFACE[role] ?? "outline"}
            align={mine ? "end" : "start"}
            className="max-w-[92%]"
          >
            {/* Prose stops at a reading width, however wide the drawer is
                pulled; code runs to the edge of the bubble and scrolls. */}
            <BubbleContent className="[&_:is(p,h3,h4,h5,blockquote,div.flex)]:max-w-[80ch]">
              <Markdown text={text} className="text-message font-medium" />
            </BubbleContent>
          </Bubble>
        ) : null}
      </MessageContent>
    </Message>
  )
})
