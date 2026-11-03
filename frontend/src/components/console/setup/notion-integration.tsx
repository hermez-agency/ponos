import * as React from "react"
import { ExternalLink } from "lucide-react"

import { Field, Said } from "@/components/console/setup/bits"
import { Rich } from "@/components/console/text"
import { Button } from "@/components/ui/button"
import { useT } from "@/lib/i18n"
import type { Shared } from "@/lib/types"

/** The first gesture: the integration, created in Notion, and its secret pasted here. */
export function NotionIntegration({
  token,
  shared,
  busy,
  onType,
  onCheck,
}: {
  token: string
  shared: Shared | null
  busy: boolean
  onType: (token: string) => void
  onCheck: (event: React.FormEvent) => void
}) {
  const t = useT()
  return (
    <section className="flex flex-col gap-3" aria-labelledby="notion-one">
      <h3 id="notion-one" className="text-sm font-semibold">
        {t("1. Create the Ponos integration")}
      </h3>
      <ol className="text-muted-foreground list-decimal pl-5 text-sm leading-relaxed">
        <li>{t("Open Notion's integrations page, and click “New integration”.")}</li>
        <li>{t("Name it “Ponos”, choose your workspace, type “Internal”, and save.")}</li>
        <li>
          <Rich text={t("Under Capabilities, tick “Read comments” and “Insert comments”, then copy the “Internal Integration Secret”.")} />
        </li>
      </ol>
      <div>
        <Button asChild variant="outline" size="sm">
          <a href="https://www.notion.so/profile/integrations" target="_blank" rel="noreferrer">
            {t("Open Notion's integrations")}
            <ExternalLink />
          </a>
        </Button>
      </div>
      <form className="flex flex-col gap-3" onSubmit={onCheck}>
        <Field
          id="notion-token"
          label={t("Integration secret")}
          type="password"
          placeholder="ntn_…"
          value={token}
          onChange={(event) => onType(event.target.value)}
          hint={shared?.ok ? t("Already saved — paste another one only to replace it.") : undefined}
        />
        <div>
          <Button type="submit" disabled={busy || !token.trim()}>
            {busy ? t("Checking…") : t("Check the token")}
          </Button>
        </div>
      </form>
      {shared ? (
        <Said
          ok={shared.ok}
          text={
            shared.ok
              ? t("Notion knows this token: it is the integration “{{name}}”.", { name: shared.name || "Ponos" })
              : shared.refused
                ? t("Notion refused this token: copy the “Internal Integration Secret” again, from Notion's integrations page.")
                : shared.said
          }
        />
      ) : null}
    </section>
  )
}
