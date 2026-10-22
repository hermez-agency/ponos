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
 * Nothing picked, the global context — because it is what every ticket is
 * told and the one thing worth seeing without asking. A project picked, its
 * page instead: its tabs, its figures, its actions, and nothing else — the
 * project's own header is the one header the panel draws, and the context is
 * a link away (`ProjectHead`'s "Global context ↑"), not a second header the
 * same size sitting over it.
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
  const picked = found && wide
  const aside = React.useRef<HTMLElement>(null)
  // The panel scrolls on its own: a project picked starts at its header.
  React.useEffect(() => {
    aside.current?.scrollTo({ top: 0 })
  }, [chosen])
  return (
    <aside ref={aside} data-projects-aside className="flex min-w-0 flex-col gap-4 [&>[data-slot=context-block]]:mb-0">
      {picked ? <Picked key={chosen} id={chosen} row={found} /> : <ContextBlock />}
    </aside>
  )
}

function Picked({ id, row }: { id: string; row: Project }) {
  const listed = React.useMemo(() => projectItem(row), [row])
  const full = useProject(id)
  const tab = usePanelTab()
  return <ProjectInPanel project={full ?? listed} tab={tab} onTab={pickTab} />
}
