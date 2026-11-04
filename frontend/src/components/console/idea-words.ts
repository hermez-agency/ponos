import { useT } from "@/lib/i18n"
import type { Tone } from "@/lib/idea-search"
import type { IdeaCategory, IdeaStatus } from "@/lib/types"

/* The words of an idea that its list declares — on its filters and in its form
 * — as well as its cards draw: apart from `idea-cards.tsx`, which is fetched
 * with the list, while `resources/ideas.tsx` is read with the console. */

/** What a status is called on a card, and on its filter. */
export function useStatusWords() {
  const t = useT()
  return {
    one: {
      proposed: t("New"),
      kept: t("Kept"),
      discarded: t("Thrown"),
      ticket: t("Turned into a ticket"),
    } satisfies Record<IdeaStatus, string>,
    many: {
      proposed: t("New ideas"),
      kept: t("Kept ideas"),
      discarded: t("Thrown ideas"),
      ticket: t("Became tickets"),
    } satisfies Record<IdeaStatus, string>,
  }
}

/* What each category is called, on a card, on its filter and in the form: the
 * developers' words, the same in every language — like a ticket's sub-type
 * (subtypes.py), they are the words of the tickets and the commits, and read
 * wrong translated. Not to be put through `t()`, nor into french.ts. */
export const CATEGORY_WORDS: Record<Exclude<IdeaCategory, "">, string> = {
  ux: "UX/UI",
  feature: "Feature",
  security: "Security",
  technical: "Tech",
}

/** What a colour is called, on the pill's label and on its filter. */
export function useToneWords(): Record<Tone, string> {
  const t = useT()
  return {
    green: t("Green (70 and up)"),
    orange: t("Orange (40 to 69)"),
    red: t("Red (under 40)"),
    unscored: t("Not scored"),
  }
}
