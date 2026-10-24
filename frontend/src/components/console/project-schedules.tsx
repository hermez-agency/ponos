import { ActionList } from "react-data-form"
import { ViewResourceContextProvider } from "react-resource-view"

import { projectSchedules } from "@/resources/schedules"
import type { ProjectItem } from "@/resources/projects"

/* The schedules tab of a project: those whose tickets are for it.
 *
 * The list is the Schedules page's own, declared once (see `projectSchedules`)
 * and kept to the schedules that point at this project's page. A schedule made
 * here is made *for* the project: the page is the default of the form's
 * project field, as a ticket made under the tickets tab is the project's.
 * It opens on its first layout rather than on the Schedules page's: that one
 * may be the split layout, which this list has not.
 */

export function ProjectSchedules({ project }: { project: ProjectItem }) {
  return (
    <ViewResourceContextProvider
      // The filter is read once, as the context is born: another project is a new list.
      key={project.id}
      resource={projectSchedules}
      resourceAction={ActionList.list}
      filter={{ project: project.id }}
      defaultData={{ project_id: project.id }}
    />
  )
}
