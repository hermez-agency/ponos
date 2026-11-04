import * as React from "react"
import type { InputControllerComponentInterface } from "react-data-form"

/* The ideas' list, their page and their form are drawn once the ideas are
 * opened: kept out of the first load, which has a budget (tests/run.py,
 * `the_console_is_downloaded_once_and_compressed`). `resources/ideas` declares
 * its views with these, and `idea-cards`, `idea-form` and `ideas-plan` arrive
 * when one is first drawn. */

type Part = React.FC<any>

const lazily = (load: () => Promise<Record<string, unknown>>, name: string): Part => {
  const Loaded = React.lazy(() => load().then((module) => ({ default: module[name] as Part })))
  return (props) => (
    <React.Suspense fallback={null}>
      <Loaded {...props} />
    </React.Suspense>
  )
}

const cards = () => import("@/components/console/idea-cards")
const form = () => import("@/components/console/idea-form")
const plan = () => import("@/components/console/ideas-plan")

export const IdeaCards = lazily(cards, "IdeaCards")
export const IdeaRows = lazily(cards, "IdeaRows")
export const IdeaPage = lazily(cards, "IdeaPage")
export const NoIdea = lazily(cards, "NoIdea")

export const IdeaWindow = lazily(form, "IdeaWindow")
export const IdeaForm = lazily(form, "IdeaForm")
export const IdeaFields = lazily(form, "IdeaFields")
export const IdeaFoot = lazily(form, "IdeaFoot")
export const IdeaTitleInputController = lazily(form, "IdeaTitleInputController") as InputControllerComponentInterface
export const IdeaTextInputController = lazily(form, "IdeaTextInputController") as InputControllerComponentInterface
export const ChipsInputController = lazily(form, "ChipsInputController") as InputControllerComponentInterface

export const IdeasPlanLine = lazily(plan, "IdeasPlanLine")
export const IdeasSettingsButton = lazily(plan, "IdeasSettingsButton")
