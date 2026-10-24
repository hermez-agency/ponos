import { Compass } from "lucide-react"

import { EmptyState } from "@/components/console/empty-state"
import { Button } from "@/components/ui/button"
import { useT } from "@/lib/i18n"

/* An address the console does not have.
 *
 * Drawn instead of the console when the server marks the page `data-missing`
 * (see `main.tsx`): somebody typed `/objectifs`, or kept a link to a page that
 * has since moved. Every view of the console is in the query string, which
 * nothing on a 404 would tell them — so this says where the views are. Plain
 * links, outside the router: the router's one page is `/`.
 */

const VIEWS: [string, string][] = [
  ["Dashboard", "/?view=console/tickets/list"],
  ["Projects", "/?view=console/projects/list"],
  ["Goals", "/?view=console/goals/list"],
  ["Ideas", "/?view=console/ideas/list"],
  ["Schedules", "/?view=console/schedules/list"],
  ["Sessions", "/?view=console/sessions/list"],
  ["Settings", "/?view=console/settings/read/config"],
]

export function NotFound() {
  const t = useT()
  return (
    <main className="bg-background flex min-h-svh items-center justify-center p-4">
      <EmptyState
        icon={Compass}
        title={t("Page not found")}
        className="w-full max-w-lg"
        action={VIEWS.map(([name, href]) => (
          <Button key={href} asChild variant={href === VIEWS[0][1] ? "default" : "outline"} size="sm">
            <a href={href}>{t(name)}</a>
          </Button>
        ))}
      >
        {t("This console has no page at {{path}}. Its pages are these:", {
          path: window.location.pathname,
        })}
      </EmptyState>
    </main>
  )
}
