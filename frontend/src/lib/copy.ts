import { toast } from "sonner"

import { toClipboard } from "./clipboard"
import { t } from "./i18n"

/** Copies `text`, and says whether it worked: "Copied" with `label` under it,
 * when there is one to say — a button that turns into a tick says it itself —
 * and always when it did not, since then the text is to be selected by hand. */
export async function copy(text: string, label?: string): Promise<boolean> {
  const copied = await toClipboard(text)
  if (!copied) toast.error(t("Copy impossible: select the text"), { description: label })
  else if (label !== undefined) toast.success(t("Copied"), { description: label })
  return copied
}
