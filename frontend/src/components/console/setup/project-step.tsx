import * as React from "react"
import { ArrowRight, FolderGit2 } from "lucide-react"

import { Field, Said, StepCard } from "@/components/console/setup/bits"
import { useKnown } from "@/components/console/setup/known"
import { Rich } from "@/components/console/text"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"

/* -- 5. the first project --------------------------------------------------- */

type Choices = Awaited<ReturnType<typeof api.setupProjects>>

/** Where a demonstration ticket and every ticket after it are filed. */
export const PROJECT_KEY = "ponos-setup-project"

export function ProjectStep({ onNext }: { onNext: () => void }) {
  const t = useT()
  const [choices, setChoices] = React.useState<Choices | null>(null)
  const [failed, setFailed] = React.useState("")
  const [name, setName] = React.useState("")
  const [repository, setRepository] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [made, setMade] = React.useState("")
  const [problem, setProblem] = React.useState("")
  const { reread } = useKnown()

  const read = React.useCallback(() => {
    void api.setupProjects().then(setChoices, (error) => setFailed(why(error)))
  }, [])
  React.useEffect(read, [read])

  const create = async (values: Record<string, unknown>) => {
    setBusy(true)
    setProblem("")
    try {
      const written = await api.createProject(values)
      window.localStorage.setItem(PROJECT_KEY, written.id)
      setMade(written.name)
      reread()
      setName("")
      setRepository("")
      // Added here rather than read again: the board's list of projects is
      // cached for a while, and would not have it yet.
      setChoices((held) =>
        held ? { ...held, projects: [...held.projects, { id: written.id, name: written.name }] } : held
      )
    } catch (error) {
      setProblem(why(error))
    } finally {
      setBusy(false)
    }
  }

  const known = choices?.projects ?? []
  return (
    <StepCard
      title={t("A first project")}
      blurb={t(
        "A ticket belongs to a project: the repository a code ticket works in, or simply a theme for writing. Pick a repository this machine already has, name one on GitHub — it is cloned at the first ticket —, or start with a project without code."
      )}
      footer={
        <Button type="button" variant={known.length ? "default" : "outline"} onClick={onNext}>
          {t("Continue")}
          <ArrowRight />
        </Button>
      }
    >
      {failed ? <Said ok={false} text={failed} /> : null}
      {!choices && !failed ? <p className="text-muted-foreground text-sm">{t("Looking for repositories…")}</p> : null}
      {made ? <Said ok text={t("The project “{{name}}” is created.", { name: made })} /> : null}
      {known.length ? (
        <p className="text-sm" data-testid="setup-projects-known">
          {t("Projects on the board: {{names}}", { names: known.map((one) => one.name).join(", ") })}
        </p>
      ) : null}

      {choices?.repositories.length ? (
        <section className="flex flex-col gap-2" aria-labelledby="project-found">
          <h3 id="project-found" className="text-sm font-semibold">
            {t("Repositories found in {{root}}", { root: choices.root })}
          </h3>
          {choices.repositories.slice(0, 12).map((one) => {
            const taken = known.some((project) => project.name.toLowerCase() === one.name.toLowerCase())
            return (
              <div key={one.path} className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm">
                <FolderGit2 className="text-muted-foreground size-4" />
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{one.name}</span>
                  <span className="text-muted-foreground block truncate text-xs">{one.remote || one.path}</span>
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy || taken}
                  onClick={() => void create({ name: one.name, kind: "code", path: one.path })}
                >
                  {taken ? t("Already a project") : t("Make it a project")}
                </Button>
              </div>
            )
          })}
        </section>
      ) : choices ? (
        <p className="text-muted-foreground text-sm">
          <Rich text={t("No repository in `{{root}}` yet — the folder where Ponos keeps them.", { root: choices.root })} />
        </p>
      ) : null}

      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          void create({ name: name.trim(), kind: repository.trim() ? "code" : "document", repository: repository.trim() })
        }}
      >
        <h3 className="text-sm font-semibold">{t("Or a new one")}</h3>
        <Field id="project-name" label={t("Project name")} value={name} onChange={(event) => setName(event.target.value)} />
        <Field
          id="project-repository"
          label={t("GitHub repository (optional)")}
          placeholder="https://github.com/owner/repository"
          value={repository}
          onChange={(event) => setRepository(event.target.value)}
          hint={t("Left empty, the project has no code: its tickets are written answers and documents.")}
        />
        <div>
          <Button type="submit" disabled={busy || !name.trim()}>
            {t("Create the project")}
          </Button>
        </div>
      </form>
      <Said ok={false} text={problem} />
    </StepCard>
  )
}
