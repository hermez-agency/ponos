import * as React from "react"
import { MessageSquare, MoreHorizontal, Pencil, Plus, Search, SearchX, Trash2, X } from "lucide-react"
import { useCurrentViewResourceContext } from "react-resource-view"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { EmptyState } from "@/components/console/empty-state"
import { PageHead } from "@/components/console/frame"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useConsole } from "@/hooks/use-console"
import { api, why } from "@/lib/api"
import { counted, currentLanguage, useT } from "@/lib/i18n"
import type { ChatSession } from "@/lib/types"
import { cn } from "@/lib/utils"

import { openTalk } from "@/lib/talk"

/* Every conversation the console has kept, the latest first.
 *
 * The drawer is where a conversation happens; this is where one is found again.
 * A row opens its session in the drawer — the whole transcript, and Claude Code
 * resumes where it stopped — and the search looks in the titles and, failing
 * that, in what was said, telling the two apart so that a row without the
 * words in its title does not read as a mistake.
 *
 * Deleting asks for the box to be ticked, as deleting a project does: the
 * session, its transcript and the files dropped in it go, and nothing brings
 * them back. Claude Code's own record of the session stays on the machine. */

export function SessionsPage() {
  const t = useT()
  const { runner } = useConsole()
  const Icon = useCurrentViewResourceContext().resource?.icon
  const [query, setQuery] = React.useState("")
  const [sessions, setSessions] = React.useState<ChatSession[] | null>(null)
  const [problem, setProblem] = React.useState("")
  const [renaming, setRenaming] = React.useState<ChatSession | null>(null)
  const [deleting, setDeleting] = React.useState<ChatSession | null>(null)

  const chat = runner?.chat
  const read = React.useCallback(
    async (words: string) => {
      try {
        const payload = await api.sessions(words)
        setSessions(payload.sessions)
        setProblem("")
      } catch (error) {
        setProblem(why(error))
      }
    },
    []
  )

  // Read again when what the open session says about itself changes — a
  // first message gave it a title, an answer moved its date — and, after a
  // pause, as the words are typed.
  React.useEffect(() => {
    const timer = window.setTimeout(() => void read(query), query ? 250 : 0)
    return () => window.clearTimeout(timer)
  }, [query, read, chat?.id, chat?.title, chat?.turns, chat?.model, chat?.project])

  const open = async (session: ChatSession) => {
    try {
      await api.openSession(session.id)
      openTalk()
    } catch (error) {
      toast.error(t("The session could not be opened"), { description: why(error) })
    }
  }

  const start = async () => {
    try {
      await api.resetChat()
      openTalk()
    } catch (error) {
      toast.error(t("The session could not be opened"), { description: why(error) })
    }
  }

  const newSession = (
    <Button variant="secondary" size="lg" className="w-full min-w-0 shrink md:w-auto" onClick={() => void start()} data-new-session>
      <Plus />
      {t("New session")}
    </Button>
  )

  return (
    <div data-sessions className="flex flex-col gap-2">
      <PageHead
        icon={Icon}
        title={t("Sessions")}
        blurb={t("Every conversation with your workspace. Open one to carry on where it stopped.")}
        action={newSession}
        className="mb-0"
      />

      <div className="relative my-2 max-w-md">
        <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
        <Input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("Search the titles and what was said")}
          className="pl-9"
        />
      </div>

      {problem ? (
        <p role="alert" className="text-destructive text-sm">
          {problem}
        </p>
      ) : sessions === null ? (
        <p className="text-muted-foreground text-sm">{t("Reading the sessions…")}</p>
      ) : sessions.length === 0 ? (
        query ? (
          <EmptyState
            icon={SearchX}
            title={t("No session matches.")}
            action={
              <Button variant="outline" size="sm" onClick={() => setQuery("")}>
                <X />
                {t("Clear the search")}
              </Button>
            }
          >
            {t("Other words, and they will be back.")}
          </EmptyState>
        ) : (
          <EmptyState
            robot="sleep"
            title={t("No session yet.")}
            action={
              <Button variant="outline" size="sm" onClick={() => void start()}>
                <Plus />
                {t("New session")}
              </Button>
            }
          >
            {t("Every conversation with your workspace is kept here, to be carried on later.")}
          </EmptyState>
        )
      ) : (
        <ul className="divide-y rounded-lg border" data-session-list>
          {sessions.map((session) => (
            <li key={session.id} className="group flex items-center gap-1 pr-2" data-session={session.id}>
              <button
                type="button"
                onClick={() => void open(session)}
                className={cn(
                  "hover:bg-accent focus-visible:ring-ring/30 flex min-w-0 flex-1 items-start gap-3 rounded-lg px-4 py-3 text-left outline-hidden focus-visible:ring-2",
                  session.current && "bg-accent/40"
                )}
              >
                <MessageSquare className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium">
                      {session.title || t("Untitled session")}
                    </span>
                    {session.current ? <Badge variant="secondary">{t("open")}</Badge> : null}
                  </span>
                  <span className="text-muted-foreground mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
                    <span>{when(session.updated)}</span>
                    <span className="font-mono">{session.model || t("Default model")}</span>
                    {session.project ? <span>{session.project}</span> : null}
                    <span>
                      {counted(session.turns, "{{count}} exchange", "{{count}} exchanges")}
                    </span>
                    {session.matched === "content" ? (
                      <span className="italic">{t("found in the conversation")}</span>
                    ) : null}
                  </span>
                </span>
              </button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="text-muted-foreground"
                    aria-label={t("More actions on “{{name}}”", { name: session.title || t("Untitled session") })}
                    data-session-menu
                  >
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => setRenaming(session)}>
                    <Pencil />
                    {t("Rename")}
                  </DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(session)}>
                    <Trash2 />
                    {t("Delete")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </li>
          ))}
        </ul>
      )}

      <RenameDialog
        session={renaming}
        onClose={() => setRenaming(null)}
        onDone={() => void read(query)}
      />
      <DeleteDialog
        session={deleting}
        onClose={() => setDeleting(null)}
        onDone={() => void read(query)}
      />
    </div>
  )
}

/** The date of a session's last message, in the language of the page. */
function when(stamp: string): string {
  const date = new Date(stamp)
  if (Number.isNaN(date.getTime())) return ""
  return date.toLocaleString(currentLanguage(), { dateStyle: "medium", timeStyle: "short" })
}

/* Radix refuses an empty value: this stands for “no project”. */
const NO_PROJECT = "__none__"

/* The title, and the project the session is about: the two words a person
 * gives a conversation to find it again. */
function RenameDialog({
  session,
  onClose,
  onDone,
}: {
  session: ChatSession | null
  onClose: () => void
  onDone: () => void
}) {
  const t = useT()
  const { projects } = useConsole()
  const [title, setTitle] = React.useState("")
  const [project, setProject] = React.useState(NO_PROJECT)
  const [refused, setRefused] = React.useState("")

  React.useEffect(() => {
    setTitle(session?.title ?? "")
    setProject(session?.project || NO_PROJECT)
    setRefused("")
  }, [session])

  const confirm = async () => {
    if (!session) return false
    try {
      if (title.trim() !== session.title) await api.renameSession(session.id, title)
      if (project !== (session.project || NO_PROJECT))
        await api.linkSession(session.id, project === NO_PROJECT ? "" : project)
      onDone()
    } catch (error) {
      setRefused(why(error))
      return false
    }
  }

  return (
    <ConfirmDialog
      open={session !== null}
      onOpenChange={(next) => (next ? undefined : onClose())}
      title={t("Rename")}
      confirm={t("Save")}
      disabled={!title.trim()}
      onConfirm={confirm}
    >
      <Input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        maxLength={200}
        data-session-title
      />
      <Label className="flex-col items-start gap-1.5 text-sm font-normal">
        {t("Project")}
        <Select value={project} onValueChange={setProject}>
          <SelectTrigger className="w-full" data-session-project>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_PROJECT}>{t("No project")}</SelectItem>
            {session?.project && !projects.some((item) => item.name === session.project) ? (
              <SelectItem value={session.project}>{session.project}</SelectItem>
            ) : null}
            {projects.map((item) => (
              <SelectItem key={item.id || item.name} value={item.name}>
                {item.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Label>
      {refused ? (
        <p role="alert" className="text-destructive text-sm">
          {refused}
        </p>
      ) : null}
    </ConfirmDialog>
  )
}

function DeleteDialog({
  session,
  onClose,
  onDone,
}: {
  session: ChatSession | null
  onClose: () => void
  onDone: () => void
}) {
  const t = useT()
  const [sure, setSure] = React.useState(false)
  const [refused, setRefused] = React.useState("")

  React.useEffect(() => {
    setSure(false)
    setRefused("")
  }, [session])

  const confirm = async () => {
    if (!session || !sure) return false
    try {
      await api.deleteSession(session.id)
      toast.success(t("Session “{{name}}” deleted", { name: session.title || t("Untitled session") }))
      onDone()
    } catch (error) {
      setRefused(why(error))
      return false
    }
  }

  return (
    <ConfirmDialog
      open={session !== null}
      onOpenChange={(next) => (next ? undefined : onClose())}
      contentProps={{ "data-delete-session": true } as React.ComponentProps<"div">}
      title={t("Delete “{{name}}”?", { name: session?.title || t("Untitled session") })}
      description={t("Its conversation and the files sent in it are deleted for good.")}
      destructive
      disabled={!sure}
      confirm={
        <>
          <Trash2 />
          {t("Delete the session")}
        </>
      }
      onConfirm={confirm}
    >
      <Label className="border-destructive/40 bg-destructive/5 items-start gap-2.5 rounded-md border p-3 text-sm font-medium">
        <Checkbox
          checked={sure}
          onCheckedChange={(next) => setSure(next === true)}
          className="mt-0.5"
          data-confirm-delete
        />
        <span>{t("Yes, I am sure I want to delete this session")}</span>
      </Label>
      {refused ? (
        <p role="alert" className="text-destructive text-sm">
          {refused}
        </p>
      ) : null}
    </ConfirmDialog>
  )
}
