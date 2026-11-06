import * as React from "react"
import { Link } from "react-resource-view"

import { useT } from "@/lib/i18n"
import type { Project } from "@/lib/types"
import { contextHref } from "@/resources/context"
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

import { ProjectInPanel } from "./project-page"

/* What sits beside the list of projects.
 *
 * Nothing picked, a line saying so and a link to the Context page, where the
 * standing context lives. A project picked, its page: its tabs, its figures,
 * its actions, and nothing else — the project's own header is the one header
 * the panel draws, and the context is a link away (`ProjectHead`'s "Inherits
 * the global context ↑").
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
    <aside ref={aside} data-projects-aside className="flex min-w-0 flex-col gap-4">
      {picked ? <Picked key={chosen} id={chosen} row={found} /> : <NothingPicked />}
    </aside>
  )
}

function NothingPicked() {
  const t = useT()
  return (
    <div className="text-muted-foreground flex flex-col items-start gap-2 rounded-xl border border-dashed p-4 text-sm">
      <p>{t("Pick a project to read its page here. What every ticket is told lives in the Context page.")}</p>
      <Link to={contextHref()} className="text-foreground underline underline-offset-2">
        {t("Open the Context page")}
      </Link>
    </div>
  )
}

function Picked({ id, row }: { id: string; row: Project }) {
  const listed = React.useMemo(() => projectItem(row), [row])
  const full = useProject(id)
  const tab = usePanelTab()
  return <ProjectInPanel project={full ?? listed} tab={tab} onTab={pickTab} />
}
