import * as React from "react"
import {
  Download,
  Eye,
  FileIcon,
  FileTextIcon,
  FilmIcon,
  LayoutGrid,
  Library as LibraryIcon,
  List,
  Pencil,
  Trash2,
  Upload,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { api, libraryUrl, why } from "@/lib/api"
import { humanSize } from "@/lib/composer"
import { Worded, useT } from "@/lib/i18n"
import { canAct } from "@/lib/role"
import { settingsFrench } from "@/lib/settings-store"
import type { Library, LibraryFile, Project } from "@/lib/types"

import { when } from "./ticket-bits"

/* Context → Library: the reference files kept for the sessions (`library.py`).
 *
 * A charter, a contract, a brief, a few screenshots: dropped once, kept until
 * somebody deletes them, and listed in the prompt of every session whose
 * project they are for — by their path, so a session reads one with the tool it
 * reads source with. Nothing is copied into a worktree.
 *
 * A file has a name, a description, tags and a scope (every project, or the
 * few that are ticked). The filters, the search included, are asked of the
 * server: the list is what `GET /api/library` answers for them. */

const SELECT =
  "border-input bg-background h-9 rounded-md border px-2 text-sm shadow-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"

const VIEW = "ponos:library-view"

type View = "list" | "grid"

function savedView(): View {
  try {
    return localStorage.getItem(VIEW) === "grid" ? "grid" : "list"
  } catch {
    return "list"
  }
}

/** The picture of an image, or the icon of anything else. */
function Thumb({ file, large = false }: { file: LibraryFile; large?: boolean }) {
  const [broken, setBroken] = React.useState(false)
  const box = large ? "h-36 w-full" : "size-14"
  if (file.kind === "image" && !broken)
    return (
      <img
        src={libraryUrl(file.id)}
        alt=""
        loading="lazy"
        draggable={false}
        className={`bg-muted ${box} shrink-0 rounded-lg border object-cover`}
        onError={() => setBroken(true)}
      />
    )
  const Icon = file.kind === "video" ? FilmIcon : file.type === "application/pdf" ? FileTextIcon : FileIcon
  return (
    <span className={`bg-muted text-muted-foreground flex ${box} shrink-0 items-center justify-center rounded-lg border`}>
      <Icon className="size-6" />
    </span>
  )
}

function Editor({
  file,
  projects,
  onDone,
  onSaved,
}: {
  file: LibraryFile
  projects: Project[]
  onDone: () => void
  onSaved: () => void
}) {
  const t = useT()
  const [name, setName] = React.useState(file.name)
  const [description, setDescription] = React.useState(file.description)
  const [tags, setTags] = React.useState(file.tags.join(", "))
  const [scope, setScope] = React.useState<string[]>(file.projects)
  const [saving, setSaving] = React.useState(false)

  const save = async () => {
    setSaving(true)
    try {
      await api.changeLibraryFile(file.id, {
        name,
        description,
        tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean),
        projects: scope,
      })
      onSaved()
      onDone()
    } catch (error) {
      toast.error(t("The file was not saved"), { description: why(error) })
    } finally {
      setSaving(false)
    }
  }

  const known = projects.filter((project) => project.id)
  const keyOf = (id: string) => id.replace(/-/g, "").toLowerCase()
  const ticked = (id: string) => scope.includes(keyOf(id))

  return (
    <form
      data-slot="library-editor"
      className="bg-card flex flex-col gap-2 rounded-xl border p-3"
      onSubmit={(event) => {
        event.preventDefault()
        void save()
      }}
    >
      <Input aria-label={t("Name")} value={name} onChange={(event) => setName(event.target.value)} />
      <Input
        aria-label={t("Description")}
        value={description}
        placeholder={t("What it is, and when a session needs it")}
        onChange={(event) => setDescription(event.target.value)}
      />
      <Input
        aria-label={t("Tags")}
        value={tags}
        placeholder={t("Tags, separated by commas")}
        onChange={(event) => setTags(event.target.value)}
      />
      <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <legend className="text-muted-foreground mb-1 text-xs">
          {t("Scope: none ticked means every project")}
        </legend>
        {known.map((project) => (
          <label key={project.id} className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={ticked(project.id)}
              onChange={(event) =>
                setScope((now) =>
                  event.target.checked
                    ? [...now, keyOf(project.id)]
                    : now.filter((key) => key !== keyOf(project.id))
                )
              }
            />
            {project.name}
          </label>
        ))}
      </fieldset>
      <div className="flex justify-end gap-2">
        <Button type="submit" size="sm" disabled={saving || !name.trim()}>
          {t("Save")}
        </Button>
        <Button type="button" variant="secondary" size="sm" onClick={onDone} disabled={saving}>
          {t("Cancel")}
        </Button>
      </div>
    </form>
  )
}

function Preview({ file, onClose }: { file: LibraryFile | null; onClose: () => void }) {
  const t = useT()
  return (
    <Dialog open={file !== null} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent closeLabel={t("Close")} className="max-w-[min(92vw,1100px)] gap-2 sm:max-w-[min(92vw,1100px)]">
        <DialogTitle>{file?.name}</DialogTitle>
        <DialogDescription className="sr-only">{t("A file of the library")}</DialogDescription>
        {file?.kind === "image" ? (
          <img
            data-slot="library-preview"
            src={libraryUrl(file.id)}
            alt={file.name}
            className="max-h-[75vh] max-w-full rounded-lg object-contain"
          />
        ) : file?.type === "application/pdf" ? (
          <iframe
            data-slot="library-preview"
            src={libraryUrl(file.id)}
            title={file.name}
            className="h-[75vh] w-full rounded-lg border"
          />
        ) : file?.kind === "video" ? (
          <video data-slot="library-preview" src={libraryUrl(file.id)} controls className="max-h-[75vh] max-w-full rounded-lg bg-black" />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function LibraryTab() {
  const t = useT()
  const [drawn, setDrawn] = React.useState<Library | null>(null)
  const [projects, setProjects] = React.useState<Project[]>([])
  const [project, setProject] = React.useState("")
  const [tag, setTag] = React.useState("")
  const [search, setSearch] = React.useState("")
  const [view, setView] = React.useState<View>(savedView)
  const [problem, setProblem] = React.useState("")
  const [editing, setEditing] = React.useState<number | null>(null)
  const [previewed, setPreviewed] = React.useState<LibraryFile | null>(null)
  const [over, setOver] = React.useState(false)
  const [sending, setSending] = React.useState(0)
  const picker = React.useRef<HTMLInputElement>(null)

  // Several reads can be in flight: only the last asked is drawn.
  const asked = React.useRef(0)
  const read = React.useCallback(async () => {
    const mine = ++asked.current
    try {
      const fresh = await api.library({ project, tag, search })
      if (mine === asked.current) {
        setDrawn(fresh)
        setProblem("")
      }
    } catch (error) {
      if (mine === asked.current) setProblem(why(error))
    }
  }, [project, tag, search])

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

  const choose = (next: View) => {
    setView(next)
    try {
      localStorage.setItem(VIEW, next)
    } catch {
      // Storage refused: the choice lasts as long as the page.
    }
  }

  // A file is uploaded for the project the list is filtered on, when it is.
  const upload = async (files: File[]) => {
    if (!files.length) return
    setSending((count) => count + files.length)
    for (const file of files) {
      try {
        await api.uploadToLibrary(file, project ? { projects: project } : {})
        toast.success(t("“{{name}}” is in the library", { name: file.name }))
      } catch (error) {
        toast.error(t("“{{name}}” could not be kept", { name: file.name }), { description: why(error) })
      } finally {
        setSending((count) => count - 1)
      }
    }
    await read()
  }

  const act = async (work: () => Promise<unknown>, done?: string) => {
    try {
      await work()
      await read()
      if (done) toast.success(done)
    } catch (error) {
      toast.error(t("That did not work"), { description: why(error) })
    }
  }

  const mayAct = canAct()
  const files = drawn?.files ?? []

  const actions = (file: LibraryFile) => (
    <span className="ml-auto flex items-center gap-1">
      {file.kind !== "document" || file.type === "application/pdf" ? (
        <Button size="icon-sm" variant="ghost" aria-label={t("Preview")} onClick={() => setPreviewed(file)}>
          <Eye />
        </Button>
      ) : null}
      <Button size="icon-sm" variant="ghost" aria-label={t("Download")} asChild>
        <a href={libraryUrl(file.id, true)} download={file.name}>
          <Download />
        </a>
      </Button>
      {mayAct ? (
        <>
          <Button size="icon-sm" variant="ghost" aria-label={t("Edit")} onClick={() => setEditing(file.id)}>
            <Pencil />
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label={t("Delete")}
            onClick={() => void act(() => api.deleteLibraryFile(file.id), t("File deleted"))}
          >
            <Trash2 />
          </Button>
        </>
      ) : null}
    </span>
  )

  const facts = (file: LibraryFile) => (
    <div className="text-muted-foreground flex flex-wrap items-center gap-1.5 text-xs">
      <Badge variant="outline">
        {file.project_names.length ? file.project_names.join(", ") : t("All the projects")}
      </Badge>
      {file.tags.map((name) => (
        <Badge key={name} variant="secondary">
          {name}
        </Badge>
      ))}
      <span>{humanSize(file.size)}</span>
      <span>{when(file.updated)}</span>
    </div>
  )

  const item = (file: LibraryFile) =>
    editing === file.id ? (
      <li key={file.id} className={view === "grid" ? "col-span-full" : undefined}>
        <Editor file={file} projects={projects} onDone={() => setEditing(null)} onSaved={() => void read()} />
      </li>
    ) : view === "grid" ? (
      <li key={file.id} data-slot="library-card" className="bg-card flex flex-col gap-2 rounded-xl border p-3">
        <Thumb file={file} large />
        <p className="truncate font-medium" title={file.name}>
          {file.name}
        </p>
        {file.description ? <p className="text-muted-foreground line-clamp-2 text-sm">{file.description}</p> : null}
        {facts(file)}
        <div className="flex">{actions(file)}</div>
      </li>
    ) : (
      <li key={file.id} data-slot="library-row" className="bg-card flex items-start gap-3 rounded-xl border p-3">
        <Thumb file={file} />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="truncate font-medium" title={file.name}>
            {file.name}
          </p>
          {file.description ? <p className="text-muted-foreground text-sm">{file.description}</p> : null}
          {facts(file)}
        </div>
        {actions(file)}
      </li>
    )

  return (
    <section
      data-slot="library-page"
      className="flex flex-col gap-4"
      onDragOver={(event) => {
        if (!mayAct || !event.dataTransfer.types.includes("Files")) return
        event.preventDefault()
        setOver(true)
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(false)
      }}
      onDrop={(event) => {
        if (!mayAct) return
        event.preventDefault()
        setOver(false)
        void upload(Array.from(event.dataTransfer.files))
      }}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-muted-foreground text-sm">
            {t("Reference files kept for the sessions: a charter, a contract, a brief. A session is told the path of those for its project and reads them from there.")}
          </p>
        </div>
        {mayAct ? (
          <>
            <input
              ref={picker}
              type="file"
              multiple
              hidden
              data-slot="library-input"
              onChange={(event) => {
                void upload(Array.from(event.target.files ?? []))
                event.target.value = ""
              }}
            />
            <Button size="sm" onClick={() => picker.current?.click()} disabled={sending > 0}>
              <Upload />
              {sending > 0 ? t("Sending…") : t("Add files")}
            </Button>
          </>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input
          type="search"
          className="max-w-xs"
          aria-label={t("Search the library")}
          placeholder={t("Search the library")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select aria-label={t("Filter by project")} className={SELECT} value={project} onChange={(event) => setProject(event.target.value)}>
          <option value="">{t("Every project")}</option>
          {projects
            .filter((found) => found.id)
            .map((found) => (
              <option key={found.id} value={found.id}>
                {found.name}
              </option>
            ))}
        </select>
        <select aria-label={t("Filter by tag")} className={SELECT} value={tag} onChange={(event) => setTag(event.target.value)}>
          <option value="">{t("Every tag")}</option>
          {(drawn?.tags ?? []).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <span className="ml-auto flex gap-1">
          <Button
            size="icon-sm"
            variant={view === "list" ? "secondary" : "ghost"}
            aria-label={t("List")}
            aria-pressed={view === "list"}
            onClick={() => choose("list")}
          >
            <List />
          </Button>
          <Button
            size="icon-sm"
            variant={view === "grid" ? "secondary" : "ghost"}
            aria-label={t("Thumbnails")}
            aria-pressed={view === "grid"}
            onClick={() => choose("grid")}
          >
            <LayoutGrid />
          </Button>
        </span>
      </div>

      {problem ? (
        <p className="text-tr-amber border-tr-amber/30 bg-tr-amber/10 rounded-xl border px-4 py-3 text-sm">{problem}</p>
      ) : null}

      {mayAct ? (
        <div
          data-slot="library-drop"
          data-over={over ? "true" : "false"}
          className={`text-muted-foreground flex items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-6 text-sm ${over ? "border-primary bg-primary/5 text-foreground" : ""}`}
        >
          <Upload className="size-4" />
          {t("Drop files here")}
        </div>
      ) : null}

      {files.length ? (
        <ul className={view === "grid" ? "grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3" : "flex flex-col gap-2"}>
          {files.map(item)}
        </ul>
      ) : drawn ? (
        <p className="text-muted-foreground flex items-center gap-2 rounded-lg border border-dashed px-4 py-3 text-sm">
          <LibraryIcon className="size-4 shrink-0" />
          {drawn.count ? t("No file matches.") : t("The library is empty.")}
        </p>
      ) : null}

      {drawn ? (
        <p data-slot="library-total" className="text-muted-foreground text-xs">
          {t("{{count}} file(s), {{size}} in all; up to {{limit}} MB a file (web.library_max_mb).", {
            count: String(drawn.count),
            size: humanSize(drawn.total),
            limit: String(drawn.max_mb),
          })}
        </p>
      ) : null}

      <Preview file={previewed} onClose={() => setPreviewed(null)} />
    </section>
  )
}

export function LibraryPage() {
  return (
    <Worded words={settingsFrench}>
      <LibraryTab />
    </Worded>
  )
}
