import { ActionList } from "react-data-form"
import { ViewResourceContextProvider } from "react-resource-view"

import { EVERY_STATUS, WORKSPACE, bare } from "@/lib/idea-search"
import { layoutOf } from "@/lib/resource-view"
import { IDEAS, ideasChanged, scopedIdeas } from "@/resources/ideas"

import { IdeasButton } from "./ideas-deck"

/* The ideas of one scope: a project's "Ideas" tab, and the swipe's second tab —
 * the workspace's when the swipe was opened from the dashboard.
 *
 * The list is the Ideas page's own, declared once (see `scopedIdeas`) and kept
 * to the scope given here, which the package holds as a filter of the context
 * and keeps through a reset of the bar. A new idea written here is for the
 * scope: the project is the default of the form's project field. It opens on
 * the layout the Ideas page was last worked in. Like the page, it rests on the new
 * ideas, unless it is `every`: the swipe's tab is called "All ideas".
 */

export function ScopedIdeas({
  project = "",
  name = "",
  find = false,
  every = false,
}: {
  /** The project's page; none for the workspace. */
  project?: string
  name?: string
  /** Offer Ponos's swipe as well, for a list that is not already inside it. */
  find?: boolean
  /** Rest on every idea rather than the new ones, for a tab that is called "All ideas". */
  every?: boolean
}) {
  return (
    <div className="flex flex-col gap-3" data-slot="ideas-list">
      {find && project ? (
        <div>
          <IdeasButton project={project} name={name} onClose={() => ideasChanged()} />
        </div>
      ) : null}
      <ViewResourceContextProvider
        // The filter is read once, as the context is born: another scope is a new list.
        key={project}
        resource={scopedIdeas}
        resourceAction={ActionList.list}
        filter={{ project: project ? bare(project) : WORKSPACE, ...(every ? { status: EVERY_STATUS } : {}) }}
        defaultData={{ project: bare(project) }}
        viewVariantId={layoutOf(IDEAS)}
      />
    </div>
  )
}
