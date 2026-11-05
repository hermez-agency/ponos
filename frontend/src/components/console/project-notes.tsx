import * as React from "react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { ProjectNotes } from "@/lib/types"

/* What a project's sessions learned: the proposals a delivered ticket wrote
 * (Keep / Discard) and the notes kept, which every ticket of the project is
 * told. Each button saves at once and the server answers with the whole list,
 * so the card never holds a state of its own to get out of step. */
export function NotesCard({ project }: { project: string }) {
  const t = useT()
  const [notes, setNotes] = React.useState<ProjectNotes | null>(null)
  const [problem, setProblem] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [draft, setDraft] = React.useState("")

  const read = React.useCallback(() => {
    api.projectNotes(project).then(
      (answer) => setNotes(answer),
      (error) => setProblem(why(error))
    )
  }, [project])

  React.useEffect(() => {
    read()
    window.addEventListener("ponos:settings", read)
    return () => window.removeEventListener("ponos:settings", read)
  }, [read])

  const act = async (values: Parameters<typeof api.saveProjectNotes>[1]) => {
    setBusy(true)
    try {
      setNotes(await api.saveProjectNotes(project, values))
      setProblem("")
      return true
    } catch (error) {
      setProblem(why(error))
      return false
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card data-card="project-notes" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-2 sm:px-6">
        <CardTitle className="text-base">{t("Project notes")}</CardTitle>
        <CardDescription className="text-[13px] leading-relaxed">
          {t(
            "What sessions learned about this project. A kept note is told to every ticket of the project, after its brief; a proposal comes from a blocked ticket that was answered, then delivered."
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-5 pb-4 sm:px-6">
        {problem ? (
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        ) : null}
        {notes && notes.proposed.length ? (
          <section data-slot="notes-proposed">
            <h4 className="mb-1 text-[13px] font-semibold">{t("Proposed by a session")}</h4>
            <ul className="divide-y">
              {notes.proposed.map((text) => (
                <li key={text} className="flex items-start gap-2 py-2">
                  <span className="min-w-0 flex-1 text-[13px] leading-snug">{text}</span>
                  <Button size="sm" disabled={busy} onClick={() => void act({ action: "keep", text })}>
                    {t("Keep")}
                  </Button>
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void act({ action: "drop", text })}>
                    {t("Discard")}
                  </Button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        <section data-slot="notes-kept">
          <h4 className="mb-1 text-[13px] font-semibold">{t("Kept notes")}</h4>
          {notes && notes.kept.length ? (
            <ul className="divide-y">
              {notes.kept.map((text, index) => (
                <KeptNote
                  key={`${index}-${text}`}
                  text={text}
                  limit={notes.limit}
                  disabled={busy}
                  onSave={(edited) => act({ action: "edit", index, text: edited })}
                  onDelete={() => void act({ action: "delete", index })}
                />
              ))}
            </ul>
          ) : (
            <p className="text-muted-foreground text-[13px]">{t("No note kept yet.")}</p>
          )}
        </section>
        <form
          className="flex gap-2"
          data-field="project-note-add"
          onSubmit={(event) => {
            event.preventDefault()
            const text = draft.trim()
            if (text)
              void act({ action: "add", text }).then((done) => {
                if (done) setDraft("")
              })
          }}
        >
          <Input
            aria-label={t("Add a note")}
            placeholder={t("A durable fact about the project")}
            maxLength={notes?.limit}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <Button type="submit" variant="outline" disabled={busy || !draft.trim()}>
            {t("Add")}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

function KeptNote({
  text,
  limit,
  disabled,
  onSave,
  onDelete,
}: {
  text: string
  limit: number
  disabled: boolean
  onSave: (edited: string) => Promise<boolean>
  onDelete: () => void
}) {
  const t = useT()
  const [value, setValue] = React.useState(text)
  const changed = value.trim() !== text && value.trim() !== ""
  return (
    <li className="flex items-center gap-2 py-2">
      <Input
        className="text-[13px]"
        aria-label={t("Kept notes")}
        maxLength={limit}
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      <Button size="sm" variant="outline" disabled={disabled || !changed} onClick={() => void onSave(value.trim())}>
        {t("Save")}
      </Button>
      <Button size="sm" variant="outline" disabled={disabled} onClick={onDelete}>
        {t("Delete")}
      </Button>
    </li>
  )
}
