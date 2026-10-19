import * as React from "react"
import type { InputControllerComponentInterface } from "react-data-form"

/* The "New project" window is opened now and then: kept out of the first load,
 * which has a budget (tests/run.py, `the_console_is_downloaded_once_and_compressed`).
 * `resources/projects` declares the form with these, and `project-form` — the
 * window itself — arrives when it is first drawn. */

type Part = React.FC<any>

const lazily = <Name extends string>(name: Name): Part => {
  const Loaded = React.lazy(() =>
    import("@/components/console/project-form").then((module) => ({ default: module[name as keyof typeof module] as Part }))
  )
  return (props) => (
    <React.Suspense fallback={null}>
      <Loaded {...props} />
    </React.Suspense>
  )
}

export const ProjectWindow = lazily("ProjectWindow")
export const ProjectForm = lazily("ProjectForm")
export const ProjectFields = lazily("ProjectFields")
export const ProjectEditFields = lazily("ProjectEditFields")
export const ProjectFoot = lazily("ProjectFoot")
export const ProjectNameInputController = lazily("ProjectNameInputController") as InputControllerComponentInterface
export const LineInputController = lazily("LineInputController") as InputControllerComponentInterface
export const KindInputController = lazily("KindInputController") as InputControllerComponentInterface
export const BoxInputController = lazily("BoxInputController") as InputControllerComponentInterface
