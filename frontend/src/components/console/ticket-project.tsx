import * as React from "react"
import { FolderGit2, Play } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { api, why } from "@/lib/api"
import { patchTicket } from "@/lib/board-store"
import { useT } from "@/lib/i18n"
import { canAct } from "@/lib/role"
import type { Project, Ticket } from "@/lib/types"

/* A ticket stopped on its project — one nobody finds on this machine
 * (`project.no-repo`), or a code ticket of « Unknown » that does not say which
 * repository it works in (`project.which-repo`) — is answered here rather than
 * on the project's page: another project, chosen in a list, and the ticket put
 * back in ready in the same gesture. A code ticket is offered the projects
 * that have a repository; the other, every project but the one it is stuck on.
 * Nothing for a role that cannot act, nor for any other stop. */

export const PROJECT_STOPS = new Set(["project.no-repo", "project.which-repo"])

export function TicketProjectChoice({ ticket }: { ticket: Ticket }) {
  const t = useT()
  const code = ticket.block?.code ?? ""
  const shown = ticket.column === "blocked" && PROJECT_STOPS.has(code) && canAct()
  const [projects, setProjects] = React.useState<Project[]>([])
  const [chosen, setChosen] = React.useState("")
  const [busy, setBusy] = React.useState(false)

  React.useEffect(() => {
    if (!shown) return
    let alive = true
    api
      .projects()
      .then((read) => alive && setProjects(read.projects))
      .catch(() => alive && setProjects([]))
    return () => {
      alive = false
    }
  }, [shown])

  if (!shown) return null
  const offered = projects.filter(
    (project) =>
      project.id &&
      project.id !== ticket.project_id &&
      // Archived: not somewhere to send a ticket any more.
      !project.shelved &&
      (code === "project.which-repo" ? project.kind === "code" : true)
  )
  if (!offered.length) return null

  const run = async () => {
    const project = offered.find((one) => one.id === chosen)
    if (!project) return
    setBusy(true)
    try {
      await api.setTicketProject(ticket.id, project.id, true)
      patchTicket(ticket.id, { project: project.name, project_id: project.id })
      toast.success(t("Moved to {{name}}, and run again", { name: project.name }))
    } catch (error) {
      toast.error(t("The project could not be changed"), { description: why(error) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2" data-slot="ticket-project-choice">
      <Select value={chosen} onValueChange={setChosen}>
        <SelectTrigger size="sm" className="min-w-48" aria-label={t("Choose a project")} data-slot="ticket-project-select">
          <FolderGit2 className="size-3.5 shrink-0" />
          <SelectValue placeholder={t("Choose a project")} />
        </SelectTrigger>
        <SelectContent>
          {offered.map((project) => (
            <SelectItem key={project.id} value={project.id}>
              {project.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button size="sm" disabled={!chosen || busy} onClick={() => void run()} data-slot="ticket-project-run">
        <Play />
        {t("Run it again")}
      </Button>
    </div>
  )
}
