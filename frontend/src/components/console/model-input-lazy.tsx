import * as React from "react"
import type { InputControllerComponentInterface } from "react-data-form"

/* The model's field of a ticket's form and of a schedule's: declared with the
 * resources, drawn once a form is opened — and fetched then, with the list of
 * models it offers (`model-input`, `model-picker`), rather than with the board,
 * whose first load has a budget. */
const Loaded = React.lazy(() =>
  import("@/components/console/model-input").then((module) => ({ default: module.ModelInputController }))
)

export const ModelInputController: InputControllerComponentInterface = (props) => (
  <React.Suspense fallback={null}>
    <Loaded {...props} />
  </React.Suspense>
)
