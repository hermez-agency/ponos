import * as React from "react"
import { useBlocker } from "@tanstack/react-router"
import { BookOpen, RefreshCw, Save } from "lucide-react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { Context } from "@/lib/types"
import { canAct } from "@/lib/role"

import { EmptyState } from "./empty-state"
import { MarkdownEditor } from "./markdown-editor"
import { Robot } from "./robot"

/* The standing context, the editor of the Context page's first tab.
 *
 * Whatever is written here reaches **every** ticket, before the project's brief
 * and before the ticket itself — which makes it the most expensive text in the
 * workspace. It covers all the projects: it is not a project's, and the page is
 * the only place it is drawn — a project's header links to it
 * (`ProjectHead`'s "Inherits the global context ↑").
 *
 * Two things this block does that no other one does.
 *
 * It **replaces** rather than appends. Every other write in this console adds:
 * a comment under a question, a report under a ticket. This is a value, not a
 * history — saving it twice has to leave one text, not two copies of it under
 * each other.
 *
 * And it edits what the *agent* reads: the Markdown the prompt carries,
 * drawn as it is typed. A heading here is the heading as an agent gets it.
 *
 * It is drawn open, in the editor, with no folded preview and no read-only
 * state: people come to this page to read and change the text, and the page's
 * head — "Context" and its sentence — is the only title above it.
 */


/* The text half-typed, outside the block.
 *
 * Each page of the admin layout is drawn afresh, and the list is redrawn when
 * the language or the layout changes, so what was being typed is kept here
 * instead — until it is saved, or until "Reread" is asked for, which is asking
 * to drop it. */
let draft: string | null = null
/** What the page said the last time it was read, which a draft is measured against. */
let read = ""

export function ContextBlock() {
  const t = useT()
  const [drawn, setDrawn] = React.useState<Context | null>(null)
  const [text, setTyped] = React.useState(draft ?? "")
  const [problem, setProblem] = React.useState("")
  const [saving, setSaving] = React.useState(false)

  const setText = React.useCallback((value: string) => {
    // A text back to what the page says is no draft at all.
    draft = value.trim() === read.trim() ? null : value
    setTyped(value)
  }, [])

  const load = React.useCallback(async (keepDraft: boolean) => {
    try {
      const fresh = await api.context()
      setDrawn(fresh)
      read = fresh.text
      if (!keepDraft || draft === null) {
        draft = null
        setTyped(fresh.text)
      }
      setProblem("")
    } catch (error) {
      setProblem(why(error))
    }
  }, [])

  React.useEffect(() => {
    void load(true)
  }, [load])

  const save = async () => {
    setSaving(true)
    try {
      await api.saveContext(text)
      setDrawn((known) => (known ? { ...known, text: text.trim() } : known))
      read = text
      draft = null
      toast.success(t("The context is saved"), {
        description: t("Every ticket from here on is told this."),
      })
    } catch (error) {
      toast.error(t("The context was not saved"), { description: why(error) })
    } finally {
      setSaving(false)
    }
  }

  // A text somebody is half-way through typing must not be lost to a reread,
  // and a save button that is live on an unchanged text says nothing.
  const changed = drawn !== null && text.trim() !== drawn.text.trim()

  const cancel = () => {
    draft = null
    setTyped(read)
  }

  // Leaving with something typed: the page, the browser's own way out.
  const leaving = useBlocker({
    shouldBlockFn: () => changed && !saving,
    enableBeforeUnload: () => changed,
    withResolver: true,
  })

  return (
    <section
      data-slot="context-block"
      className="flex flex-col gap-3"
    >
      <p className="text-muted-foreground text-sm">
        {t("What every ticket is told, for all the projects.")}
      </p>

      {problem ? (
        <p className="text-tr-amber border-tr-amber/30 bg-tr-amber/10 rounded-xl border px-4 py-3 text-sm">
          {problem}
        </p>
      ) : !drawn ? (
        <p className="text-muted-foreground flex items-center gap-3 text-sm">
          <Robot state="thinking" size={40} />
          {t("Reading the context…")}
        </p>
      ) : !drawn.editable ? (
        <EmptyState icon={BookOpen}>
          {t("This board has no context page, so there is nowhere to write.")}
        </EmptyState>
      ) : (
        <>
          <MarkdownEditor
            value={text}
            onChange={setText}
            readOnly={!canAct()}
            placeholder={t(
              "Who you are, what the team does, the stack, the conventions, the things never to do. Keep it to one screen."
            )}
            className="min-h-[18rem]"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => void save()} disabled={!changed || saving || !canAct()}>
              <Save />
              {saving ? t("Saving…") : t("Save")}
            </Button>
            <Button variant="secondary" size="sm" onClick={cancel} disabled={saving}>
              {t("Cancel")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => void load(false)} disabled={saving}>
              <RefreshCw />
              {t("Reread")}
            </Button>
            <span role="status" className="text-muted-foreground text-xs">
              {changed ? t("Unsaved changes") : t("No changes")}
            </span>
            <span className="text-muted-foreground ml-auto inline-flex items-center gap-1.5 font-mono text-[0.7rem]">
              <BookOpen className="size-3.5" />
              {t("{{count}} characters in every prompt", { count: String(text.trim().length) })}
            </span>
          </div>
          <p className="text-muted-foreground text-xs">
            {t("saved to the board, and read again on the next run.")}
          </p>
        </>
      )}

      <ConfirmDialog
        open={leaving.status === "blocked"}
        onOpenChange={(opened) => {
          if (!opened) leaving.reset?.()
        }}
        title={t("Leave without saving?")}
        description={t("The changes made to the global context are not saved.")}
        cancel={t("Keep editing")}
        confirm={t("Leave")}
        onConfirm={() => {
          draft = null
          leaving.proceed?.()
        }}
      />
    </section>
  )
}
