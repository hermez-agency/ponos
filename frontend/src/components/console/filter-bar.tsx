import * as React from "react"
import * as SelectPrimitive from "@radix-ui/react-select"
import { ChevronDown, SlidersHorizontal } from "lucide-react"
import { InputControllerProvider, getFormInputsFromForm, useFormContext } from "react-data-form"

import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem } from "@/components/ui/select"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

/* One way to filter a list, in the whole console.
 *
 * The board's search bar had it first: a field, then one button per filter
 * with its name in it, and what it asks for beside the name once it asks for
 * something. The lists of the package — the projects, the ideas — drew a
 * label over each select instead, a row of six labels taller than the row it
 * named, and their bar scrolled sideways on a phone without saying so. They
 * now draw the board's buttons, and lay them out the board's way: a line that
 * wraps rather than scrolls, and, where there are many, folded behind one
 * "Filters" button while the list is narrower than they are.
 */

/* The button a filter opens from: dashed while it asks for nothing, solid and
 * saying what it asks for once it does. */
export const FilterButton = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<typeof Button> & { label: string; on: boolean }
>(function FilterButton({ label, on, children, className, ...props }, ref) {
  return (
    <Button
      ref={ref}
      variant="outline"
      size="sm"
      data-on={on || undefined}
      className={cn("shrink-0 font-normal", !on && "border-dashed", on && "border-primary/50", className)}
      {...props}
    >
      {label}
      {children ? (
        <span className="bg-primary/10 text-primary max-w-32 truncate rounded px-1.5 text-xs font-medium">
          {children}
        </span>
      ) : null}
      <ChevronDown className="opacity-60" />
    </Button>
  )
})

/* A select has no empty value: "" — "all", where a list rests — is this one. */
const ANY = "__any__"

/** One choice among a few, as a filter button: the select's options, the button's look. */
export function FilterSelect({
  label,
  value,
  options,
  onChange,
  resting = "",
  always = false,
  className,
  ...props
}: {
  label: string
  value: string
  /** Every value, the one that asks for nothing included. */
  options: { value: string; label: string }[]
  onChange: (value: string) => void
  /** The value that asks for nothing: the button is dashed on it. */
  resting?: string
  /** Say the choice even on the resting value — an order is always one. */
  always?: boolean
} & Omit<React.ComponentProps<"button">, "value" | "onChange">) {
  const chosen = options.find((option) => option.value === value)
  const on = value !== resting
  return (
    /* Positioned: Radix draws a native select beside it, absolutely, and one
     * placed against the page rather than against the bar widens a phone's
     * screen. */
    <div className="relative">
      <Select value={value || ANY} onValueChange={(next) => onChange(next === ANY ? "" : next)}>
        <SelectPrimitive.Trigger asChild>
          <FilterButton label={label} on={on} aria-label={label} className={className} {...props}>
            {chosen && (on || always) ? chosen.label : null}
          </FilterButton>
        </SelectPrimitive.Trigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value || ANY} value={option.value || ANY}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

/**
 * The fields of a list's filter bar, as its form's `formInputs`.
 *
 * `lead` is the one always in sight — the search box, or the row the list is
 * read by —, and with `grow` it takes what the others leave, as the board's
 * search box does. With `fold`, the others go
 * behind a "Filters" button that counts the ones on while the bar is narrower
 * than `@3xl`; measured on the bar, not the screen, as the board's is. The
 * labels stay, for a screen reader: each button says its name already.
 */
export function listFilters({ lead, grow = false, fold = false }: { lead: string; grow?: boolean; fold?: boolean }) {
  return function ListFilters() {
    const t = useT()
    const { form } = useFormContext()
    const [unfolded, setUnfolded] = React.useState(false)
    const inputs = getFormInputsFromForm(form)
    const field = (input: (typeof inputs)[number]) => (
      <InputControllerProvider key={`${input.id}${input.name}${form.version}`} formInput={input} />
    )
    const first = inputs.filter((input) => input.name === lead)
    const others = inputs.filter((input) => input.name !== lead)
    const on = others.filter((input) => input.name && String(form.data?.[input.name] ?? "")).length

    return (
      <div
        data-list-filters
        className="@container w-full min-w-0 [&_[data-slot=field]]:my-0 [&_[data-slot=field-label]]:sr-only"
      >
        <div className="flex flex-wrap items-center gap-2">
          <div className={cn("min-w-0", grow && "min-w-48 flex-1 @3xl:max-w-sm @3xl:min-w-56")}>
            {first.map(field)}
          </div>
          {fold ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className={cn("shrink-0 @3xl:hidden", on > 0 && "border-primary/50")}
              aria-expanded={unfolded}
              onClick={() => setUnfolded(!unfolded)}
            >
              <SlidersHorizontal />
              {t("Filters")}
              {on ? (
                <span className="bg-primary text-primary-foreground rounded-full px-1.5 text-xs tabular-nums">{on}</span>
              ) : null}
            </Button>
          ) : null}
          <div
            data-slot="list-filters"
            className={cn(
              "flex-wrap items-center gap-1.5",
              fold ? cn("basis-full", unfolded ? "flex" : "hidden", "@3xl:flex @3xl:basis-auto") : "flex"
            )}
          >
            {others.map(field)}
          </div>
        </div>
      </div>
    )
  }
}
