import { BookOpen } from "lucide-react"

import { PageHead } from "@/components/console/frame"
import { useT } from "@/lib/i18n"

/* The head of the Context page — see `resources/context.tsx`, which draws it
 * in place of the layout's header. It is the page's one title: the wrapper's
 * `data-slot` is what `index.css` reads to leave out the package's second one
 * (the card each tab draws under the row of tabs) and the breadcrumb's second
 * "Context" (the record's name, after the resource's). */
export function ContextHead() {
  const t = useT()
  return (
    <div data-slot="context-page-head">
      <PageHead icon={BookOpen} title={t("Context")} blurb={t("Everything a session is given besides its ticket")} />
    </div>
  )
}
