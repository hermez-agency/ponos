import * as React from "react"
import { ClockIcon } from "lucide-react"
import { Link } from "react-resource-view"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useConsole } from "@/hooks/use-console"
import { api, why } from "@/lib/api"
import { currentLanguage, useT } from "@/lib/i18n"
import { setOpenChat, useOpenChat } from "@/lib/open-chat"
import { closeTalk } from "@/lib/talk"
import type { ChatSession } from "@/lib/types"
import { sessionsHref } from "@/resources/sessions"

import { SessionFlag } from "./session-flag"

/* The latest conversations, one click from the one that is open.
 *
 * Read when the menu opens and not before: the list is only wanted by whoever
 * asks for it, and the sessions page, a click away at the bottom, is where the
 * rest are searched, renamed and deleted. Opening one swaps the transcript
 * through the stream, as it does from that page. */

const LATEST = 12

/** The date of a conversation's last message, short enough for a menu. */
function when(stamp: string): string {
  const date = new Date(stamp)
  if (Number.isNaN(date.getTime())) return ""
  return date.toLocaleString(currentLanguage(), { dateStyle: "medium", timeStyle: "short" })
}

export function TalkHistory() {
  const t = useT()
  const openId = useOpenChat()
  const { elsewhere, activity } = useConsole()
  const [sessions, setSessions] = React.useState<ChatSession[] | null>(null)
  const [problem, setProblem] = React.useState("")
  const [shown, setShown] = React.useState(false)

  const read = async (open: boolean) => {
    setShown(open)
    if (!open) return
    try {
      setSessions((await api.sessions("")).sessions)
      setProblem("")
    } catch (error) {
      setProblem(why(error))
    }
  }

  // The menu is open while a conversation answers: its flags follow.
  React.useEffect(() => {
    if (shown) void read(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `read` is the menu's own, changed by every render
  }, [activity])

  // Following another conversation is this tab's own business: the one left
  // goes on answering, and the list says so.
  const open = (session: ChatSession) => setOpenChat(session.id)
  const flagged = elsewhere.busy + elsewhere.unread > 0

  return (
    <DropdownMenu onOpenChange={(next) => void read(next)}>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("Conversations")}
              className="relative opacity-70 hover:opacity-100"
              data-talk-history
              data-elsewhere={flagged || undefined}
            >
              <ClockIcon />
              {flagged ? (
                <span
                  aria-hidden
                  className={`bg-primary absolute top-1 right-1 size-1.5 rounded-full ${elsewhere.busy ? "animate-pulse" : ""}`}
                />
              ) : null}
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent side="bottom">{t("Conversations")}</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-80 max-w-[calc(100vw-2rem)]">
        <p className="text-muted-foreground px-2 py-1.5 text-xs font-medium">{t("Conversations")}</p>
        {problem ? (
          <p role="alert" className="text-destructive px-2 py-1.5 text-sm">
            {problem}
          </p>
        ) : sessions === null ? (
          <p className="text-muted-foreground px-2 py-1.5 text-sm">{t("Reading the conversations…")}</p>
        ) : sessions.length === 0 ? (
          <p className="text-muted-foreground px-2 py-1.5 text-sm">{t("No conversation yet.")}</p>
        ) : (
          <div className="scroll-thin max-h-72 overflow-y-auto">
            {sessions.slice(0, LATEST).map((session) => (
              <DropdownMenuItem
                key={session.id}
                className="flex-col items-start gap-0"
                aria-current={session.id === openId || undefined}
                onSelect={() => void open(session)}
                data-session={session.id}
              >
                <span className="flex w-full items-center gap-2">
                  <span className="truncate font-medium">
                    {session.title || t("Untitled conversation")}
                  </span>
                  {session.id === openId ? null : <SessionFlag session={session} />}
                </span>
                <span className="text-muted-foreground text-xs">
                  {when(session.updated)}
                  {session.id === openId ? ` · ${t("open")}` : ""}
                </span>
              </DropdownMenuItem>
            ))}
          </div>
        )}
        <div role="separator" className="bg-border -mx-1 my-1 h-px" />
        <DropdownMenuItem asChild>
          <Link to={sessionsHref()} onClick={closeTalk}>
            {t("Conversations")}
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
