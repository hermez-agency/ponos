import * as React from "react"
import { MoreHorizontal, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Label } from "@/components/ui/label"
import { api } from "@/lib/api"
import { counted, useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

/* Deleting a project, from the list and from its page.
 *
 * One dialog for both, and no way around it: the menu only opens the dialog,
 * and the button in it stays off until the box saying one is sure has been
 * ticked (a long name is a chore to retype) — the server still asks for the
 * name, which the dialog sends itself.
 * It says what is about to happen in the order it happens: the project leaves
 * the console and the runner for good, its page goes to the board's trash, its
 * tickets are stopped (or deleted, if asked), and what is on the machine is not
 * touched. */

/** What the dialog needs to know of a project. */
export interface Deletable {
  id: string
  name: string
}

export function DeleteProjectDialog({
  project,
  tickets,
  open,
  onOpenChange,
  onDeleted,
}: {
  project: Deletable
  /** How many tickets point at it, `null` while the board has not arrived. */
  tickets: number | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onDeleted: () => void
}) {
  const t = useT()
  const [sure, setSure] = React.useState(false)
  const [trash, setTrash] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [refused, setRefused] = React.useState("")

  React.useEffect(() => {
    if (!open) return
    setSure(false)
    setTrash(false)
    setRefused("")
  }, [open])

  const confirm = async () => {
    if (!sure || busy) return false
    setBusy(true)
    setRefused("")
    try {
      const done = await api.deleteProject(project.id, { confirm: project.name, trash_tickets: trash })
      onOpenChange(false)
      toast.success(t("Project “{{name}}” deleted", { name: done.name }), {
        description: t("Its page was put aside in the board's trash folder."),
        duration: 15_000,
      })
      onDeleted()
    } catch (error) {
      setRefused(error instanceof Error ? error.message : String(error))
      return false
    } finally {
      setBusy(false)
    }
  }

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => (busy ? undefined : onOpenChange(next))}
      contentProps={{ "data-delete-project": true } as React.ComponentProps<"div">}
      title={t("Delete “{{name}}”?", { name: project.name })}
      description={
        tickets === null
          ? t("Ponos will stop following this project.")
          : tickets === 0
            ? t("Ponos will stop following this project. No ticket points at it.")
            : counted(
                tickets,
                "Ponos will stop following this project. {{count}} ticket points at it.",
                "Ponos will stop following this project. {{count}} tickets point at it."
              )
      }
      destructive
      disabled={!sure}
      confirm={
        <>
          <Trash2 />
          {busy ? t("Deleting…") : t("Delete the project")}
        </>
      }
      onConfirm={confirm}
    >
      <ul className="text-muted-foreground list-disc space-y-1.5 pl-5 text-sm">
        <li>{t("It disappears from the console and is no longer synchronised: the runner takes none of its tickets, and no more tokens are spent on it.")}</li>
        <li>{t("Its page goes to the board's trash, where it is kept and can be restored.")}</li>
        <li>
          {trash
            ? t("Its tickets are deleted too.")
            : t("Its tickets stay on the board; those that are ready or in progress are blocked, with a comment saying why.")}
        </li>
        <li>{t("The GitHub repository and the folder on this machine are never deleted. Its throwaway worktrees are cleaned up.")}</li>
        <li>{t("Its ideas are deleted; what it cost stays in the statistics.")}</li>
      </ul>

      {tickets ? (
        <Label className="items-start gap-2.5 text-sm font-normal">
          <Checkbox checked={trash} onCheckedChange={(next) => setTrash(next === true)} className="mt-0.5" />
          <span>
            {counted(
              tickets,
              "Also delete its {{count}} ticket",
              "Also delete its {{count}} tickets"
            )}
          </span>
        </Label>
      ) : null}

      <Label className="border-destructive/40 bg-destructive/5 items-start gap-2.5 rounded-md border p-3 text-sm font-medium">
        <Checkbox
          checked={sure}
          onCheckedChange={(next) => setSure(next === true)}
          className="mt-0.5"
          data-confirm-delete
        />
        <span>{t("Yes, I am sure I want to delete this project")}</span>
      </Label>

      {refused ? (
        <p role="alert" className="text-destructive text-sm">
          {refused}
        </p>
      ) : null}

    </ConfirmDialog>
  )
}

/** The “…” menu of a project, whose one entry opens the dialog above. */
export function ProjectMenu({
  project,
  tickets,
  onDeleted,
  className,
}: {
  project: Deletable
  tickets: number | null
  onDeleted: () => void
  className?: string
}) {
  const t = useT()
  const [asking, setAsking] = React.useState(false)
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            data-project-menu
            className={cn("text-muted-foreground", className)}
            aria-label={t("More actions on “{{name}}”", { name: project.name })}
            title={t("More actions")}
          >
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem variant="destructive" onSelect={() => setAsking(true)}>
            <Trash2 />
            {t("Delete")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <DeleteProjectDialog
        project={project}
        tickets={tickets}
        open={asking}
        onOpenChange={setAsking}
        onDeleted={onDeleted}
      />
    </>
  )
}
