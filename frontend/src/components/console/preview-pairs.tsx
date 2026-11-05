import type { components } from "@/lib/api-types"
import { useT } from "@/lib/i18n"

type Shot = components["schemas"]["PreviewShot"]

/* The captures Ponos took of a ticket's pages, before and after the change, side by side
 * page by page — to judge an interface ticket from a phone. Nothing when none were taken. */
export function PreviewPairs({ ticket, shots }: { ticket: string; shots?: Shot[] }) {
  const t = useT()
  if (!shots?.length) return null
  const pages = [...new Set(shots.map((shot) => shot.page))]
  const src = (file: string) => `/api/tickets/${ticket}/previews/${file}`
  return (
    <section data-slot="previews" className="mt-4">
      <h3 className="mb-2 text-sm font-semibold">{t("Before and after")}</h3>
      <div className="space-y-4">
        {pages.map((page) => (
          <figure key={page} data-page={page}>
            <figcaption className="text-muted-foreground mb-1 font-mono text-xs">{page}</figcaption>
            <div className="grid grid-cols-2 gap-2">
              {(["before", "after"] as const).map((side) => {
                const shot = shots.find((candidate) => candidate.page === page && candidate.side === side)
                return (
                  <a
                    key={side}
                    href={shot ? src(shot.file) : undefined}
                    target="_blank"
                    rel="noreferrer"
                    className="block min-w-0"
                  >
                    <span className="text-muted-foreground mb-0.5 block text-xs">
                      {side === "before" ? t("Before") : t("After")}
                    </span>
                    {shot ? (
                      <img
                        src={src(shot.file)}
                        alt={`${side} ${page}`}
                        loading="lazy"
                        className="w-full rounded border"
                      />
                    ) : (
                      <span className="text-muted-foreground text-xs">—</span>
                    )}
                  </a>
                )
              })}
            </div>
          </figure>
        ))}
      </div>
    </section>
  )
}
