import * as React from "react"
import { Brain, Check, FileDown, MessageSquare, Pencil, Plus, Ticket, Trash2, X } from "lucide-react"
import { generateLink, Link } from "react-resource-view"
import { ActionList } from "react-data-form"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { api, why } from "@/lib/api"
import { Worded, useT } from "@/lib/i18n"
import { setOpenChat } from "@/lib/open-chat"
import { canAct, isAdmin } from "@/lib/role"
import { SCOPE } from "@/lib/resource-view"
import { settingsFrench } from "@/lib/settings-store"
import { openTalk } from "@/lib/talk"
import type { Memories, Memory, Project } from "@/lib/types"

import { Eyebrow } from "./frame"
import { when } from "./ticket-bits"

/* Context → Memory: what Ponos remembers from one session to the next
 * (`memory.py`).
 *
 * A memory is a short fact with a kind, a scope (everywhere, or one project)
 * and a source. Only an **accepted** one reaches a session's prompt: what a
 * session, the assistant or the MCP proposes waits at the top of the list for
 * a person to accept, edit or refuse it — unless the setting under the list
 * says otherwise. A refused proposal stays known, so it does not come back.
 *
 * Each filter, the search included, is asked of the server: the list is what
 * `GET /api/memories` answers for them. */

const SELECT =
  "border-input bg-background h-9 rounded-md border px-2 text-sm shadow-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"

const KIND_LABELS: Record<string, string> = {
  person: "Person",
  preference: "Preference or instruction",
  project: "Project",
  reference: "Reference",
}

/** The page a memory comes from, when it has one: its ticket, or its conversation. */
function Origin({ memory }: { memory: Memory }) {
  const t = useT()
  if (memory.source === "ticket" && memory.source_ref) {
    return (
      <Link
        to={generateLink({ scope: SCOPE, resourceId: "tickets", resourceAction: ActionList.read, id: memory.source_ref })}
        data-slot="memory-origin"
        className="inline-flex items-center gap-1 underline-offset-2 hover:underline"
      >
        <Ticket className="size-3" />
        {t("From a ticket")}
      </Link>
    )
  }
  if (memory.source === "chat" && memory.source_ref && !memory.source_ref.startsWith("file:")) {
    return (
      <button
        type="button"
        data-slot="memory-origin"
        className="inline-flex items-center gap-1 underline-offset-2 hover:underline"
        onClick={() => {
          setOpenChat(memory.source_ref)
          openTalk()
        }}
      >
        <MessageSquare className="size-3" />
        {t("From a conversation")}
      </button>
    )
  }
  return (
    <span className="inline-flex items-center gap-1">
      {memory.source_ref.startsWith("file:")
        ? t("Imported from the assistant's files")
        : memory.source === "manual"
          ? t("Typed by hand")
          : t("From a conversation")}
    </span>
  )
}

function Editor({
  memory,
  projects,
  limit,
  onDone,
  onSaved,
}: {
  memory?: Memory
  projects: Project[]
  limit: number
  onDone: () => void
  onSaved: (memories: Memories) => void
}) {
  const t = useT()
  const [text, setText] = React.useState(memory?.text ?? "")
  const [kind, setKind] = React.useState(memory?.kind ?? "preference")
  const [scope, setScope] = React.useState(memory ? memory.scope || "global" : "global")
  const [saving, setSaving] = React.useState(false)

  const save = async () => {
    setSaving(true)
    try {
      const values = { text, kind, scope }
      onSaved(memory ? await api.changeMemory(memory.id, values) : await api.addMemory(values))
      onDone()
    } catch (error) {
      toast.error(t("The memory was not saved"), { description: why(error) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      data-slot="memory-editor"
      className="bg-card flex flex-col gap-2 rounded-xl border p-3"
      onSubmit={(event) => {
        event.preventDefault()
        void save()
      }}
    >
      <Textarea
        aria-label={t("The fact")}
        value={text}
        maxLength={limit}
        rows={2}
        placeholder={t("One short fact: a preference, a decision, a constraint, a reference.")}
        onChange={(event) => setText(event.target.value)}
      />
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label={t("Type")} className={SELECT} value={kind} onChange={(event) => setKind(event.target.value)}>
          {Object.entries(KIND_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {t(label)}
            </option>
          ))}
        </select>
        <select aria-label={t("Scope")} className={SELECT} value={scope} onChange={(event) => setScope(event.target.value)}>
          <option value="global">{t("All the projects")}</option>
          {projects
            .filter((project) => project.id)
            .map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
        </select>
        <span className="text-muted-foreground ml-auto font-mono text-[0.7rem]">
          {text.trim().length}/{limit}
        </span>
        <Button type="submit" size="sm" disabled={saving || !text.trim()}>
          {t("Save")}
        </Button>
        <Button type="button" variant="secondary" size="sm" onClick={onDone} disabled={saving}>
          {t("Cancel")}
        </Button>
      </div>
    </form>
  )
}

function MemoryTab() {
  const t = useT()
  const [drawn, setDrawn] = React.useState<Memories | null>(null)
  const [projects, setProjects] = React.useState<Project[]>([])
  const [scope, setScope] = React.useState("")
  const [kind, setKind] = React.useState("")
  const [status, setStatus] = React.useState("")
  const [search, setSearch] = React.useState("")
  const [problem, setProblem] = React.useState("")
  const [adding, setAdding] = React.useState(false)
  const [editing, setEditing] = React.useState<number | null>(null)

  // Several reads can be in flight (a write rereads, a filter changes): only
  // the last asked is drawn, whatever order they come back in.
  const asked = React.useRef(0)
  const read = React.useCallback(async () => {
    const mine = ++asked.current
    try {
      const fresh = await api.memories({ scope, kind, status, search })
      if (mine === asked.current) {
        setDrawn(fresh)
        setProblem("")
      }
    } catch (error) {
      if (mine === asked.current) setProblem(why(error))
    }
  }, [scope, kind, status, search])

  // The search is asked of the server a moment after the last key.
  React.useEffect(() => {
    const timer = window.setTimeout(() => void read(), search ? 250 : 0)
    return () => window.clearTimeout(timer)
  }, [read, search])

  React.useEffect(() => {
    api
      .projects()
      .then((answer) => setProjects(answer.projects))
      .catch(() => setProjects([]))
  }, [])

  const act = async (work: () => Promise<unknown>, done?: string) => {
    try {
      await work()
      // The list is asked again with the filters: a write answers the unfiltered one.
      await read()
      if (done) toast.success(done)
    } catch (error) {
      toast.error(t("That did not work"), { description: why(error) })
    }
  }

  const proposals = (drawn?.memories ?? []).filter((memory) => memory.status === "proposed")
  const others = (drawn?.memories ?? []).filter((memory) => memory.status !== "proposed")
  const mayAct = canAct()

  const row = (memory: Memory) =>
    editing === memory.id ? (
      <li key={memory.id}>
        <Editor
          memory={memory}
          projects={projects}
          limit={drawn?.limit ?? 300}
          onDone={() => setEditing(null)}
          onSaved={() => void read()}
        />
      </li>
    ) : (
      <li
        key={memory.id}
        data-slot="memory-row"
        data-status={memory.status}
        className="bg-card flex flex-col gap-2 rounded-xl border p-3"
      >
        <p className={memory.status === "refused" ? "text-muted-foreground line-through" : ""}>{memory.text}</p>
        <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
          <Badge variant="secondary">{t(KIND_LABELS[memory.kind] ?? memory.kind)}</Badge>
          <Badge variant="outline">{memory.scope ? memory.scope_name : t("All the projects")}</Badge>
          {memory.status === "refused" ? <Badge variant="outline">{t("Refused")}</Badge> : null}
          <Origin memory={memory} />
          <span>{when(memory.updated)}</span>
          {mayAct ? (
            <span className="ml-auto flex items-center gap-1">
              {memory.status === "proposed" ? (
                <>
                  <Button size="sm" onClick={() => void act(() => api.decideMemory(memory.id, "accept"))}>
                    <Check />
                    {t("Accept")}
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void act(() => api.decideMemory(memory.id, "refuse"))}
                  >
                    <X />
                    {t("Refuse")}
                  </Button>
                </>
              ) : null}
              {memory.status === "refused" ? (
                <Button size="sm" variant="secondary" onClick={() => void act(() => api.decideMemory(memory.id, "accept"))}>
                  <Check />
                  {t("Accept")}
                </Button>
              ) : null}
              <Button size="icon-sm" variant="ghost" aria-label={t("Edit")} onClick={() => setEditing(memory.id)}>
                <Pencil />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={t("Delete")}
                onClick={() => void act(() => api.deleteMemory(memory.id), t("Memory deleted"))}
              >
                <Trash2 />
              </Button>
            </span>
          ) : null}
        </div>
      </li>
    )

  return (
    <section data-slot="memory-page" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Eyebrow>{t("Memory")}</Eyebrow>
          <p className="text-muted-foreground mt-1 text-sm">
            {t("What Ponos remembers from one session to the next. Sessions are told the accepted memories of their project and the global ones.")}
          </p>
        </div>
        {mayAct ? (
          <div className="flex gap-2">
            {drawn && drawn.importable > 0 ? (
              <Button
                variant="outline"
                size="sm"
                data-slot="memory-import"
                onClick={() =>
                  void act(api.importMemories, t("Memories imported from the assistant's files"))
                }
              >
                <FileDown />
                {t("Import {{count}} file(s) of the assistant", { count: String(drawn.importable) })}
              </Button>
            ) : null}
            <Button size="sm" onClick={() => setAdding(true)} disabled={adding}>
              <Plus />
              {t("Add a memory")}
            </Button>
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input
          type="search"
          className="max-w-xs"
          aria-label={t("Search the memory")}
          placeholder={t("Search the memory")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select aria-label={t("Filter by scope")} className={SELECT} value={scope} onChange={(event) => setScope(event.target.value)}>
          <option value="">{t("Every scope")}</option>
          <option value="global">{t("All the projects")}</option>
          {projects
            .filter((project) => project.id)
            .map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
        </select>
        <select aria-label={t("Filter by type")} className={SELECT} value={kind} onChange={(event) => setKind(event.target.value)}>
          <option value="">{t("Every type")}</option>
          {Object.entries(KIND_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {t(label)}
            </option>
          ))}
        </select>
        <select aria-label={t("Filter by state")} className={SELECT} value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="">{t("Every state")}</option>
          <option value="accepted">{t("Accepted")}</option>
          <option value="proposed">{t("Waiting")}</option>
          <option value="refused">{t("Refused")}</option>
        </select>
      </div>

      {adding ? (
        <Editor
          projects={projects}
          limit={drawn?.limit ?? 300}
          onDone={() => setAdding(false)}
          onSaved={() => void read()}
        />
      ) : null}

      {problem ? (
        <p className="text-tr-amber border-tr-amber/30 bg-tr-amber/10 rounded-xl border px-4 py-3 text-sm">{problem}</p>
      ) : null}

      {proposals.length ? (
        <div data-slot="memory-proposals" className="flex flex-col gap-2">
          <Eyebrow>{t("Waiting for your word")}</Eyebrow>
          <p className="text-muted-foreground text-xs">{t("No session reads these until you accept them.")}</p>
          <ul className="flex flex-col gap-2">{proposals.map(row)}</ul>
        </div>
      ) : null}

      {others.length ? (
        <ul className="flex flex-col gap-2">{others.map(row)}</ul>
      ) : drawn && !proposals.length ? (
        <p className="text-muted-foreground flex items-center gap-2 rounded-lg border border-dashed px-4 py-3 text-sm">
          <Brain className="size-4 shrink-0" />
          {t("Nothing is remembered yet.")}
        </p>
      ) : null}

      {drawn && isAdmin() ? (
        <label className="flex items-start gap-2 text-sm">
          <Checkbox
            checked={drawn.auto_accept}
            onCheckedChange={(value) => void act(() => api.memoryAutoAccept(value === true))}
          />
          <span>
            {t("Accept the proposals without waiting")}
            <span className="text-muted-foreground block text-xs">
              {t("A session's proposal then reaches the next prompts at once; you read it afterwards.")}
            </span>
          </span>
        </label>
      ) : null}
    </section>
  )
}

export function MemoryPage() {
  return (
    <Worded words={settingsFrench}>
      <MemoryTab />
    </Worded>
  )
}
