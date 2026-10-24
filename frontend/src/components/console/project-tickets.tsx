import { ActionList } from "react-data-form"
import { Link, ViewResourceContextProvider } from "react-resource-view"

import { useT } from "@/lib/i18n"
import { carrying, layoutOf } from "@/lib/resource-view"
import { TICKETS, projectTickets } from "@/resources/tickets"
import { newProjectHref, type ProjectItem } from "@/resources/projects"

/* The first tab of a project: its tickets, as the dashboard draws them.
 *
 * The list is the dashboard's own, declared once (see `projectTickets`) and
 * kept to the tickets that name this project — a ticket carries its project's
 * name, which is also how the cards count them. It opens on the layout the
 * dashboard was last worked in, and remembers the one picked here for it.
 *
 * A ticket made here is made *for* the project: the page's id is the default
 * of the form's project field, so the "New ticket" button the list draws is
 * the dashboard's, prefilled.
 *
 * A project the configuration alone names has no "New ticket" at all, and says
 * why over the list rather than leaving a button missing: a ticket points at a
 * page. The way out is its page, made with the name and the path the
 * configuration already gives it — the line of `config.toml` then is that
 * page's path.
 */

export function ProjectTickets({ project }: { project: ProjectItem }) {
  const t = useT()
  // The id of a project the configuration alone names is a name, not a page: a
  // ticket cannot point at it, so the list has nothing to create.
  const canCreate = Boolean(project.id) && project.source !== "config"
  return (
    <>
      {project.source === "config" ? (
        <p data-slot="project-no-page" className="text-muted-foreground text-sm">
          {t("This project has no page: create it to attach tickets to it.")}{" "}
          <Link
            to={carrying(newProjectHref(), { name: project.name, path: project.configured ?? "" })}
            className="underline underline-offset-2"
          >
            {t("Create its page")}
          </Link>
        </p>
      ) : null}
      <ViewResourceContextProvider
        // The filter is read once, as the context is born: a rename is a new list.
        key={`${project.id}:${project.name}`}
        resource={projectTickets}
        resourceAction={ActionList.list}
        filter={{ project: project.name }}
        defaultData={{ project: project.id }}
        viewVariantId={layoutOf(TICKETS)}
        quota={canCreate ? undefined : { get: () => ({ current: 1, max: 1 }) }}
      />
    </>
  )
}
