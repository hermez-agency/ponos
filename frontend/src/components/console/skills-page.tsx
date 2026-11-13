import * as React from "react"
import { FileUp, FolderUp, Paperclip, Pencil, Plus, Power, Sparkles, Trash2, TriangleAlert, X } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { api, why } from "@/lib/api"
import { Worded, useT } from "@/lib/i18n"
import { canAct } from "@/lib/role"
import { settingsFrench } from "@/lib/settings-store"
import type { Project, Skill, SkillOpened, Skills } from "@/lib/types"

import { ConfirmDialog } from "./confirm-dialog"
import { Eyebrow } from "./frame"
import { MarkdownEditor } from "./markdown-editor"
import { when } from "./ticket-bits"

/* Context → Skills: the Claude Code skills Ponos gives its sessions
 * (`skills.py`).
 *
 * A skill is a SKILL.md (a name, a description, a Markdown body) and the files
 * beside it. Ponos keeps them; the runner puts the ones that apply in the
 * worktree of a ticket's session, under `.claude/skills/`, for every session or
 * for the projects the skill is scoped to. A skill the repository already holds
 * under the same name is never overwritten — the repository's wins, and the row
 * says so. What the repositories hold is listed below, read only.
 *
 * Files travel as base64 in JSON: they are small, and a skill is a handful. */

const SELECT =
  "border-input bg-background h-9 rounded-md border px-2 text-sm shadow-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"

/** A file's bytes as base64, without the `data:` prefix a FileReader puts on them. */
function base64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "")
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

/** The files an `<input type=file>` gave, each with the path it has inside the chosen folder. */
async function encoded(list: FileList): Promise<{ path: string; data: string }[]> {
  return Promise.all(
    Array.from(list).map(async (file) => ({
      path: file.webkitRelativePath || file.name,
      data: await base64(file),
    }))
  )
}

function Editor({
  skill,
  projects,
  onDone,
  onSaved,
}: {
  skill?: SkillOpened
  projects: Project[]
  onDone: () => void
  onSaved: () => void
}) {
  const t = useT()
  const [name, setName] = React.useState(skill?.name ?? "")
  const [description, setDescription] = React.useState(skill?.description ?? "")
  const [body, setBody] = React.useState(skill?.body ?? "")
  const [some, setSome] = React.useState(Boolean(skill?.scope.length))
  const [chosen, setChosen] = React.useState<string[]>(skill?.scope ?? [])
  const [attached, setAttached] = React.useState(skill?.attached ?? [])
  const [saving, setSaving] = React.useState(false)
  const id = skill?.id

  const save = async () => {
    setSaving(true)
    try {
      const values = { name, description, body, scope: some ? chosen : [] }
      if (id === undefined) await api.addSkill(values)
      else await api.changeSkill(id, values)
      onSaved()
      onDone()
    } catch (error) {
      toast.error(t("The skill was not saved"), { description: why(error) })
    } finally {
      setSaving(false)
    }
  }

  const attach = async (list: FileList | null) => {
    if (!list?.length || id === undefined) return
    try {
      const opened = await api.attachSkillFiles(id, await encoded(list))
      setAttached(opened.attached)
      onSaved()
    } catch (error) {
      toast.error(t("That did not work"), { description: why(error) })
    }
  }

  const detach = async (path: string) => {
    if (id === undefined) return
    try {
      setAttached((await api.detachSkillFile(id, path)).attached)
      onSaved()
    } catch (error) {
      toast.error(t("That did not work"), { description: why(error) })
    }
  }

  return (
    <form
      data-slot="skill-editor"
      className="bg-card flex flex-col gap-3 rounded-xl border p-3"
      onSubmit={(event) => {
        event.preventDefault()
        void save()
      }}
    >
      <div className="flex flex-wrap gap-2">
        <Input
          className="max-w-xs font-mono"
          aria-label={t("Skill name")}
          placeholder={t("skill-name")}
          value={name}
          maxLength={64}
          onChange={(event) => setName(event.target.value)}
        />
        <Input
          className="min-w-64 flex-1"
          aria-label={t("What it is for")}
          placeholder={t("What it is for, and when Claude should use it.")}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">{t("SKILL.md")}</span>
        <div data-slot="skill-body" className="rounded-md border px-3 py-2">
          <MarkdownEditor value={body} onChange={setBody} field className="min-h-40" />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t("Scope")}
          className={SELECT}
          value={some ? "some" : "all"}
          onChange={(event) => setSome(event.target.value === "some")}
        >
          <option value="all">{t("All the sessions")}</option>
          <option value="some">{t("Only some projects")}</option>
        </select>
        {some
          ? projects
              .filter((project) => project.id)
              .map((project) => (
                <label key={project.id} className="flex items-center gap-1.5 text-sm">
                  <Checkbox
                    checked={chosen.includes(project.id)}
                    onCheckedChange={(value) =>
                      setChosen((now) =>
                        value === true ? [...now, project.id] : now.filter((other) => other !== project.id)
                      )
                    }
                  />
                  {project.name}
                </label>
              ))
          : null}
      </div>
      {id !== undefined ? (
        <div data-slot="skill-files" className="flex flex-col gap-1">
          <span className="text-muted-foreground text-xs">{t("Files beside the SKILL.md")}</span>
          <ul className="flex flex-wrap gap-2">
            {attached.map((file) => (
              <li key={file.path} className="bg-muted flex items-center gap-1 rounded-md px-2 py-1 font-mono text-xs">
                {file.path}
                <button
                  type="button"
                  aria-label={t("Remove {{name}}", { name: file.path })}
                  className="hover:text-destructive"
                  onClick={() => void detach(file.path)}
                >
                  <X className="size-3" />
                </button>
              </li>
            ))}
          </ul>
          <label className="text-muted-foreground inline-flex w-fit cursor-pointer items-center gap-1 text-sm underline-offset-2 hover:underline">
            <Paperclip className="size-3.5" />
            {t("Attach files")}
            <input
              type="file"
              multiple
              className="sr-only"
              aria-label={t("Attach files")}
              onChange={(event) => {
                void attach(event.target.files)
                event.target.value = ""
              }}
            />
          </label>
        </div>
      ) : (
        <p className="text-muted-foreground text-xs">{t("Files can be attached once the skill is saved.")}</p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="submit" size="sm" disabled={saving || !name.trim() || !description.trim()}>
          {t("Save")}
        </Button>
        <Button type="button" variant="secondary" size="sm" onClick={onDone} disabled={saving}>
          {t("Cancel")}
        </Button>
      </div>
    </form>
  )
}

function SkillsTab() {
  const t = useT()
  const [drawn, setDrawn] = React.useState<Skills | null>(null)
  const [projects, setProjects] = React.useState<Project[]>([])
  const [problem, setProblem] = React.useState("")
  const [adding, setAdding] = React.useState(false)
  const [editing, setEditing] = React.useState<SkillOpened | null>(null)
  const mayAct = canAct()

  const read = React.useCallback(async () => {
    try {
      setDrawn(await api.skills())
      setProblem("")
    } catch (error) {
      setProblem(why(error))
    }
  }, [])

  React.useEffect(() => {
    void read()
    api
      .projects()
      .then((answer) => setProjects(answer.projects))
      .catch(() => setProjects([]))
  }, [read])

  const act = async (work: () => Promise<unknown>, done?: string) => {
    try {
      await work()
      await read()
      if (done) toast.success(done)
    } catch (error) {
      toast.error(t("That did not work"), { description: why(error) })
    }
  }

  const imported = async (list: FileList | null, archive: boolean) => {
    if (!list?.length) return
    await act(async () => {
      if (archive) await api.importSkill({ archive: await base64(list[0]) })
      else await api.importSkill({ files: await encoded(list) })
    }, t("Skill imported"))
  }

  const open = async (skill: Skill) => {
    try {
      setAdding(false)
      setEditing(await api.skill(skill.id))
    } catch (error) {
      toast.error(t("That did not work"), { description: why(error) })
    }
  }

  const row = (skill: Skill) =>
    editing?.id === skill.id ? (
      <li key={skill.id}>
        <Editor skill={editing} projects={projects} onDone={() => setEditing(null)} onSaved={() => void read()} />
      </li>
    ) : (
      <li
        key={skill.id}
        data-slot="skill-row"
        data-enabled={skill.enabled}
        className="bg-card flex flex-col gap-2 rounded-xl border p-3"
      >
        <div className="flex flex-wrap items-baseline gap-2">
          <span className={skill.enabled ? "font-mono font-medium" : "text-muted-foreground font-mono line-through"}>
            {skill.name}
          </span>
          <span className="text-muted-foreground min-w-0 flex-1 text-sm">{skill.description}</span>
        </div>
        <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
          <Badge variant="outline">
            {skill.scope.length ? skill.scope_names.join(", ") : t("All the sessions")}
          </Badge>
          <Badge variant={skill.enabled ? "secondary" : "outline"}>{skill.enabled ? t("Active") : t("Inactive")}</Badge>
          {skill.files ? <span>{t("{{count}} file(s)", { count: String(skill.files) })}</span> : null}
          <span>{when(skill.updated)}</span>
          {skill.conflicts.length ? (
            <span data-slot="skill-conflict" className="text-tr-amber inline-flex items-center gap-1">
              <TriangleAlert className="size-3" />
              {t("The repository of {{projects}} already has this skill: the repository's wins, this one is not placed there.", {
                projects: skill.conflicts.map((clash) => clash.project_name).join(", "),
              })}
            </span>
          ) : null}
          {mayAct ? (
            <span className="ml-auto flex items-center gap-1">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void act(() => api.changeSkill(skill.id, { enabled: !skill.enabled }))}
              >
                <Power />
                {skill.enabled ? t("Disable") : t("Enable")}
              </Button>
              <Button size="icon-sm" variant="ghost" aria-label={t("Edit")} onClick={() => void open(skill)}>
                <Pencil />
              </Button>
              <ConfirmDialog
                title={t("Delete {{name}}", { name: skill.name })}
                description={t("The skill and its files are deleted. The next sessions no longer receive it.")}
                confirm={t("Delete")}
                destructive
                onConfirm={() => act(() => api.deleteSkill(skill.id), t("Skill deleted"))}
                trigger={
                  <Button size="icon-sm" variant="ghost" aria-label={t("Delete")}>
                    <Trash2 />
                  </Button>
                }
              />
            </span>
          ) : null}
        </div>
      </li>
    )

  return (
    <section data-slot="skills-page" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-muted-foreground text-sm">
            {t("The Claude Code skills Ponos gives its sessions. Each is put in the worktree of a ticket under .claude/skills, for every session or for some projects.")}
          </p>
        </div>
        {mayAct ? (
          <div className="flex flex-wrap gap-2">
            <label className="border-input hover:bg-accent inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border px-3 text-sm">
              <FolderUp className="size-4" />
              {t("Import a folder")}
              <input
                type="file"
                className="sr-only"
                aria-label={t("Import a folder")}
                data-slot="skill-import-folder"
                // @ts-expect-error webkitdirectory is not in the DOM typings, though every browser has it
                webkitdirectory=""
                onChange={(event) => {
                  void imported(event.target.files, false)
                  event.target.value = ""
                }}
              />
            </label>
            <label className="border-input hover:bg-accent inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border px-3 text-sm">
              <FileUp className="size-4" />
              {t("Import a .zip")}
              <input
                type="file"
                accept=".zip,application/zip"
                className="sr-only"
                aria-label={t("Import a .zip")}
                data-slot="skill-import-zip"
                onChange={(event) => {
                  void imported(event.target.files, true)
                  event.target.value = ""
                }}
              />
            </label>
            <Button
              size="sm"
              onClick={() => {
                setEditing(null)
                setAdding(true)
              }}
              disabled={adding}
            >
              <Plus />
              {t("New skill")}
            </Button>
          </div>
        ) : null}
      </div>

      {adding ? <Editor projects={projects} onDone={() => setAdding(false)} onSaved={() => void read()} /> : null}

      {problem ? (
        <p className="text-tr-amber border-tr-amber/30 bg-tr-amber/10 rounded-xl border px-4 py-3 text-sm">{problem}</p>
      ) : null}

      {drawn?.skills.length ? (
        <ul className="flex flex-col gap-2">{drawn.skills.map(row)}</ul>
      ) : drawn && !adding ? (
        <p className="text-muted-foreground flex items-center gap-2 rounded-lg border border-dashed px-4 py-3 text-sm">
          <Sparkles className="size-4 shrink-0" />
          {t("No skill yet.")}
        </p>
      ) : null}

      {drawn?.repositories.length ? (
        <div data-slot="skills-repositories" className="flex flex-col gap-2">
          <Eyebrow>{t("In the repositories")}</Eyebrow>
          <p className="text-muted-foreground text-xs">
            {t("Skills the projects' repositories already hold. Read only: they are changed in their repository.")}
          </p>
          <ul className="flex flex-col gap-2">
            {drawn.repositories.map((item) => (
              <li
                key={`${item.project}/${item.name}`}
                data-slot="repository-skill"
                className="flex flex-wrap items-baseline gap-2 rounded-xl border border-dashed px-3 py-2"
              >
                <span className="font-mono">{item.name}</span>
                <span className="text-muted-foreground min-w-0 flex-1 text-sm">{item.description}</span>
                <Badge variant="outline">{item.project_name}</Badge>
                <span className="text-muted-foreground font-mono text-xs">{item.repository}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  )
}

export function SkillsPage() {
  return (
    <Worded words={settingsFrench}>
      <SkillsTab />
    </Worded>
  )
}
