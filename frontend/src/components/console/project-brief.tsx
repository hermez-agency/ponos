import * as React from "react"
import { useBlocker } from "@tanstack/react-router"
import { Pencil } from "lucide-react"
import { Link } from "react-resource-view"
import { toast } from "sonner"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { Button } from "@/components/ui/button"
import { ApiError, api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { ProjectBrief } from "@/lib/types"
import { forgetProject, projectsHref, type ProjectItem } from "@/resources/projects"

import { CONTEXT_ANCHOR } from "./context-block"
import { Eyebrow } from "./frame"
import { Markdown } from "./markdown"
import { MarkdownEditor } from "./markdown-editor"

/* A project's brief, read — and written, with the editor the rest of the
 * console writes in.
 *
 * The text is fetched again when somebody starts editing, not taken from the
 * page: that read is the one the save is measured against. What it brings back
 * is the brief, a `version` of it, and what the page holds that Markdown does
 * not (`losses`). The save sends the version back, and the server refuses to
 * overwrite a brief that no longer says it — the page is then read again, by
 * choice, rather than written over. A page that holds more than Markdown can
 * is rewritten only once this has said what that costs and been told to go on.
 */

export function ProjectBrief({ project }: { project: ProjectItem }) {
  const t = useT()
  // What the page shows when not editing: what the project said, until a save
  // here says better.
  const [shown, setShown] = React.useState(project.content ?? "")
  React.useEffect(() => setShown(project.content ?? ""), [project.content])
  const [opened, setOpened] = React.useState<ProjectBrief | null>(null)
  const [loading, setLoading] = React.useState(false)

  const edit = async () => {
    setLoading(true)
    try {
      setOpened(await api.projectBrief(project.id))
    } catch (error) {
      toast.error(t("The brief could not be read"), { description: why(error) })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <Eyebrow>{t("the brief")}</Eyebrow>
          <Link
            to={`${projectsHref()}#${CONTEXT_ANCHOR}`}
            className="text-muted-foreground hover:text-foreground text-xs underline underline-offset-2"
          >
            {t("Inherits the global context ↑")}
          </Link>
        </span>
        {opened ? null : (
          <Button variant="outline" size="sm" onClick={() => void edit()} disabled={loading}>
            <Pencil />
            {t("Edit")}
          </Button>
        )}
      </div>
      <div className="mt-2">
        {opened ? (
          <BriefEditor
            id={project.id}
            opened={opened}
            onReopen={setOpened}
            onClose={(saved) => {
              if (saved !== undefined) setShown(saved)
              setOpened(null)
            }}
          />
        ) : shown ? (
          <Markdown text={shown} />
        ) : (
          <p className="text-muted-foreground text-sm">
            {t(
              "Nothing is written on this page, so its tickets are told about the workspace and nothing about the project."
            )}
          </p>
        )}
      </div>
    </div>
  )
}

function BriefEditor({
  id,
  opened,
  onReopen,
  onClose,
}: {
  id: string
  opened: ProjectBrief
  onReopen: (brief: ProjectBrief) => void
  onClose: (saved?: string) => void
}) {
  const t = useT()
  const [text, setText] = React.useState(opened.content)
  const [saving, setSaving] = React.useState(false)
  const [conflict, setConflict] = React.useState(false)
  const [asking, setAsking] = React.useState(false)
  const kinds = Object.entries(opened.losses)
  const changed = text.trim() !== opened.content.trim()

  const write = async () => {
    setAsking(false)
    setSaving(true)
    try {
      const written = await api.saveProject(id, {
        content: text,
        base: opened.version,
        accept_losses: kinds.length > 0,
      })
      // Read again by whoever draws this project next, the panel or the page alone.
      forgetProject(id)
      toast.success(t("The brief is saved"), {
        description: t("The next ticket of this project is told this."),
      })
      onClose(written.content)
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) setConflict(true)
      else toast.error(t("The brief was not saved"), { description: why(error) })
    } finally {
      setSaving(false)
    }
  }

  // Saving a page that holds more than Markdown does is asked about first.
  const save = () => {
    if (saving || conflict || !changed) return
    if (kinds.length) setAsking(true)
    else void write()
  }

  const reload = async () => {
    try {
      const fresh = await api.projectBrief(id)
      setConflict(false)
      setText(fresh.content)
      onReopen(fresh)
    } catch (error) {
      toast.error(t("The brief could not be read"), { description: why(error) })
    }
  }

  const latest = React.useRef({ save, onClose, changed })
  latest.current = { save, onClose, changed }
  React.useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "s") {
        event.preventDefault()
        latest.current.save()
      } else if (event.key === "Escape" && !event.defaultPrevented && !latest.current.changed) {
        latest.current.onClose()
      }
    }
    window.addEventListener("keydown", listener)
    return () => window.removeEventListener("keydown", listener)
  }, [])

  // Leaving with something typed: the tab, the page, the browser's own way out.
  const leaving = useBlocker({
    shouldBlockFn: () => changed && !saving,
    enableBeforeUnload: () => changed,
    withResolver: true,
  })

  return (
    <div className="flex flex-col gap-3" data-slot="project-brief-editor">
      {conflict ? (
        <Alert variant="destructive">
          <AlertTitle>{t("This brief changed in Notion since you opened it.")}</AlertTitle>
          <AlertDescription>
            <p>{t("Saving would overwrite that. Reload it to see the new version — what you typed here is dropped.")}</p>
            <Button variant="outline" size="sm" className="mt-2" onClick={() => void reload()}>
              {t("Reload")}
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}
      {kinds.length ? (
        <p className="text-tr-amber border-tr-amber/30 bg-tr-amber/10 rounded-xl border px-4 py-3 text-sm">
          {t("Saving rewrites the page from this text. The page holds what Markdown cannot keep, and it will be lost:")}{" "}
          {kinds.map(([kind, count]) => `${lostName(kind, t)} (${count})`).join(", ")}.
        </p>
      ) : null}
      <MarkdownEditor
        value={text}
        onChange={setText}
        placeholder={t("Write it as you would brief somebody joining the project.")}
        className="min-h-[18rem]"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={save} disabled={!changed || saving || conflict}>
          {saving ? t("Saving…") : t("Save")}
        </Button>
        <Button variant="secondary" size="sm" onClick={() => onClose()} disabled={saving}>
          {t("Cancel")}
        </Button>
        <span role="status" className="text-muted-foreground text-xs">
          {changed ? t("Unsaved changes") : t("No changes")}
        </span>
      </div>

      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        title={t("Save and lose these?")}
        description={kinds.map(([kind, count]) => `${lostName(kind, t)} (${count})`).join(", ")}
        confirm={t("Save anyway")}
        onConfirm={() => void write()}
      />

      <ConfirmDialog
        open={leaving.status === "blocked"}
        onOpenChange={(open) => {
          if (!open) leaving.reset?.()
        }}
        title={t("Leave without saving?")}
        description={t("The changes made to this brief are not saved.")}
        cancel={t("Keep editing")}
        confirm={t("Leave")}
        onConfirm={() => leaving.proceed?.()}
      />
    </div>
  )
}

/** What a kind of loss is called, as the page would say it. A block type nobody named is shown as Notion spells it. */
function lostName(kind: string, t: (key: string) => string): string {
  const names: Record<string, string> = {
    formatting: t("bold, italic and colours"),
    link: t("links"),
    mention: t("mentions"),
    equation: t("equations"),
    toggle: t("toggles"),
    callout: t("callouts"),
    table: t("tables"),
    column_list: t("columns"),
    child_page: t("sub-pages"),
    child_database: t("embedded databases"),
    image: t("images"),
    file: t("files"),
    pdf: t("PDFs"),
    bookmark: t("bookmarks"),
    embed: t("embeds"),
    nested: t("blocks nested too deep"),
  }
  return names[kind] ?? kind.replace(/_/g, " ")
}
