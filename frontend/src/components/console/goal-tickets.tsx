import * as React from "react"
import { Plus, X } from "lucide-react"
import { useFormContext, type InputControllerComponentInterface } from "react-data-form"

import { Checkbox } from "@/components/ui/checkbox"
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { titleOf, useBoard } from "@/lib/board-store"
import { ticketsFor } from "@/lib/goal-search"
import { t, useFrench } from "@/lib/i18n"

/* The tickets a goal is tied to: the ones chosen, a line each, and a search
 * to add another.
 *
 * The package's multi-select draws every option as a button, and a board has
 * every ticket of the workspace — over a thousand of them, a wall of buttons
 * spilling out of the dialog. So the choice is a search, as the ticket's own
 * goal is (`combobox.tsx`): it offers the tickets still to do in the goal's
 * projects, twenty at a time, and the box under it opens it to the rest. The
 * value written back is the same list of ids. Its words are in
 * `goal-french.ts`: the first load has no room for them. */
const words = () => import("@/lib/goal-french").then((module) => module.GOAL_FRENCH)

export const GoalTicketsInputController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const { tickets } = useBoard()
  const { form } = useFormContext()
  const [open, setOpen] = React.useState(false)
  const [search, setSearch] = React.useState("")
  const [every, setEvery] = React.useState(false)
  const chosen = Array.isArray(formInput.value) ? (formInput.value as string[]) : []
  const projects = Array.isArray(form.data?.projects) ? (form.data.projects as string[]) : []
  const { shown, more } = ticketsFor(tickets, { search, projects, every, chosen })
  const named = (id: string) => {
    const ticket = tickets.find((one) => one.id === id)
    return ticket ? `#${ticket.short} ${titleOf(ticket)}` : id
  }
  const write = (value: string[]) => onChange({ ...formInput, value })
  // Not drawn in English while its French is on the way.
  if (!useFrench(words)) return null

  return (
    <div className="flex min-w-0 flex-col gap-2" data-slot="goal-tickets">
      {chosen.length ? (
        <ul className="flex min-w-0 flex-col gap-1">
          {chosen.map((id) => (
            <li key={id} className="bg-muted/50 flex min-w-0 items-center gap-2 rounded-md px-2 py-1 text-sm">
              <span className="min-w-0 flex-1 truncate">{named(id)}</span>
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground shrink-0 cursor-pointer"
                aria-label={t("Remove {{name}}", { name: named(id) })}
                onClick={() => write(chosen.filter((one) => one !== id))}
              >
                <X className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {/* Modal, or the dialog the form is drawn in keeps the wheel from scrolling the list. */}
      <Popover open={open} onOpenChange={setOpen} modal>
        <PopoverTrigger asChild>
          <button
            type="button"
            id={formInput.id}
            name={formInput.name}
            role="combobox"
            aria-expanded={open}
            aria-haspopup="listbox"
            className="border-input text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 flex h-9 w-full cursor-pointer items-center gap-2 rounded-md border bg-transparent px-3 py-2 text-left text-sm shadow-xs outline-none focus-visible:ring-[3px]"
          >
            <Plus className="size-4 shrink-0" />
            <span className="truncate">{t("Add a ticket…")}</span>
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="w-(--radix-popover-trigger-width) p-0"
          // The dialog under it would take Escape as its own and close too.
          onEscapeKeyDown={(event) => event.stopPropagation()}
        >
          {/* Filtered here rather than by cmdk: the scope and the twenty are the search's. */}
          <Command shouldFilter={false}>
            <CommandInput placeholder={t("Search a ticket...")} value={search} onValueChange={setSearch} />
            <CommandList>
              <CommandEmpty>{t("Nothing matches.")}</CommandEmpty>
              <CommandGroup>
                {shown.map((ticket) => (
                  <CommandItem key={ticket.id} value={ticket.id} onSelect={() => write([...chosen, ticket.id])}>
                    <span className="min-w-0 flex-1 truncate">{`#${ticket.short} ${titleOf(ticket)}`}</span>
                    {ticket.project ? (
                      <span className="text-muted-foreground max-w-[40%] shrink-0 truncate text-xs">{ticket.project}</span>
                    ) : null}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
          <div className="text-muted-foreground flex flex-col gap-2 border-t px-3 py-2 text-xs">
            {more ? <span>{t("{{count}} more: narrow the search.", { count: String(more) })}</span> : null}
            <label className="flex cursor-pointer items-center gap-2">
              <Checkbox checked={every} onCheckedChange={(checked) => setEvery(checked === true)} />
              {t("Finished tickets and other projects too")}
            </label>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  )
}
