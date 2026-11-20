import * as React from "react"
import { GitFork, LoaderCircle, TriangleAlert } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { Run, Step } from "@/lib/types"

/* « Start again from here », asked: the step it starts from, what the new
 * session is told, and — before anybody confirms — what is not taken back.
 *
 * The conversation is cut at the step (`forks.py`); the worktree is not, and
 * that is the one thing somebody would otherwise assume. So it is said here,
 * where the choice is made, as it is said to the session itself.
 *
 * Its own chunk: only an opened ticket's journal ever draws it, and the card
 * that carries `session-log.tsx` onto the board has no use for a dialog. */
export function ForkDialog({ run, step, onClose }: { run: Run; step: Step; onClose: () => void }) {
  const t = useT()
  const [text, setText] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const position = step.position ?? 0

  const send = () => {
    if (!position || busy) return
    setBusy(true)
    api
      .forkRun(run.id, position, text)
      .then(() => {
        toast.success(t("The ticket starts again from step {{step}}", { step: position }))
        onClose()
      })
      .catch((error: unknown) =>
        toast.error(t("The ticket could not start again from this step"), { description: why(error) })
      )
      .finally(() => setBusy(false))
  }

  return (
    <Dialog open onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent data-slot="fork-dialog">
        <DialogHeader>
          <DialogTitle>{t("Start again from step {{step}}", { step: position })}</DialogTitle>
          <DialogDescription>
            {t(
              "A new session starts from the conversation up to this step, without what came after it. This session stays readable in the journal."
            )}
          </DialogDescription>
        </DialogHeader>
        <p data-slot="fork-files" className="bg-muted/50 flex items-start gap-2 rounded-md border px-3 py-2 text-sm">
          <TriangleAlert aria-hidden="true" className="text-tr-amber mt-0.5 size-4 shrink-0" />
          <span>
            {t(
              "The files are not taken back: the worktree and the branch stay as this session left them, with what it changed after this step. The new session is told so, and looks at them first."
            )}
          </span>
        </p>
        <Textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) send()
          }}
          rows={4}
          autoFocus
          aria-label={t("What the new session is told")}
          placeholder={t("This time, do it this way… (optional)")}
        />
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("Cancel")}
          </Button>
          <Button onClick={send} disabled={busy} aria-busy={busy || undefined} data-slot="fork-send">
            {busy ? <LoaderCircle className="animate-spin" /> : <GitFork />}
            {t("Start again")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
