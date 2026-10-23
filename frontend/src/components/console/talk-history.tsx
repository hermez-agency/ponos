import * as React from "react"
import { ClockIcon } from "lucide-react"
import { Link } from "react-resource-view"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api, why } from "@/lib/api"
import { currentLanguage, useT } from "@/lib/i18n"
import { closeTalk } from "@/lib/talk"
import type { ChatSession } from "@/lib/types"
import { sessionsHref } from "@/resources/sessions"

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

export function TalkHistory({ disabled }: { disabled: boolean }) {
  const t = useT()
  const [sessions, setSessions] = React.useState<ChatSession[] | null>(null)
  const [problem, setProblem] = React.useState("")

  const read = async (open: boolean) => {
    if (!open) return
    try {
      setSessions((await api.sessions("")).sessions)
      setProblem("")
    } catch (error) {
      setProblem(why(error))
    }
  }

  const open = async (session: ChatSession) => {
    if (session.current) return
    try {
      await api.openSession(session.id)
    } catch (error) {
      toast.error(t("The session could not be opened"), { description: why(error) })
    }
  }

  return (
    <DropdownMenu onOpenChange={(next) => void read(next)}>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              className="opacity-70 hover:opacity-100"
              aria-label={t("Sessions")}
              disabled={disabled}
              data-talk-history
            >
              <ClockIcon />
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent side="bottom">{t("Sessions")}</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-80 max-w-[calc(100vw-2rem)]">
        <p className="text-muted-foreground px-2 py-1.5 text-xs font-medium">{t("Sessions")}</p>
        {problem ? (
          <p role="alert" className="text-destructive px-2 py-1.5 text-sm">
            {problem}
          </p>
        ) : sessions === null ? (
          <p className="text-muted-foreground px-2 py-1.5 text-sm">{t("Reading the sessions…")}</p>
        ) : sessions.length === 0 ? (
          <p className="text-muted-foreground px-2 py-1.5 text-sm">{t("No session yet.")}</p>
        ) : (
          <div className="scroll-thin max-h-72 overflow-y-auto">
            {sessions.slice(0, LATEST).map((session) => (
              <DropdownMenuItem
                key={session.id}
                className="flex-col items-start gap-0"
                aria-current={session.current || undefined}
                onSelect={() => void open(session)}
                data-session={session.id}
              >
                <span className="w-full truncate font-medium">
                  {session.title || t("Untitled session")}
                </span>
                <span className="text-muted-foreground text-xs">
                  {when(session.updated)}
                  {session.current ? ` · ${t("open")}` : ""}
                </span>
              </DropdownMenuItem>
            ))}
          </div>
        )}
        <div role="separator" className="bg-border -mx-1 my-1 h-px" />
        <DropdownMenuItem asChild>
          <Link to={sessionsHref()} onClick={closeTalk}>
            {t("Sessions")}
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
