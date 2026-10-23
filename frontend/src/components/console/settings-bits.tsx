import * as React from "react"
import {
  ChevronDown,
  CircleAlert,
  CircleCheck,
  CircleHelp,
  CornerLeftUp,
  Eye,
  EyeOff,
  File as FileIcon,
  Folder as FolderIcon,
  FolderOpen,
  Loader2Icon,
} from "lucide-react"
import {
  FormElement,
  FormInputViolation,
  InputControllerProvider,
  SelectInputController,
  getFormInputsFromForm,
  useForm,
  useFormContext,
  type FormDecoratorPropsInterface,
  type FormGroupProviderPropsInterface,
  type FormInputInterface,
  type FormInterface,
  type InputControllerInterface,
} from "react-data-form"

import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { useConsole } from "@/hooks/use-console"
import { api, why } from "@/lib/api"
import { t as translate, useT } from "@/lib/i18n"
import { splitHelp } from "@/lib/settings-search"
import {
  cardId,
  currentSettings,
  draftOf,
  forgetDraft,
  inputName,
  publishSettings,
  rememberDraft,
  sectionsIn,
  useAsked,
  useKeysShown,
} from "@/lib/settings-store"
import type { Folder, SettingField, SettingFold, SettingSection, SettingValue } from "@/lib/types"

import { openTalk } from "@/lib/talk"
import { Rich } from "./text"

/* One page of `config.toml`, as a form of cards.
 *
 * A page is one of the six groups the server describes, and one form: what you
 * type in any of its cards waits under the same bar, and is saved in one go.
 * The cards are how the form is *drawn* — react-data-form still holds the
 * state and draws each control; `GroupCards` only decides where each one goes,
 * and `SettingRow` how a label, its line of help and its control sit together.
 *
 * The three states a setting carries are the whole grammar of the page: what
 * the file says, what the runner falls back on when it says nothing, and what
 * you have just typed. So the form's data is compared against the description
 * it was built from and only what actually moved is sent — a field left alone
 * is a line the file keeps, comment and all, and a token you did not retype is
 * a token that never left the machine. See `written`.
 */

/** Radix has no empty-string value, and "the file says nothing" needs one. */
const UNSET = "default:unset"

/** A token you asked to forget. An empty box already means "I did not retype it". */
const FORGOTTEN = "secret:forgotten"

/** The secrets a Test button can try before they are saved. */
const TRIED = new Set(["claude.api_key"])

// The command a card is checked with. The CLI already knows how to say whether
// a token works; the settings page does not need a second opinion.
const CHECKS: Record<string, [string, string]> = {
  notion: ["doctor", "does that token reach your board?"],
  notify: ["notify", "send yourself a test message"],
}

function same(left: unknown, right: unknown): boolean {
  if (Array.isArray(left) && Array.isArray(right))
    return left.length === right.length && left.every((item, index) => item === right[index])
  return left === right
}

/* -- a field, both ways ---------------------------------------------------- */

/** What a field is worth to the form, before anybody types. */
function held(field: SettingField): SettingValue {
  if (field.kind === "secret") return ""
  if (field.kind === "bool")
    return field.value === null || field.value === undefined ? UNSET : String(field.value)
  if (field.kind === "choice") return (field.value as string) || UNSET
  if (field.kind === "events") {
    // Nothing stated means the three the runner would send anyway, shown
    // ticked: a list of moments has no greyed placeholder to fall back on.
    const fallback = Array.isArray(field.fallback) ? (field.fallback as string[]) : []
    return (field.value as string[] | null) ?? fallback
  }
  if (field.kind === "lines") {
    // The rules the runner reads are the ones shown, so that "default" is text
    // you can edit rather than a greyed hint: one per line, in a single box.
    const fallback = Array.isArray(field.fallback) ? (field.fallback as string[]) : []
    return ((field.value as string[] | null) ?? fallback).join("\n")
  }
  if (field.kind === "int") return field.value === null ? "" : (field.value as number)
  return field.value === null ? "" : String(field.value)
}

/** The same, as the file may hold it — or `null`, which removes the line. */
function told(field: SettingField, value: unknown): SettingValue {
  if (field.kind === "bool") return value === UNSET ? null : value === "true"
  if (field.kind === "choice") return value === UNSET || !value ? null : String(value)
  if (field.kind === "events") {
    // In the order the server lists them, so that ticking a box off and back
    // on is not a change of its own.
    const chosen = new Set(Array.isArray(value) ? value.map(String) : [])
    return field.choices.filter((choice) => chosen.has(choice))
  }
  if (field.kind === "lines")
    return String(value ?? "")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
  if (field.kind === "secret") return value === FORGOTTEN ? null : String(value ?? "").trim()
  if (field.kind === "int") {
    const text = String(value ?? "").trim()
    return text === "" ? null : Number(text)
  }
  return String(value ?? "").trim()
}

/** A choice as the page says it: its words when the server gave some, else the value. */
const worded = (field: SettingField, value: string) => field.options?.[value] ?? value

/** The greyed answer in a box: what happens if you say nothing. */
function placeholder(field: SettingField): string {
  if (field.kind === "secret")
    return field.preview
      ? translate("set · ends {{preview}}", { preview: field.preview })
      : translate("not set")
  if (field.fallback === "" || field.fallback === null || field.fallback === undefined) {
    // A placeholder is plain text: the code spans of the sentence lose their marks.
    if (field.placeholder) return translate(field.placeholder).replaceAll("`", "")
    return field.name.endsWith("prompt_file")
      ? translate("Ponos's default instructions")
      : translate("not set")
  }
  return translate("default · {{value}}", { value: String(field.fallback) })
}

/* -- the controls ------------------------------------------------------------ */

/** A form input that remembers which setting it draws. */
interface SettingInput extends FormInputInterface {
  setting: SettingField
}

const settingOf = (formInput: FormInputInterface) => (formInput as SettingInput).setting

/* Yes or no, as a switch. The file has a third answer — nothing, which is the
 * runner's own default — and the switch shows what that default is. Flipping
 * it back to the default on a field the file said nothing about leaves the
 * file saying nothing, rather than writing the default down. */
const SwitchController = ({ formInput, onChange }: InputControllerInterface) => {
  const field = settingOf(formInput)
  const on = formInput.value === UNSET ? Boolean(field.fallback) : formInput.value === "true"
  return (
    <Switch
      id={formInput.id}
      checked={on}
      // What this machine lacks greys it out — and still lets a switch left on be turned off.
      disabled={Boolean(field.unavailable) && !on}
      onCheckedChange={(next) =>
        onChange({
          ...formInput,
          value: field.value === null && next === Boolean(field.fallback) ? UNSET : String(next),
        })
      }
    />
  )
}

/* The moments a message is sent at, as three buttons that stay pressed: there
 * are three of them, and a list that drops down to show three is a list in the
 * way. */
const EventsController = ({ formInput, onChange }: InputControllerInterface) => {
  const t = useT()
  const field = settingOf(formInput)
  const chosen = new Set(Array.isArray(formInput.value) ? (formInput.value as string[]) : [])
  return (
    <div id={formInput.id} role="group" className="flex flex-wrap gap-2">
      {field.choices.map((choice) => {
        const pressed = chosen.has(choice)
        return (
          <Button
            key={choice}
            type="button"
            size="sm"
            variant={pressed ? "default" : "outline"}
            aria-pressed={pressed}
            onClick={() => {
              const next = new Set(chosen)
              if (pressed) next.delete(choice)
              else next.add(choice)
              onChange({ ...formInput, value: field.choices.filter((item) => next.has(item)) })
            }}
          >
            {t(worded(field, choice))}
          </Button>
        )
      })}
    </div>
  )
}

/* One rule a line, in a box tall enough to read them: the lists are sentences,
 * and a single-line input would show the first twenty words of the first. */
const LinesController = ({ formInput, onChange }: InputControllerInterface) => (
  <Textarea
    id={formInput.id}
    name={formInput.name}
    rows={Math.min(Math.max(String(formInput.value ?? "").split("\n").length + 1, 4), 12)}
    value={String(formInput.value ?? "")}
    onChange={(event) => onChange({ ...formInput, value: event.target.value })}
  />
)

/* A number, its unit beside it, and the one thing the package's number control
 * cannot say: nothing at all. It reads an emptied box as `Number("")`, which is
 * zero — and zero is an interval the runner would refuse. Here an empty box
 * stays empty, which is how the default comes back. */
const CountController = ({ formInput, onChange }: InputControllerInterface) => {
  const t = useT()
  const field = settingOf(formInput)
  return (
    <div className="flex items-center gap-2">
      <Input
        id={formInput.id}
        name={formInput.name}
        type="number"
        inputMode="numeric"
        autoComplete="off"
        className="w-40"
        value={formInput.value === undefined || formInput.value === null ? "" : String(formInput.value)}
        placeholder={formInput.placeholder}
        onChange={(event) => {
          const text = event.target.value.trim()
          onChange({ ...formInput, value: text === "" ? "" : Number(text) })
        }}
      />
      {field.unit ? <span className="text-muted-foreground text-sm">{t(field.unit)}</span> : null}
    </div>
  )
}

/* A secret is not a password field with a value: it is a field whose value is
 * deliberately absent. Typing sets it, leaving it alone leaves it alone, and
 * forgetting one has to be a gesture of its own. The eye shows what you are
 * typing — the saved one never comes to the browser, so it cannot show that. */
const SecretController = ({ formInput, onChange }: InputControllerInterface) => {
  const t = useT()
  const field = settingOf(formInput)
  const [shown, setShown] = React.useState(false)
  const [trying, setTrying] = React.useState(false)
  const [tried, setTried] = React.useState<{ ok: boolean; said: string } | null>(null)
  const forgotten = formInput.value === FORGOTTEN
  const typed = forgotten ? "" : String(formInput.value ?? "").trim()
  const testable = TRIED.has(field.name) && !forgotten && Boolean(typed || field.preview)
  const test = async () => {
    setTrying(true)
    setTried(null)
    try {
      setTried(await api.saveProvider({ provider: "api_key", key: typed, save: false }))
    } catch (error) {
      setTried({ ok: false, said: why(error) })
    } finally {
      setTrying(false)
    }
  }
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Input
            id={formInput.id}
            name={formInput.name}
            type={shown ? "text" : "password"}
            autoComplete="off"
            spellCheck={false}
            className="pr-10"
            value={forgotten ? "" : String(formInput.value ?? "")}
            placeholder={forgotten ? t("not set") : formInput.placeholder}
            onChange={(event) => {
              setTried(null)
              onChange({ ...formInput, value: event.target.value })
            }}
          />
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-md"
            aria-label={shown ? t("Hide") : t("Show")}
            title={t("Shows what you type: the saved one never leaves this machine.")}
            onClick={() => setShown(!shown)}
          >
            {shown ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
        {field.preview && !forgotten ? (
          <Button type="button" variant="outline" size="sm" onClick={() => onChange({ ...formInput, value: FORGOTTEN })}>
            {t("Forget")}
          </Button>
        ) : null}
        {testable ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={trying}
            onClick={() => void test()}
          >
            {trying ? <Loader2Icon className="size-4 animate-spin" /> : null}
            {t("Test the connection")}
          </Button>
        ) : null}
        {forgotten ? (
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange({ ...formInput, value: "" })}>
            {t("Keep it")}
          </Button>
        ) : null}
      </div>
      {tried ? (
        <p
          role="status"
          className={cn(
            "flex items-center gap-1.5 text-[13px]",
            tried.ok ? "text-emerald-700 dark:text-emerald-300" : "text-destructive"
          )}
        >
          {tried.ok ? <CircleCheck className="size-4 shrink-0" /> : <CircleAlert className="size-4 shrink-0" />}
          {tried.said}
        </p>
      ) : null}
    </div>
  )
}

/** A path inside a folder, without doubling the slash a root ends on. */
const inside = (folder: string, name: string) => `${folder.replace(/\/+$/, "")}/${name}`

/* A path on the machine the runner is on, typed or picked.
 *
 * The browser's own picker hands back a file's name and never its path — and
 * the file, in any case, is on the runner's machine, which is not always the
 * one the browser is on. So the picker asks the server what a folder holds, a
 * folder at a time. */
const PathController = ({ formInput, onChange }: InputControllerInterface) => {
  const t = useT()
  const field = settingOf(formInput)
  const [open, setOpen] = React.useState(false)
  const [listing, setListing] = React.useState<Folder | null>(null)
  const [problem, setProblem] = React.useState("")
  const value = String(formInput.value ?? "")

  const look = async (path: string) => {
    setProblem("")
    try {
      setListing(await api.folder(path))
    } catch (error) {
      setProblem(why(error))
    }
  }
  const choose = (path: string) => {
    onChange({ ...formInput, value: path })
    setOpen(false)
  }

  return (
    <div className="flex items-center gap-2">
      <Input
        id={formInput.id}
        name={formInput.name}
        autoComplete="off"
        spellCheck={false}
        className="min-w-0 flex-1 font-mono text-[13px]"
        value={value}
        placeholder={formInput.placeholder}
        onChange={(event) => onChange({ ...formInput, value: event.target.value })}
      />
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next)
          if (next) void look(value || String(field.fallback ?? ""))
        }}
      >
        <PopoverTrigger asChild>
          <Button type="button" variant="outline" size="sm">
            <FolderOpen />
            {t("Browse")}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-80 p-0" data-testid="path-picker">
          {listing ? (
            <>
              <div className="flex items-center gap-1 border-b p-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  disabled={!listing.parent}
                  aria-label={t("Up one folder")}
                  onClick={() => void look(listing.parent)}
                >
                  <CornerLeftUp />
                </Button>
                <span className="min-w-0 truncate font-mono text-xs" title={listing.folder}>
                  {listing.folder}
                </span>
              </div>
              <ul className="max-h-64 overflow-y-auto py-1">
                {listing.entries.map((entry) => (
                  <li key={entry.name}>
                    <button
                      type="button"
                      className="hover:bg-muted flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm"
                      onClick={() =>
                        entry.folder
                          ? void look(inside(listing.folder, entry.name))
                          : choose(inside(listing.folder, entry.name))
                      }
                    >
                      {entry.folder ? (
                        <FolderIcon className="text-muted-foreground size-4 shrink-0" />
                      ) : (
                        <FileIcon className="text-muted-foreground size-4 shrink-0" />
                      )}
                      <span className="truncate">{entry.name}</span>
                    </button>
                  </li>
                ))}
                {!listing.entries.length ? (
                  <li className="text-muted-foreground px-3 py-1.5 text-sm">{t("An empty folder.")}</li>
                ) : null}
                {listing.more ? (
                  <li className="text-muted-foreground px-3 py-1.5 text-xs">
                    {t("{{count}} more — type the rest of the path.", { count: String(listing.more) })}
                  </li>
                ) : null}
              </ul>
              <div className="border-t p-2">
                <Button type="button" size="sm" className="w-full" onClick={() => choose(listing.folder)}>
                  {t("Choose this folder")}
                </Button>
              </div>
            </>
          ) : (
            <p className={cn("p-3 text-sm", problem ? "text-destructive" : "text-muted-foreground")}>
              {problem || t("Reading the folder…")}
            </p>
          )}
        </PopoverContent>
      </Popover>
    </div>
  )
}

/* -- one field, laid out ------------------------------------------------------ */

/* The « ? » beside a label: the whole sentence of help, of which the line
 * under the field is only the start, and what has to happen for a change to
 * count. A popover rather than a tooltip, because a phone has no hover. Also
 * drawn by a project's own settings, beside the same labels. */
export function MoreHelp({ field }: { field: Pick<SettingField, "label" | "help"> & { after?: string } }) {
  const t = useT()
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground inline-flex size-5 items-center justify-center rounded-full"
          aria-label={t("More about “{{label}}”", { label: t(field.label) })}
        >
          <CircleHelp className="size-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 text-sm leading-relaxed">
        <p>
          <Rich text={t(field.help)} />
        </p>
        {field.after ? (
          <p className="text-muted-foreground mt-2 text-xs">
            {t("takes effect once")} <Rich text={t(field.after)} />
          </p>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}

/* A field: its label in bold, its control, a sentence of what it does — the rest
 * behind the « ? » — and, for whoever asked to see them, its key. A switch sits
 * at the right of its label, the way a phone's settings put it; anything else
 * goes under it, the width of the column. */
function SettingRow({ formInput, onChange, formInputComponent: Control }: FormGroupProviderPropsInterface) {
  const t = useT()
  const keys = useKeysShown()
  const field = settingOf(formInput)
  const id = formInput.id ?? `field-${formInput.name}`
  const [line] = splitHelp(t(field.help))

  const label = (
    <div className="flex min-w-0 items-center gap-1">
      <Label htmlFor={id} className="leading-snug font-semibold">
        {t(field.label)}
      </Label>
      {field.help || field.after ? <MoreHelp field={field} /> : null}
    </div>
  )
  const description = line ? (
    <p className="text-muted-foreground mt-1 text-[13px] leading-snug">
      <Rich text={line} />
    </p>
  ) : null
  const control = <Control formInput={{ ...formInput, id }} onChange={onChange} />

  return (
    <div
      data-field={formInput.name}
      className="scroll-mt-28 rounded-md py-4 transition-colors duration-700 first:pt-1 data-found:bg-primary/10"
    >
      {field.kind === "bool" ? (
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            {label}
            {description}
          </div>
          <div className="shrink-0 pt-0.5">{control}</div>
        </div>
      ) : (
        <>
          {label}
          {description}
          <div className="mt-2.5">{control}</div>
        </>
      )}
      {field.unavailable ? (
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-400" data-slot="setting-unavailable">
          {t(field.unavailable)}
        </p>
      ) : null}
      {field.environment ? (
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
          <Rich text={t("Given by the environment variable `{{name}}`.", { name: field.environment })} />
        </p>
      ) : null}
      {keys ? (
        <code
          className="text-muted-foreground mt-2 block font-mono text-[11px]"
          title={
            field.variable
              ? t("Its variable, in secrets.env or the environment")
              : t("Its key in config.toml")
          }
        >
          {field.variable ?? field.name}
        </code>
      ) : null}
      <FormInputViolation formInput={formInput} />
    </div>
  )
}

/* -- the model table -------------------------------------------------------- */

/* Fourteen fields that are one table: down the side, the four levels and the
 * model each runs on; across, the four types of ticket, a dot on the level each
 * starts at. Laid flat they read as fourteen unrelated settings; as a table,
 * as the one decision they are. */
function ModelGrid({ section, inputs }: { section: SettingSection; inputs: Map<string, FormInputInterface> }) {
  const t = useT()
  const keys = useKeysShown()
  const { onChange } = useFormContext()
  const levels = section.fields.filter((field) => field.grid === "level")
  const types = section.fields.filter((field) => field.grid === "type")
  const order = types[0]?.choices ?? []
  const subtypes = section.fields.filter((field) => field.grid === "subtype")
  const shifts = subtypes[0]?.choices ?? []

  return (
    <div className="mt-2 border-t pt-4" data-testid="model-grid">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] border-collapse text-sm">
          <caption className="sr-only">{t("Model per level, and where each type of ticket starts")}</caption>
          <thead>
            <tr className="text-muted-foreground text-xs">
              <th scope="col" className="pb-2 text-left font-medium">
                {t("Level")}
              </th>
              <th scope="col" className="pb-2 text-left font-medium">
                {t("Model")}
              </th>
              {types.map((type) => (
                <th key={type.name} scope="col" className="px-1 pb-2 text-center font-medium">
                  {t(type.short ?? type.label)}
                  {keys ? <code className="block font-mono text-[10px] font-normal">{type.name}</code> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {order.map((level) => {
              const field = levels.find((item) => item.name.endsWith(`_${level}`))
              const input = field ? inputs.get(inputName(field.name)) : undefined
              return (
                <tr
                  key={level}
                  data-field={field ? inputName(field.name) : undefined}
                  className="border-t transition-colors duration-700 data-found:bg-primary/10"
                >
                  <th scope="row" className="py-2 pr-3 text-left font-semibold">
                    {t(field?.short ?? level)}
                    {keys && field ? (
                      <code className="text-muted-foreground block font-mono text-[10px] font-normal">{field.name}</code>
                    ) : null}
                  </th>
                  <td className="py-2 pr-3">
                    {field && input ? (
                      <Input
                        aria-label={t(field.label)}
                        title={t(field.help)}
                        autoComplete="off"
                        spellCheck={false}
                        className="h-8 w-32 font-mono text-[13px]"
                        value={String(input.value ?? "")}
                        placeholder={String(field.fallback ?? "")}
                        onChange={(event) => onChange({ ...input, value: event.target.value })}
                      />
                    ) : null}
                  </td>
                  {types.map((type) => {
                    const typeInput = inputs.get(inputName(type.name))
                    if (!typeInput) return <td key={type.name} />
                    const starts = typeInput.value === UNSET ? type.fallback : typeInput.value
                    return (
                      <td key={type.name} className="px-1 py-2 text-center">
                        <input
                          type="radio"
                          name={inputName(type.name)}
                          className="accent-primary size-4 cursor-pointer align-middle"
                          checked={starts === level}
                          aria-label={`${t(type.short ?? type.label)} — ${t(field?.short ?? level)}`}
                          onChange={() =>
                            onChange({
                              ...typeInput,
                              // Back on the default of a type the file said nothing
                              // about: it goes on saying nothing.
                              value: !type.value && level === type.fallback ? UNSET : level,
                            })
                          }
                        />
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="text-muted-foreground mt-2 text-xs leading-relaxed">
        {t("Each column is a type of ticket: the dot is the level it starts at, before its size and wording move it. An empty model is the nearest level's.")}
      </p>
      {/* Code, by its sub-types: where each starts from Code's own level —
          the same dots, one table further down, since it is the same choice
          made finer. A sub-type added to subtypes.py is a column here. */}
      {subtypes.length ? (
        <div className="mt-4 overflow-x-auto" data-testid="model-grid-subtypes">
          <table className="w-full min-w-[40rem] border-collapse text-sm">
            <caption className="sr-only">{t("Where each sub-type of a code ticket starts, from Code's level")}</caption>
            <thead>
              <tr className="text-muted-foreground text-xs">
                <th scope="col" className="pb-2 text-left font-medium">
                  {t("Code, by sub-type")}
                </th>
                {subtypes.map((subtype) => (
                  <th key={subtype.name} scope="col" className="px-1 pb-2 text-center font-medium">
                    {/* The sub-type's own word, untranslated: see SUBTYPES in subtypes.py. */}
                    {subtype.short ?? t(subtype.label)}
                    {keys ? <code className="block font-mono text-[10px] font-normal">{subtype.name}</code> : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shifts.map((shift) => (
                <tr key={shift} className="border-t">
                  <th scope="row" className="py-2 pr-3 text-left font-semibold">
                    {t(subtypes[0]?.options?.[shift] ?? shift)}
                  </th>
                  {subtypes.map((subtype) => {
                    const input = inputs.get(inputName(subtype.name))
                    if (!input) return <td key={subtype.name} />
                    const moves = input.value === UNSET ? subtype.fallback : input.value
                    return (
                      <td
                        key={subtype.name}
                        data-field={inputName(subtype.name)}
                        className="px-1 py-2 text-center transition-colors duration-700 data-found:bg-primary/10"
                      >
                        <input
                          type="radio"
                          name={inputName(subtype.name)}
                          className="accent-primary size-4 cursor-pointer align-middle"
                          checked={moves === shift}
                          aria-label={`${subtype.short ?? t(subtype.label)} — ${t(subtype.options?.[shift] ?? shift)}`}
                          onChange={() =>
                            onChange({
                              ...input,
                              value: !subtype.value && shift === subtype.fallback ? UNSET : shift,
                            })
                          }
                        />
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-muted-foreground mt-2 text-xs leading-relaxed">
            {t("A code ticket starts at Code's level, moved by its sub-type — never past the lightest or the heaviest level, and Fable only when it is allowed.")}
          </p>
        </div>
      ) : null}
    </div>
  )
}

/* -- cards, and what folds ---------------------------------------------------- */

/** What a page hands its cards: what it adds to some of them, and what was last saved. */
interface GroupExtras {
  group: string
  fields: SettingField[]
  /** Drawn at the top of a card — the console's own language, on the languages card. */
  extra: (section: SettingSection) => React.ReactNode
  /** A card that is a list of rows rather than of fields: `[projects]`, `[github]`. */
  pairs: (section: SettingSection) => React.ReactNode
  note: SaveNote | null
}

const GroupContext = React.createContext<GroupExtras>({
  group: "",
  fields: [],
  extra: () => null,
  pairs: () => null,
  note: null,
})

/* The blocks somebody unfolded, for as long as the page is open: coming back to
 * a page shows it the way it was left. */
const UNFOLDED = new Set<string>()

/** Whether a field or a card the search asked for is among these. */
const among = (target: string, fields: SettingField[], cards: string[] = []) =>
  !!target && (cards.includes(target) || fields.some((field) => field.name === target))

/* What folds: a card's advanced settings, or the block of cards at the end of a
 * page. Open when you opened it, when something typed in it is waiting to be
 * saved — a change you cannot see is a change you save without knowing — or
 * when a search leads into it. */
function useFold(key: string, fields: SettingField[], cards: string[] = []) {
  const { form } = useFormContext()
  const target = useAsked()
  const [open, setOpen] = React.useState(() => UNFOLDED.has(key))
  React.useEffect(() => {
    if (among(target, fields, cards)) setOpen(true)
    // `fields` and `cards` are the description's, fixed for this form.
  }, [target]) // eslint-disable-line react-hooks/exhaustive-deps
  const typed = Object.keys(written(fields, form.data as Record<string, SettingValue>)).length > 0
  const toggle = () => {
    if (open) UNFOLDED.delete(key)
    else UNFOLDED.add(key)
    setOpen(!open)
  }
  return { open: open || typed, typed, toggle }
}

function Advanced({ section, children }: { section: SettingSection; children: React.ReactNode }) {
  const t = useT()
  const fields = section.fields.filter((field) => field.advanced)
  const { open, typed, toggle } = useFold(`advanced:${section.key}`, fields)
  return (
    <div className="mt-1 border-t pt-2">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="text-muted-foreground -ml-2"
        aria-expanded={open}
        disabled={typed}
        onClick={toggle}
      >
        <ChevronDown className={cn("transition-transform", open && "rotate-180")} />
        {open
          ? t("Hide the advanced settings")
          : t("Show the advanced settings ({{count}})", { count: String(fields.length) })}
      </Button>
      <div hidden={!open} className="divide-y">
        {children}
      </div>
    </div>
  )
}

function FoldBlock({
  fold,
  sections,
  children,
}: {
  fold: SettingFold
  sections: SettingSection[]
  children: React.ReactNode
}) {
  const t = useT()
  const fields = sections.flatMap((section) => section.fields)
  const { open, typed, toggle } = useFold(
    `fold:${fold.key}`,
    fields,
    sections.map((section) => section.key)
  )
  return (
    <section data-fold={fold.key} className="rounded-xl border border-dashed">
      <button
        type="button"
        className="flex w-full items-start gap-3 rounded-xl p-5 text-left disabled:cursor-default"
        aria-expanded={open}
        disabled={typed}
        onClick={toggle}
      >
        <ChevronDown className={cn("text-muted-foreground mt-0.5 size-4 shrink-0 transition-transform", open && "rotate-180")} />
        <span className="min-w-0">
          <span className="block font-semibold">{t(fold.title)}</span>
          <span className="text-muted-foreground mt-1 block text-[13px] leading-relaxed">
            <Rich text={t(fold.blurb)} />
          </span>
        </span>
      </button>
      <div hidden={!open} className="flex flex-col gap-5 px-3 pb-3 sm:px-5 sm:pb-5">
        {children}
      </div>
    </section>
  )
}

function SettingCard({ section, inputs }: { section: SettingSection; inputs: Map<string, FormInputInterface> }) {
  const t = useT()
  const { extra, pairs } = React.useContext(GroupContext)
  const { runCommand } = useConsole()
  const row = (field: SettingField) => {
    const formInput = inputs.get(inputName(field.name))
    return formInput ? <InputControllerProvider key={field.name} formInput={formInput} /> : null
  }
  const check = CHECKS[section.key]
  const essentials = section.fields.filter((field) => !field.advanced && !field.grid)
  const advanced = section.fields.filter((field) => field.advanced)

  return (
    <Card
      id={cardId(section.key)}
      data-card={section.key}
      className="scroll-mt-28 gap-0 py-0 transition-shadow duration-700 data-found:ring-primary/50 data-found:ring-2"
    >
      <CardHeader className="gap-1 px-5 pt-5 pb-2 sm:px-6">
        <CardTitle className="text-base">{t(section.title)}</CardTitle>
        <CardDescription className="text-[13px] leading-relaxed">
          <Rich text={t(section.blurb)} />
        </CardDescription>
        {check ? (
          <CardAction>
            <Button
              type="button"
              variant="outline"
              size="xs"
              className="font-mono"
              title={t(check[1])}
              onClick={() => {
                // The answer lands in the console's transcript, which is behind the
                // bubble: a check you cannot read is a check nobody ran.
                openTalk()
                void runCommand(check[0])
              }}
            >
              &gt; {check[0]}
            </Button>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="px-5 pb-4 sm:px-6">
        {extra(section)}
        {section.pairs ? pairs(section) : null}
        {essentials.length ? <div className="divide-y">{essentials.map(row)}</div> : null}
        {section.layout === "grid" ? <ModelGrid section={section} inputs={inputs} /> : null}
        {advanced.length ? <Advanced section={section}>{advanced.map(row)}</Advanced> : null}
      </CardContent>
    </Card>
  )
}

/* The page's cards, where the package would have drawn a grid of fields: the
 * open ones in the order the server lists them, then each folded block. */
function GroupCards() {
  const { form } = useFormContext()
  const { group } = React.useContext(GroupContext)
  const inputs = new Map(
    getFormInputsFromForm(form).map((formInput) => [String(formInput.name), formInput])
  )
  const sections = sectionsIn(group)
  const folds = currentSettings()?.folds ?? []
  return (
    <div className="flex flex-col gap-5">
      {sections
        .filter((section) => !section.fold)
        .map((section) => (
          <SettingCard key={section.key} section={section} inputs={inputs} />
        ))}
      {folds.map((fold) => {
        const folded = sections.filter((section) => section.fold === fold.key)
        if (!folded.length) return null
        return (
          <FoldBlock key={fold.key} fold={fold} sections={folded}>
            {folded.map((section) => (
              <SettingCard key={section.key} section={section} inputs={inputs} />
            ))}
          </FoldBlock>
        )
      })}
    </div>
  )
}

/* Not a `<form>`: the cards of projects and GitHub accounts open dialogs with
 * forms of their own, and a submit there would bubble, through the portal, to
 * this one. Enter in a field saves nothing anyway — the bar does. */
const Plain = ({ children, className }: FormDecoratorPropsInterface) => (
  <div className={className}>{children}</div>
)

/* -- the page, as a declaration -------------------------------------------- */

function input(field: SettingField): SettingInput {
  const shared: SettingInput = {
    name: inputName(field.name),
    // Drawn by `SettingRow`, which translates it.
    label: field.label,
    placeholder: placeholder(field),
    setting: field,
  }

  if (field.kind === "bool") return { ...shared, controller: SwitchController }

  if (field.kind === "choice")
    return {
      ...shared,
      controller: SelectInputController,
      valueOptions: [
        {
          // A default nobody wrote is still a line in the list, and an empty
          // `{{value}}` would be read as a key rather than as nothing at all.
          value: UNSET,
          label: translate("default · {{value}}", {
            value: field.fallback ? translate(worded(field, String(field.fallback))) : "—",
          }),
        },
        ...field.choices.map((choice) => ({ value: choice, label: worded(field, choice) })),
      ],
    }

  if (field.kind === "events") return { ...shared, controller: EventsController }
  if (field.kind === "lines") return { ...shared, controller: LinesController }
  if (field.kind === "secret") return { ...shared, controller: SecretController }
  if (field.kind === "int") return { ...shared, controller: CountController }
  if (field.kind === "path") return { ...shared, controller: PathController }
  return shared
}

/** Every field of a page, keyed the way the form has to key it. */
export function fieldData(fields: SettingField[]): Record<string, SettingValue> {
  return Object.fromEntries(fields.map((field) => [inputName(field.name), held(field)]))
}

/** What the file would gain from these fields: only the lines that actually moved. */
export function written(
  fields: SettingField[],
  data: Record<string, SettingValue>
): Record<string, SettingValue> {
  const changes: Record<string, SettingValue> = {}
  for (const field of fields) {
    const now = told(field, data[inputName(field.name)])
    if (same(now, told(field, held(field)))) continue
    changes[field.name] = now
  }
  return changes
}

/* -- what a page is saved with ---------------------------------------------- */

/* The bar every page ends on: what is waiting to be saved, and the two gestures,
 * against the right edge.
 *
 * It is the form's own submit action rather than a footer drawn beside it, so
 * the count it shows is read off the form the package is holding rather than
 * off a second copy kept in a parent.
 *
 * It sticks to the bottom of the screen only while something is waiting to be
 * saved — that is the moment it must not be scrolled away from. The room at its
 * right end then is the discussion's bubble, which floats over the bottom
 * corner of every page: without it, Save sat under the bubble. On a phone it
 * sticks to the top of the bottom bar rather than behind it. */
function SaveBar() {
  const { form, onSubmit, updateData, isLoading } = useFormContext()
  const { group, fields, note } = React.useContext(GroupContext)
  const t = useT()

  const changed = Object.keys(written(fields, form.data as Record<string, SettingValue>)).length
  const saving = isLoading.value
  const status = saving
    ? { text: t("Saving…"), tone: "text-muted-foreground" }
    : changed > 0
      ? { text: t("Unsaved changes"), tone: "text-foreground" }
      : note?.bad
        ? { text: note.text, tone: "text-destructive" }
        : note
          ? { text: t("Saved ✓"), tone: "text-tr-green" }
          : { text: t("No changes"), tone: "text-muted-foreground" }

  return (
    <div
      data-testid="settings-bar"
      className={cn(
        "mt-6 flex flex-wrap items-center justify-end gap-2 border-t py-3",
        changed > 0 &&
          "bg-background/95 sticky bottom-(--bottom-nav) z-10 pr-16 shadow-[0_-6px_12px_-8px_rgb(0_0_0/0.2)] backdrop-blur"
      )}
    >
      <span
        role="status"
        className={cn("mr-auto flex min-w-0 items-center gap-1.5 text-xs select-none", status.tone)}
      >
        {changed > 0 && !saving ? (
          <span aria-hidden className="bg-primary size-1.5 shrink-0 rounded-full" />
        ) : null}
        {status.text}
      </span>
      <Button
        type="button"
        variant="secondary"
        disabled={!changed || saving}
        onClick={() => {
          forgetDraft(group)
          updateData(fieldData(fields), false)
        }}
      >
        {t("Cancel")}
      </Button>
      <Button
        type="button"
        className="disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100"
        disabled={!changed || saving}
        onClick={() => void onSubmit()}
      >
        {saving ? <Loader2Icon className="animate-spin" /> : null}
        {saving ? t("Saving…") : t("Save")}
      </Button>
    </div>
  )
}

function groupForm(fields: SettingField[]): FormInterface {
  return {
    label: { submit: "Save" },
    components: {
      formSubmitAction: SaveBar,
      formInputs: GroupCards,
      formGroupProvider: SettingRow,
      formDecorator: Plain,
    },
    inputs: Object.fromEntries(fields.map((field) => [inputName(field.name), input(field)])),
  }
}

/** What a save came back with, said in the words the fields are said in. */
export interface SaveNote {
  text: string
  bad: boolean
}

export function GroupForm({
  group,
  extra,
  pairs,
  note,
  onSaved,
}: {
  group: string
  extra: GroupExtras["extra"]
  pairs: GroupExtras["pairs"]
  note: SaveNote | null
  onSaved: (note: SaveNote) => void
}) {
  const { reloadState } = useConsole()
  // Read once: the form is keyed by the description's revision, so a new one
  // is a new form rather than this one changing under you.
  const fields = React.useMemo(
    () => sectionsIn(group).flatMap((section) => section.fields),
    [group]
  )
  const form = React.useMemo(() => groupForm(fields), [fields])
  const data = React.useMemo(() => draftOf(group) ?? fieldData(fields), [group, fields])

  const context = useForm({
    form,
    data,
    // Only one page is drawn at a time, so a page leaving the screen would
    // otherwise take what you typed on it with it.
    onChange: (typed) => {
      const current = typed as Record<string, SettingValue>
      rememberDraft(group, current, Object.keys(written(fields, current)).length > 0)
    },
    onSubmit: async (typed) => {
      const changes = written(fields, typed as Record<string, SettingValue>)
      if (!Object.keys(changes).length) {
        onSaved({ bad: false, text: translate("Nothing to save — the file already said that.") })
        return
      }
      try {
        const result = await api.saveSettings({ settings: changes })
        forgetDraft(group)
        // The description is read again rather than patched: a token that has
        // just been set comes back as a preview, and a line that has just been
        // removed comes back as the default it fell through to.
        publishSettings(await api.settings())
        await reloadState()
        // A 200 is the server saying it wrote; what it wrote is a courtesy, and
        // a save is not going to be reported as a failure over a missing list.
        const saved = result.saved ?? []
        // The server says what has to happen in the same words the fields do,
        // so the sentence is translated the same way they are.
        const after = (result.after ?? []).map((one) => translate(one))
        const how =
          saved.length === 1
            ? translate("one setting")
            : translate("{{count}} settings", { count: String(saved.length) })
        onSaved({
          bad: false,
          text:
            translate("Saved {{how}}: {{names}}.", { how, names: saved.join(", ") }) +
            (after.length
              ? " " + translate("Takes effect once {{after}}.", { after: after.join("; ") })
              : ""),
        })
      } catch (error) {
        // On the page itself, not in the transcript: on a phone the console is
        // a tab away, and a save you have to go looking for is one you doubt.
        onSaved({ bad: true, text: translate("Not saved: {{why}}", { why: why(error) }) })
      }
    },
  })

  return (
    <GroupContext.Provider value={{ group, fields, extra, pairs, note }}>
      <FormElement {...context} />
    </GroupContext.Provider>
  )
}
