import * as React from "react"

import type { Project } from "@/lib/types"
import {
  idOf,
  pickTab,
  projectItem,
  useProject,
  useProjects,
  usePanelTab,
  usePicked,
  useWide,
} from "@/resources/projects"

import { ContextBlock } from "./context-block"
import { ProjectInPanel } from "./project-page"

/* What sits beside the list of projects.
 *
 * The global context first — always, folded to a few lines, because it is what
 * every ticket is told and the one thing worth seeing without asking — then the
 * project picked in the list: its page, the same one its address opens, with
 * its tabs, its figures and its actions. It was a summary of its own, with a
 * link to the page for the rest: two views of one project, which said
 * different things. The page alone stays a link away, from the panel's header.
 *
 * The row the list read draws it at once; the project as its page reads it —
 * the brief — replaces it as it arrives, read once for the panel and the page
 * alone (see `readProject`).
 *
 * Wide, it is a column next to the list (see `index.css`). Narrower there is no
 * panel: a project picked opens its page (see `ProjectMaster`).
 */

export function ProjectAside() {
  const read = useProjects()
  const chosen = usePicked()
  const wide = useWide()
  const found = read?.projects.find((project) => idOf(project) === chosen)
  return (
    <aside data-projects-aside className="flex min-w-0 flex-col gap-4 [&>[data-slot=context-block]]:mb-0">
      <ContextBlock />
      {found && wide ? <Picked key={chosen} id={chosen} row={found} /> : null}
    </aside>
  )
}

function Picked({ id, row }: { id: string; row: Project }) {
  const listed = React.useMemo(() => projectItem(row), [row])
  const full = useProject(id)
  const tab = usePanelTab()
  return <ProjectInPanel project={full ?? listed} tab={tab} onTab={pickTab} />
}
