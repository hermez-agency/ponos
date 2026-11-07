import { useProjects } from "@/resources/projects"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

import { ProjectThumb } from "./project-picture"

/* Whom an idea is for: the project's icon and name, or the workspace.
 *
 * Said the same way on the Ideas page and on the cards of the swipe, so it is
 * drawn once. The icon is the one every other place shows — `ProjectThumb`, the
 * page's icon — found in the list the console already holds. An idea
 * files its project under the bare page id and the list may carry dashes, hence
 * the comparison without them. A project the list no longer knows is named by
 * what the caller still has, and drawn with its initial.
 */

const bare = (id: string) => id.replace(/-/g, "")

export function IdeaOrigin({
  project,
  name = "",
  className,
}: {
  /** The project's page id; empty for the workspace. */
  project: string
  /** A name to fall back on while the list is not read, or when it no longer holds the project. */
  name?: string
  className?: string
}) {
  const t = useT()
  const found = useProjects()?.projects.find((one) => project && bare(one.id) === bare(project))
  if (!project)
    return (
      <span data-slot="idea-origin" className={cn("text-muted-foreground min-w-0 truncate text-xs", className)}>
        {t("Workspace")}
      </span>
    )
  const label = found?.name || name
  return (
    <span
      data-slot="idea-origin"
      className={cn("text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs", className)}
    >
      <ProjectThumb project={found ?? { name: label }} className="size-5 rounded-md" />
      <span className="truncate">{label || t("Project")}</span>
    </span>
  )
}
