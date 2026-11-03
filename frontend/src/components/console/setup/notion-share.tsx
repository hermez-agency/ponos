import { ExternalLink } from "lucide-react"

import { Rich } from "@/components/console/text"
import { Button } from "@/components/ui/button"
import { useT } from "@/lib/i18n"

/** The second gesture: the integration added to a page, in Notion's own menu. */
export function NotionShare({ name }: { name: string }) {
  const t = useT()
  return (
    <section className="flex flex-col gap-3" aria-labelledby="notion-two">
      <h3 id="notion-two" className="text-sm font-semibold">
        {t("2. Add Ponos to your Notion page")}
      </h3>
      <div className="grid items-start gap-4 sm:grid-cols-[1fr_17rem]">
        <ol className="text-muted-foreground list-decimal pl-5 text-sm leading-relaxed">
          <li>{t("In Notion, open the page the board should live under — or create an empty one, “Ponos” for instance.")}</li>
          <li>
            <Rich text={t("Click `···` at the top right of the page, then “Connections”.")} />
          </li>
          <li>{t("Search for “{{name}}”, pick it, and confirm.", { name })}</li>
          <li>{t("Come back here: the page appears below on its own.")}</li>
        </ol>
        <NotionShareIllustration name={name} />
      </div>
      <div>
        <Button asChild variant="outline" size="sm">
          <a href="https://www.notion.so" target="_blank" rel="noreferrer">
            {t("Open Notion")}
            <ExternalLink />
          </a>
        </Button>
      </div>
    </section>
  )
}

/** What Notion's own menu looks like at the moment it matters — drawn rather
 * than photographed, so that it speaks the page's language and stays true
 * whatever the workspace is called. */
function NotionShareIllustration({ name }: { name: string }) {
  const t = useT()
  return (
    <figure className="bg-muted/40 rounded-xl border p-3 text-xs" aria-label={t("Notion's page menu, Connections open")}>
      <div className="mb-2 flex items-center justify-end gap-2 text-[0.7rem]">
        <span className="text-muted-foreground">{t("Share")}</span>
        <span className="text-muted-foreground">☆</span>
        <span className="ring-primary rounded px-1.5 font-bold ring-2">···</span>
      </div>
      <div className="bg-background ml-auto w-56 rounded-lg border shadow-sm">
        <div className="text-muted-foreground border-b px-3 py-1.5">{t("Copy link")}</div>
        <div className="bg-primary/10 text-foreground flex items-center justify-between px-3 py-1.5 font-semibold">
          {t("Connections")}
          <span>›</span>
        </div>
        <div className="border-t p-2">
          <div className="text-muted-foreground mb-1.5 rounded border px-2 py-1">{t("Search for connections…")}</div>
          <div className="bg-primary/10 ring-primary flex items-center gap-2 rounded px-2 py-1 font-medium ring-1">
            <span aria-hidden>🤖</span>
            {name}
          </div>
        </div>
      </div>
      <figcaption className="text-muted-foreground mt-2 text-center">
        <Rich text={t("`···` → Connections → {{name}}", { name })} />
      </figcaption>
    </figure>
  )
}
