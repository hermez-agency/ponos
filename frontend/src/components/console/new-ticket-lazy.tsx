import * as React from "react"
import type { InputControllerComponentInterface } from "react-data-form"

/* The "New ticket" dialog is opened now and then: kept out of the first load,
 * which has a budget (tests/run.py, `the_console_is_downloaded_once_and_compressed`).
 * `resources/tickets` declares the form with these, and `new-ticket` — the
 * dialog itself — arrives when the dialog is first drawn. */

/** How long the editor takes to tell the form what it holds: see `useSendOnControlEnter`. */
export const EDITOR_SETTLES = 300

type Part = React.FC<any>

const lazily = <Name extends string>(name: Name): Part => {
  const Loaded = React.lazy(() =>
    import("@/components/console/new-ticket").then((module) => ({ default: module[name as keyof typeof module] as Part }))
  )
  return (props) => (
    <React.Suspense fallback={null}>
      <Loaded {...props} />
    </React.Suspense>
  )
}

export const NewTicketFields = lazily("NewTicketFields")
export const NewTicketFoot = lazily("NewTicketFoot")
export const SegmentedInputController = lazily("SegmentedInputController") as InputControllerComponentInterface
export const PillsInputController = lazily("PillsInputController") as InputControllerComponentInterface
export const ProjectInputController = lazily("ProjectInputController") as InputControllerComponentInterface
export const WithProjects = lazily("WithProjects")
