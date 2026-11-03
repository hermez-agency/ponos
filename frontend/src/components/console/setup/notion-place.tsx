import { LoaderCircle, NotebookText } from "lucide-react"

import { Report } from "@/components/console/setup/bits"
import { Button } from "@/components/ui/button"
import { useT } from "@/lib/i18n"
import type { Provisioned, Shared } from "@/lib/types"
import { cn } from "@/lib/utils"

/** The third gesture: a board already there, or a page to build one under. */
export function NotionPlace({
  shared,
  waiting,
  found,
  page,
  busy,
  done,
  onPage,
  onBuild,
}: {
  shared: Shared
  waiting: boolean
  found: boolean
  page: string
  busy: boolean
  done: Provisioned | null
  onPage: (page: string) => void
  onBuild: (chosen: { page?: string; workspace?: string }) => void
}) {
  const t = useT()
  return (
    <section className="flex flex-col gap-3" aria-labelledby="notion-three" data-testid="notion-shared">
      <h3 id="notion-three" className="text-sm font-semibold">
        {t("3. Choose where the board goes")}
      </h3>
      {waiting ? (
        <p className="text-muted-foreground flex items-center gap-2 text-sm" role="status">
          <LoaderCircle className="size-4 animate-spin" />
          {t("Waiting for a page shared with “{{name}}”…", { name: shared.name || "Ponos" })}
        </p>
      ) : null}
      {shared.boards.map((one) => (
        <div key={one.id} className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm">
          <NotebookText className="text-muted-foreground size-4" />
          <span className="flex-1">{t("A Ponos board is already there.")}</span>
          <Button type="button" size="sm" disabled={busy || found} onClick={() => onBuild({ workspace: one.id })}>
            {t("Use this board")}
          </Button>
        </div>
      ))}
      {shared.pages.length ? (
        <div className="flex flex-col gap-2" role="radiogroup" aria-label={t("Pages shared with the integration")}>
          {shared.pages.map((one) => (
            <label
              key={one.id}
              className={cn(
                "flex cursor-pointer items-center gap-3 rounded-lg border p-3 text-sm",
                page === one.id ? "border-primary bg-primary/5" : "hover:bg-muted/60"
              )}
            >
              <input
                type="radio"
                name="notion-page"
                value={one.id}
                checked={page === one.id}
                onChange={() => onPage(one.id)}
                className="accent-primary"
              />
              <span className="flex-1 font-medium">{one.title || t("(untitled page)")}</span>
            </label>
          ))}
          <div>
            <Button type="button" disabled={busy || !page} onClick={() => onBuild({ page })}>
              {busy ? t("Building the board…") : t("Build the board under this page")}
            </Button>
          </div>
        </div>
      ) : null}
      <Report done={done} />
    </section>
  )
}
