import * as React from "react"
import { Check, ChevronsUpDown } from "lucide-react"
import { Link } from "react-resource-view"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { api, why } from "@/lib/api"
import { t as translate, useT } from "@/lib/i18n"
import type { ChatModels } from "@/lib/types"
import { cn } from "@/lib/utils"

import { closeTalk } from "@/lib/talk"

/* The model a session runs on, chosen from the session itself.
 *
 * Two lists, and the second is only there when OpenRouter has a key: the Claude
 * models Claude Code names by family, and every model OpenRouter sells, searched
 * by name. The models the sessions last ran on come first, so the five you use
 * are not a scroll through four hundred. Without a key the picker says so and
 * leads to the setting, rather than hiding a list the person may not know exists.
 *
 * The choice belongs to the session and takes effect on the next message — the
 * one being answered keeps the model it started on. */

/** A model as the picker writes it: Claude's family capitalised, a slug as it is. */
export const modelName = (id: string, known?: ChatModels): string =>
  known?.claude.find((item) => item.id === id)?.name ??
  known?.openrouter.models.find((item) => item.id === id)?.name ??
  id

/** What the catalogue says of a model, read when a list is opened — not before:
 * it is a request to OpenRouter, and most pages are never going to show it. */
export function useModels(open: boolean) {
  const [models, setModels] = React.useState<ChatModels | null>(null)
  const [reading, setReading] = React.useState(false)
  React.useEffect(() => {
    if (!open) return
    setReading(true)
    api
      .chatModels()
      .then(setModels)
      .catch((error) => toast.error(why(error)))
      .finally(() => setReading(false))
  }, [open])
  return { models, reading }
}

/** A price per million tokens, as short as it reads: `$3 / $15`. */
export const priced = (input?: number | null, output?: number | null): string => {
  if (input == null || output == null) return ""
  const dollars = (value: number) => `$${Number(value.toFixed(value < 1 ? 3 : 2))}`
  return `${dollars(input)} / ${dollars(output)}`
}

/** The picker's list, shared by every place that chooses a model — the chat's,
 * a new ticket's, a recurrence's, a blocked ticket's. `empty` is the line that
 * stands for "no model of its own", for the places where that is an answer. */
export function ModelList({
  model,
  models,
  reading,
  pick,
  empty,
  settingsTo,
  onSettings,
  extra = [],
}: {
  model: string
  models: ChatModels | null
  reading: boolean
  pick: (id: string) => void
  empty: string
  settingsTo: string
  onSettings: () => void
  /** Values the board already holds, which no list above names: still choosable. */
  extra?: string[]
}) {
  const t = useT()
  const recent = models?.recent ?? []
  const claude = models?.claude ?? []
  const router = models?.openrouter
  const known = models ?? undefined
  const named = new Set([...claude.map((item) => item.id), ...(router?.models ?? []).map((item) => item.id)])
  const others = extra.filter((id) => id && !named.has(id))
  return (
    <Command>
      <CommandInput placeholder={t("Search a model…")} />
      <CommandList>
        <CommandEmpty>{reading ? t("Reading the models…") : t("No such model")}</CommandEmpty>
        {recent.length ? (
          <CommandGroup heading={t("Recently used")}>
            {recent.map((id) => (
              <Choice key={`recent:${id}`} id={id} name={modelName(id, known)} model={model} pick={pick} models={known} />
            ))}
          </CommandGroup>
        ) : null}
        <CommandGroup heading="Claude">
          <CommandItem value="default" onSelect={() => pick("")} data-model-option="">
            <Check className={cn("size-4", model === "" ? "opacity-100" : "opacity-0")} />
            {empty}
          </CommandItem>
          {claude.map((item) => (
            <Choice key={item.id} id={item.id} name={item.name} model={model} pick={pick} />
          ))}
        </CommandGroup>
        {others.length ? (
          <CommandGroup heading={t("On the board")}>
            {others.map((id) => (
              <Choice key={id} id={id} name={id} model={model} pick={pick} />
            ))}
          </CommandGroup>
        ) : null}
        {router?.configured && router.models.length ? (
          <CommandGroup heading="OpenRouter">
            {router.models.map((item) => (
              <Choice key={item.id} id={item.id} name={item.name} model={model} pick={pick} models={known} />
            ))}
          </CommandGroup>
        ) : null}
      </CommandList>
      {router && !router.configured ? (
        <p className="text-muted-foreground border-t px-3 py-2 text-xs leading-relaxed">
          {t("Only the Claude models, until OpenRouter is configured.")}{" "}
          <Link to={settingsTo} className="text-foreground underline underline-offset-2" onClick={onSettings}>
            {t("Set up OpenRouter")}
          </Link>
        </p>
      ) : null}
      {router?.error ? (
        <p role="alert" className="text-destructive border-t px-3 py-2 text-xs">
          {router.error}
        </p>
      ) : null}
    </Command>
  )
}

/** Whether a model cannot use tools, which Claude Code cannot work without. */
const toolless = (id: string, models?: ChatModels): boolean =>
  models?.openrouter.models.find((item) => item.id === id)?.tools === false

/** Said once, on the choice: a model that cannot use tools does not fail at once, it fails mid-ticket. */
export const warnToolless = (id: string, models: ChatModels | null) => {
  if (toolless(id, models ?? undefined)) {
    toast.warning(translate("This model cannot use tools, which Claude Code needs to work: the ticket will probably fail."))
  }
}

export function ModelPicker({
  model,
  className,
  onChosen,
  settingsTo,
}: {
  /** What the next turn runs on, as the server resolved it. */
  model: string
  className?: string
  onChosen?: () => void
  /** Where the OpenRouter key is set, for the line that leads there. */
  settingsTo: string
}) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const { models, reading } = useModels(open)

  const pick = async (id: string) => {
    setOpen(false)
    if (id === model) return
    try {
      await api.setChatModel(id)
      warnToolless(id, models)
      onChosen?.()
    } catch (error) {
      toast.error(why(error))
    }
  }

  const label = model ? modelName(model, models ?? undefined) : t("Default model")

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          role="combobox"
          aria-expanded={open}
          aria-label={t("Model of this session")}
          data-model-picker
          className={cn("text-muted-foreground max-w-48 gap-1 px-2 font-mono text-xs", className)}
        >
          <span className="truncate">{label}</span>
          <ChevronsUpDown className="size-3 shrink-0 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0" data-model-list>
        <ModelList
          model={model}
          models={models}
          reading={reading}
          pick={(id) => void pick(id)}
          empty={t("Default model")}
          settingsTo={settingsTo}
          onSettings={() => {
            setOpen(false)
            closeTalk()
          }}
        />
      </PopoverContent>
    </Popover>
  )
}

function Choice({
  id,
  name,
  model,
  pick,
  models,
}: {
  id: string
  name: string
  model: string
  pick: (id: string) => void
  /** The catalogue, for the price and the tools of an OpenRouter model. */
  models?: ChatModels
}) {
  const t = useT()
  const listed = models?.openrouter.models.find((item) => item.id === id)
  const price = priced(listed?.input, listed?.output)
  return (
    <CommandItem value={`${id} ${name}`} onSelect={() => pick(id)} data-model-option={id}>
      <Check className={cn("size-4", model === id ? "opacity-100" : "opacity-0")} />
      <span className="truncate">{name}</span>
      {listed?.tools === false ? (
        <Badge
          variant="outline"
          className="border-destructive/40 text-destructive shrink-0 px-1 text-[0.6rem]"
          title={t("Cannot use tools, which Claude Code needs to work")}
        >
          {t("no tools")}
        </Badge>
      ) : null}
      {name !== id || price ? (
        <span className="text-muted-foreground ml-auto flex shrink-0 flex-col items-end pl-2 font-mono text-[0.65rem] leading-tight">
          {name !== id ? <span className="max-w-40 truncate">{id}</span> : null}
          {price ? <span title={t("Dollars per million tokens, read / written")}>{price}</span> : null}
        </span>
      ) : null}
    </CommandItem>
  )
}
