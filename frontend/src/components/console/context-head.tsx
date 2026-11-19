import * as React from "react"
import { BookOpen } from "lucide-react"

import { PageHead } from "@/components/console/frame"
import { useT } from "@/lib/i18n"

/* The head of the Context page — see `resources/context.tsx`, which draws it
 * in place of the layout's header. It is the page's one title: the body's
 * `data-context-page`, set while it is drawn, is what `index.css` reads to
 * leave out the package's second one (the card each tab draws under the row of
 * tabs) and the breadcrumb's second "Context" (the record's name, after the
 * resource's). An attribute, not `body:has([data-slot="context-page-head"])`:
 * that `:has()` made every element inserted under the body, on any page,
 * restyle each element of the page that has a `data-slot`. Set before the
 * page is painted, so the second title is never seen. */
export function ContextHead() {
  const t = useT()
  React.useLayoutEffect(() => {
    document.body.setAttribute("data-context-page", "")
    return () => document.body.removeAttribute("data-context-page")
  }, [])
  return (
    <div data-slot="context-page-head">
      <PageHead icon={BookOpen} title={t("Context")} blurb={t("Everything a session is given besides its ticket")} />
    </div>
  )
}
