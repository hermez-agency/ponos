import * as React from "react"
import { ChevronsUpDown } from "lucide-react"
import type { InputControllerComponentInterface } from "react-data-form"

import { ModelList, modelName, useModels, warnToolless } from "@/components/console/model-picker"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { closeTalk } from "@/lib/talk"
import { t } from "@/lib/i18n"
import { cn } from "@/lib/utils"
import { settingsHref } from "@/resources/settings"

/* The chat's model picker, as a form field and as a stand-alone control.
 *
 * A ticket, a recurrence and a blocked ticket's "another model" all choose the
 * same thing the chat does, so they draw the same list (`ModelList`): the Claude
 * models, OpenRouter's catalogue with a search when a key is set, the recent
 * ones, a price and a "no tools" badge. Nothing here is written to the board
 * except the value: Notion adds a slug to its Model column the first time a
 * ticket carries it, and only the ones chosen get there.
 */

/** The control itself: what is chosen, and what to do when another is. */
export function ModelChoice({
  value,
  onChange,
  empty,
  id,
  name,
  label,
  className,
  extra,
}: {
  value: string
  onChange: (model: string) => void
  /** What no model at all is called here: "the runner's model", "Same model"… */
  empty: string
  id?: string
  name?: string
  label?: string
  className?: string
  /** What the board already offers beyond the lists. */
  extra?: string[]
}) {
  const [open, setOpen] = React.useState(false)
  const { models, reading } = useModels(open)
  // The catalogue is not read until the list is opened: a slug is shown as it is
  // written, which is the label the board gives it too.
  const shown = value ? modelName(value, models ?? undefined) : empty
  return (
    // Modal, or the dialog the field is drawn in keeps the wheel from scrolling the list.
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <button
          type="button"
          id={id}
          name={name}
          role="combobox"
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-label={label}
          data-model-choice
          className={cn(
            "border-input focus-visible:border-ring focus-visible:ring-ring/50 flex h-8 w-full cursor-pointer items-center justify-between gap-2 rounded-md border bg-transparent px-3 py-2 text-left text-sm whitespace-nowrap shadow-xs transition-[color,box-shadow] outline-none focus-visible:ring-[3px]",
            !value && "text-muted-foreground",
            className
          )}
        >
          <span className="truncate">{shown}</span>
          <ChevronsUpDown className="text-muted-foreground size-4 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-80 max-w-[90vw] p-0"
        data-model-list
        // The dialog under it would take Escape as its own and close too.
        onEscapeKeyDown={(event) => event.stopPropagation()}
      >
        <ModelList
          model={value}
          models={models}
          reading={reading}
          empty={empty}
          extra={extra}
          settingsTo={settingsHref("models")}
          onSettings={() => {
            setOpen(false)
            closeTalk()
          }}
          pick={(next) => {
            setOpen(false)
            if (next === value) return
            warnToolless(next, models)
            onChange(next)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}

/** The Model field of a form: `placeholder` says what an empty one means. */
export const ModelInputController: InputControllerComponentInterface = ({ formInput, onChange }) => (
  <ModelChoice
    id={formInput.id}
    name={formInput.name}
    value={String(formInput.value ?? "")}
    extra={(formInput.valueOptions ?? []).map((option) => String(option.value ?? ""))}
    empty={t(formInput.placeholder ?? "The runner's model")}
    // The height of the other selects of a form (`ComboboxInputController`).
    className="h-9"
    onChange={(value) => onChange({ ...formInput, value, violations: [] })}
  />
)
