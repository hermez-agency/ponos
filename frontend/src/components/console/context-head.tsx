import { BookOpen } from "lucide-react"

import { PageHead } from "@/components/console/frame"
import { useT } from "@/lib/i18n"

/* The head of the Context page — see `resources/context.tsx`, which draws it
 * in place of the layout's header. */
export function ContextHead() {
  const t = useT()
  return <PageHead icon={BookOpen} title={t("Context")} blurb={t("Everything a session is given besides its ticket")} />
}
