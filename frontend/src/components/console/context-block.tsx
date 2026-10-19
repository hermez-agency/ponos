import * as React from "react"
import { useBlocker, useLocation } from "@tanstack/react-router"
import { BookOpen, Pencil, RefreshCw, Save } from "lucide-react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { Context } from "@/lib/types"
import { cn } from "@/lib/utils"

import { EmptyState } from "./empty-state"
import { Eyebrow } from "./frame"
import { Markdown } from "./markdown"
import { MarkdownEditor } from "./markdown-editor"
import { Robot } from "./robot"

/* The standing context, as the first block of the Projects page.
 *
 * Whatever is written here reaches **every** ticket, before the project's brief
 * and before the ticket itself — which makes it the most expensive text in the
 * workspace. It sits over the projects because it covers all of them: it is a
 * block of that page, not a project and not a page of its own.
 *
 * Two things this block does that no other one does.
 *
 * It **replaces** rather than appends. Every other write in this console adds:
 * a comment under a question, a report under a ticket. This is a value, not a
 * history — saving it twice has to leave one text, not two copies of it under
 * each other.
 *
 * And it edits what the *agent* reads, not what Notion draws: the page
 * flattened into the Markdown the prompt carries, drawn as it is typed. A
 * heading that looks different here from the way it looks in Notion is the
 * heading as an agent gets it.
 *
 * It is drawn folded — a few lines, so that a long text does not push the
 * projects off a phone — and opened by "See all" or by "Edit".
 */

/** The address a project's brief links back to. */
export const CONTEXT_ANCHOR = "global-context"

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
  const [editing, setEditing] = React.useState(draft !== null)
  const [open, setOpen] = React.useState(false)
  const [overflows, setOverflows] = React.useState(false)
  const [problem, setProblem] = React.useState("")
  const [saving, setSaving] = React.useState(false)
  const body = React.useRef<HTMLDivElement>(null)
  const hash = useLocation({ select: (location) => location.hash })

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

  // The link from a project's brief lands here.
  React.useEffect(() => {
    if (hash === CONTEXT_ANCHOR && drawn) document.getElementById(CONTEXT_ANCHOR)?.scrollIntoView()
  }, [hash, drawn])

  const save = async () => {
    setSaving(true)
    try {
      await api.saveContext(text)
      setDrawn((known) => (known ? { ...known, text: text.trim() } : known))
      read = text
      draft = null
      setEditing(false)
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
    setEditing(false)
  }

  // Leaving with something typed: the page, the browser's own way out.
  const leaving = useBlocker({
    shouldBlockFn: () => changed && !saving,
    enableBeforeUnload: () => changed,
    withResolver: true,
  })

  const shown = drawn?.text.trim() ?? ""
  React.useLayoutEffect(() => {
    const element = body.current
    if (element) setOverflows(element.scrollHeight > element.clientHeight + 1)
  }, [shown, open, editing])

  return (
    <section
      id={CONTEXT_ANCHOR}
      data-slot="context-block"
      className="bg-card mb-6 flex scroll-mt-4 flex-col gap-3 rounded-xl border p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Eyebrow>{t("Global context")}</Eyebrow>
          <p className="text-muted-foreground mt-1 text-sm">
            {t("Sent to Ponos in every ticket, for all the projects")}
          </p>
        </div>
        {drawn?.editable && !editing && shown ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setEditing(true)}
          >
            <Pencil />
            {t("Edit")}
          </Button>
        ) : null}
      </div>

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
          {t("This workspace has no “{{page}}” page, so there is nowhere to write.", {
            page: drawn.where,
          })}
          <br />
          <code className="font-mono text-xs">ponos init &lt;page-url&gt;</code> {t("builds it.")}
        </EmptyState>
      ) : editing ? (
        <>
          <MarkdownEditor
            value={text}
            onChange={setText}
            placeholder={t(
              "Who you are, what the team does, the stack, the conventions, the things never to do. Keep it to one screen."
            )}
            className="min-h-[18rem]"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => void save()} disabled={!changed || saving}>
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
            <Eyebrow>{drawn.storage}</Eyebrow> —{" "}
            {t("saved to the “{{page}}” page, and read again on the next run.", {
              page: drawn.where,
            })}
          </p>
        </>
      ) : shown ? (
        <>
          <div
            ref={body}
            data-open={open}
            className={cn(
              "relative overflow-hidden",
              !open &&
                "max-h-24 [mask-image:linear-gradient(to_bottom,black_60%,transparent)]"
            )}
          >
            <Markdown text={shown} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {overflows || open ? (
              <Button variant="ghost" size="sm" onClick={() => setOpen(!open)} aria-expanded={open}>
                {open ? t("Fold") : t("See all")}
              </Button>
            ) : null}
            <span className="text-muted-foreground font-mono text-[0.7rem]">
              {t("{{count}} characters in every prompt", { count: String(shown.length) })}
            </span>
          </div>
        </>
      ) : (
        // One line and its button: an empty state as tall as the screen's
        // empty states was the largest thing on the Projects page, for a text
        // nobody had written yet.
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed px-4 py-3">
          <p className="text-muted-foreground flex min-w-0 items-center gap-2 text-sm">
            <BookOpen className="size-4 shrink-0" />
            {t("Nothing is written yet, so the tickets are told nothing about who the work is for.")}
          </p>
          <Button size="sm" onClick={() => setEditing(true)}>
            <Pencil />
            {t("Write the context")}
          </Button>
        </div>
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
