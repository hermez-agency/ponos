import * as React from "react"
import { ExternalLink, Globe, History, KeyRound, Lock, LockOpen, Plus, RefreshCw, Trash2, Users } from "lucide-react"
import {
  FormElement,
  InputControllerProvider,
  getFormInputsFromForm,
  useForm,
  useFormContext,
  type FormContextOutput,
  type FormDecoratorPropsInterface,
  type FormGroupProviderPropsInterface,
  type FormInputInterface,
  type FormInterface,
  type InputControllerComponentInterface,
  type ViolationInterface,
} from "react-data-form"
import { toast } from "sonner"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { ApiError, api, why } from "@/lib/api"
import { refusals } from "@/lib/refusals"
import { Worded, t, useT } from "@/lib/i18n"
import { settingsFrench } from "@/lib/settings-store"
import type { Vault, VaultEntry, VaultMoment } from "@/lib/types"

import { ConfirmDialog } from "./confirm-dialog"
import { when } from "./ticket-bits"

/* The settings' Vault page: the keys, logins and notes a ticket's session is
 * given, kept encrypted by Ponos itself (`vault_store.py`).
 *
 * Write-only. A value is typed, sent, and never seen again — no route answers
 * it, and nothing here keeps it: the secret fields are left uncontrolled, read
 * from the form the moment it is sent and emptied right after, so no value
 * sits in a React state, a store, a cache or `localStorage`. There is no
 * "show": a value is replaced, never read back.
 *
 * The vault is locked until the console's password is typed once, on the page
 * itself (`Locked`); from then on no form asks for it. Whether it is open is the
 * server's to say (`proven`, kept by `web/sessions.py` for this browser and
 * carried further by every write) — the page only draws it. Locked while open
 * (fifteen minutes unused, another tab's Lock), a write is refused: the
 * password is asked over the form, which keeps what was typed, and the write
 * is sent again (`Guard`).
 *
 * The locked page shows nothing but the lock. The names are no secret — the
 * server lists them to an admin either way — but a page of rows whose every
 * button needs the password first is a page of buttons that do not work.
 */

const SELECT =
  "border-input bg-background h-9 w-full rounded-md border px-2 text-sm shadow-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"

const KINDS: { kind: VaultEntry["kind"]; label: string }[] = [
  { kind: "token", label: "API key / token" },
  { kind: "login", label: "Login + password" },
  { kind: "note", label: "Secret note" },
]

const labelOf = (kind: string) => KINDS.find((one) => one.kind === kind)?.label ?? kind

const ACTIONS: Record<VaultMoment["action"], string> = {
  created: "entry created",
  replaced: "value replaced",
  projects: "projects changed",
  described: "description changed",
  url: "site changed",
  revoked: "entry revoked",
  read: "given to a session",
  rotated: "sealed under a new key",
  login: "signed in by Ponos's browser",
  "login-failed": "sign-in failed",
  "login-second-factor": "sign-in stopped on a second factor",
  "login-refused": "sign-in refused",
}

/** A write refused because the vault is locked for this browser: the password is what it wants. */
function locked(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && Boolean(error.data.violations?.some((one) => one.propertyPath === "confirm"))
}

/** The vault was locked, and the password was not typed: the write was not sent. */
class StillLocked extends Error {}

/** Send a write; if the vault locked itself meanwhile, ask for the password over the page and send it again. */
type Guard = <T>(send: () => Promise<T>) => Promise<T>

/** Empty fields once their values are sent: the value is in the request, and nowhere else. */
function emptied(...fields: React.RefObject<HTMLInputElement | HTMLTextAreaElement | null>[]) {
  for (const field of fields) if (field.current) field.current.value = ""
}

/** The password field and its button: on the locked page, and over a form when the vault locked itself. */
function UnlockField({ field, problem, focused }: { field: React.RefObject<HTMLInputElement | null>; problem: string; focused?: boolean }) {
  const t = useT()
  return (
    <div className="flex flex-col gap-1.5 text-sm">
      <label className="flex flex-col gap-1.5">
        <span className="font-medium">{t("The console's password")}</span>
        <Input
          ref={field}
          type="password"
          autoComplete="current-password"
          name="vault-unlock"
          autoFocus={focused}
          data-slot="vault-unlock-password"
        />
      </label>
      {problem ? (
        <Alert variant="destructive">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  )
}

/** Unlock with what is in `field`: "" once open, else what to say. */
async function unlock(field: React.RefObject<HTMLInputElement | null>, t: ReturnType<typeof useT>): Promise<string> {
  const typed = field.current?.value ?? ""
  if (!typed) return t("Type the console's password.")
  try {
    await api.unlockVault(typed)
    return ""
  } catch (error) {
    return error instanceof ApiError && error.status === 403 ? t("Wrong password.") : why(error)
  } finally {
    if (field.current) field.current.value = ""
  }
}

/** The page of a locked vault: the lock, and nothing else. */
function Locked({ onUnlocked }: { onUnlocked: () => void }) {
  const t = useT()
  const field = React.useRef<HTMLInputElement>(null)
  const [problem, setProblem] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    const said = await unlock(field, t)
    setBusy(false)
    setProblem(said)
    if (said) field.current?.focus()
    else onUnlocked()
  }
  return (
    <Card data-card="vault-locked" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
        <CardTitle className="flex items-center gap-2 text-base">
          <Lock className="size-4" />
          {t("The vault is locked")}
        </CardTitle>
        <CardDescription className="text-[13px]">
          {t("Type the console's password once to open it — the token, on a console opened with it alone.")}
        </CardDescription>
      </CardHeader>
      <CardContent className="px-5 pb-5 sm:px-6">
        <form className="flex flex-col gap-3" onSubmit={(event) => void submit(event)}>
          <UnlockField field={field} problem={problem} focused />
          <div>
            <Button type="submit" size="sm" disabled={busy} data-slot="vault-unlock">
              <LockOpen />
              {t("Unlock")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

/** The password asked over the page, when a write found the vault locked: `answer` says whether it was typed. */
function Relock({ open, answer }: { open: boolean; answer: (unlocked: boolean) => void }) {
  const t = useT()
  const field = React.useRef<HTMLInputElement>(null)
  const [problem, setProblem] = React.useState("")
  // The window puts the focus on its button: the field is where the password goes.
  React.useEffect(() => {
    if (!open) return
    const timer = window.setTimeout(() => field.current?.focus(), 0)
    return () => window.clearTimeout(timer)
  }, [open])
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => {
        if (next) return
        setProblem("")
        answer(false)
      }}
      title={t("The vault locked itself")}
      description={t("Nothing typed is lost: unlock it, and the change goes on.")}
      confirm={t("Unlock")}
      onConfirm={async () => {
        const said = await unlock(field, t)
        setProblem(said)
        if (said) return false
        answer(true)
      }}
    >
      <div data-slot="vault-relock">
        <UnlockField field={field} problem={problem} />
      </div>
    </ConfirmDialog>
  )
}

/** The vault's state, discreetly: open, until when without action — and the lock. */
function State({ minutes, asleep, onLock }: { minutes: number; asleep: boolean; onLock: () => void }) {
  const t = useT()
  return (
    <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" data-slot="vault-state">
      {asleep ? (
        <span>{t("Locked after {{minutes}} min without action: the password is asked at the next change", { minutes })}</span>
      ) : (
        <span className="flex items-center gap-1.5">
          <LockOpen className="size-3.5" aria-hidden />
          {t("Unlocked · locks again after {{minutes}} min without action", { minutes })}
        </span>
      )}
      {asleep ? null : (
        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={onLock} data-slot="vault-lock">
          <Lock />
          {t("Lock")}
        </Button>
      )}
    </div>
  )
}

function Projects({
  known,
  chosen,
  onChange,
}: {
  known: string[]
  chosen: string[]
  onChange: (projects: string[]) => void
}) {
  const t = useT()
  const toggle = (name: string, on: boolean) =>
    onChange(on ? [...chosen, name] : chosen.filter((one) => one !== name))
  if (!known.length) return <p className="text-muted-foreground text-xs">{t("No project on the board yet.")}</p>
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-2" data-slot="vault-projects">
      {known.map((name) => (
        <label key={name} className="flex items-center gap-2 text-sm">
          <Checkbox checked={chosen.includes(name)} onCheckedChange={(on) => toggle(name, on === true)} aria-label={name} />
          {name}
        </label>
      ))}
    </div>
  )
}

/** The fields of a value, by kind — left uncontrolled, see the top of this file. */
function ValueFields({
  kind,
  value,
  user,
  password,
}: {
  kind: string
  value: React.RefObject<HTMLInputElement | HTMLTextAreaElement | null>
  user: React.RefObject<HTMLInputElement | null>
  password: React.RefObject<HTMLInputElement | null>
}) {
  const t = useT()
  if (kind === "login")
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5 text-sm">
          <span className="font-medium">{t("User")}</span>
          <Input ref={user} type="password" autoComplete="off" name="vault-user" data-slot="vault-user" />
        </label>
        <label className="flex flex-col gap-1.5 text-sm">
          <span className="font-medium">{t("Password")}</span>
          <Input ref={password} type="password" autoComplete="off" name="vault-password" data-slot="vault-password" />
        </label>
      </div>
    )
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-medium">{t("Value")}</span>
      {kind === "note" ? (
        <Textarea
          ref={value as React.RefObject<HTMLTextAreaElement | null>}
          rows={5}
          autoComplete="off"
          spellCheck={false}
          className="font-mono text-xs"
          name="vault-value"
          data-slot="vault-value"
        />
      ) : (
        <Input
          ref={value as React.RefObject<HTMLInputElement | null>}
          type="password"
          autoComplete="off"
          name="vault-value"
          data-slot="vault-value"
        />
      )}
    </label>
  )
}

/* What `vault_store._checked_url` keeps, said before the request: a bare host
 * is https, any other scheme than http(s) is refused — the address is drawn as
 * a link. The server checks it again. */
const SCHEME = /^[A-Za-z][A-Za-z0-9+.-]*:(?!\d)/

/** The address an entry's site is kept as, or null for one that is no site; "" for none. */
function siteAddress(typed: string): URL | null | "" {
  const url = typed.trim()
  if (!url) return ""
  const whole = SCHEME.test(url) ? url : `https://${url}`
  if (whole.length > 500 || /\s/.test(whole)) return null
  try {
    const parsed = new URL(whole)
    return (parsed.protocol === "https:" || parsed.protocol === "http:") && parsed.hostname ? parsed : null
  } catch {
    return null
  }
}

const NO_SITE = "This is not the address of a site: it starts with https:// (or http://), like https://dokploy.example.com."

/** A site as the list draws it: its domain alone, opening the whole address in a new tab. */
function SiteLink({ url }: { url: string }) {
  const t = useT()
  const site = siteAddress(url)
  if (!site) return null
  return (
    <a
      href={site.href}
      target="_blank"
      rel="noopener noreferrer"
      title={url}
      className="text-foreground inline-flex items-center gap-1 underline-offset-2 hover:underline"
      data-slot="vault-site-link"
      aria-label={t("Open {{site}} in a new tab", { site: site.hostname })}
    >
      {site.hostname.replace(/^www\./, "")}
      <ExternalLink className="size-3" aria-hidden />
    </a>
  )
}

/* Read, not emptied: a write the vault's lock stopped is sent again with them,
 * and one given up leaves them where they were typed. `emptied` once it is over. */
function values(
  kind: string,
  value: React.RefObject<HTMLInputElement | HTMLTextAreaElement | null>,
  user: React.RefObject<HTMLInputElement | null>,
  password: React.RefObject<HTMLInputElement | null>
) {
  return kind === "login"
    ? { user: user.current?.value ?? "", password: password.current?.value ?? "" }
    : { value: value.current?.value ?? "" }
}

/* -- a new entry --------------------------------------------------------------- */

/* The rules `vault_store` writes an entry by, said while it is typed — the
 * server is still the judge, and its refusals land under the same fields.
 *
 * A name is corrected rather than refused (`normalized`, as the server does):
 * `umami login` is UMAMI_LOGIN, and the variables it gives are shown under the
 * field as they will be. Only an empty name, the runner's own and one another
 * entry already gives are refused. A login's user is no secret and has no
 * length; a password, a key or a note needs `SHORTEST` characters, or Ponos
 * could not mask it in what a session writes. */

/** `vault.SHORTEST`: below it, a value could not be masked. */
const SHORTEST = 6

const NO_NAME = "Give the entry a name, in letters or digits: UMAMI, say."
const RESERVED = "{{variable}} is Ponos's own and never given to a project: choose another name."
const TAKEN = "This name is already given by the entry {{name}}: choose another one."
const NO_USER = "Type the user name."
const SHORT_PASSWORD = "The password needs at least {{count}} characters: shorter, Ponos could not mask it in what a session writes."
const SHORT_VALUE = "The value needs at least {{count}} characters: shorter, Ponos could not mask it in what a session writes."

/* What `vault_store` refuses with, recognised to be said in the page's
 * language: these sentences are the vault's alone, so they travel with this
 * page and its dictionary rather than in `refusals.ts`, which every page loads.
 * `tests/test_vault_store.py` holds them to the Python's. */
const said = (message: string) => {
  const found = REFUSED(message)
  return found ? t(found.key, found.params) : message
}
const REFUSED = refusals([
  NO_NAME,
  RESERVED,
  TAKEN,
  NO_USER,
  SHORT_PASSWORD,
  SHORT_VALUE,
  "{{expires}} is not a date: write it YYYY-MM-DD.",
  "{{url}} is not the address of a site: it starts with https://.",
  "An entry is one of {{kinds}}.",
])

/** A name as `vault_store.normalized` writes it: upper case, no accent, `_` for the rest. */
export function normalized(typed: string): string {
  const bare = typed.trim().normalize("NFKD").replace(/\p{M}/gu, "")
  const plain = bare
    .toUpperCase()
    .replace(/[^A-Z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_")
  return /^\d/.test(plain) ? `_${plain}` : plain
}

/** The variables an entry gives its sessions — its address's only once it has one. */
function given(name: string, kind: string, url = true): string[] {
  const own = kind === "login" ? [`${name}_USER`, `${name}_PASSWORD`] : [name]
  return url ? [...own, `${name}_URL`] : own
}

/** What the form holds. A secret field holds its length, never what is typed: see the top of this file. */
interface Draft {
  kind: VaultEntry["kind"]
  name: string
  value: number
  user: number
  password: number
  url: string
  projects: string[]
  description: string
  expires: string
}

const EMPTY: Omit<Draft, "kind"> = { name: "", value: 0, user: 0, password: 0, url: "", projects: [], description: "", expires: "" }

/** Why `typed` cannot name an entry of `kind`, given what the vault already holds — or nothing. */
function nameProblem(typed: string, kind: string, vault: Vault): string {
  const name = normalized(typed)
  if (!name) return t(NO_NAME)
  const mine = given(name, kind)
  const reserved = new Set(vault.reserved)
  const own = mine.find((variable) => reserved.has(variable) || variable.startsWith("PONOS_"))
  if (own) return t(RESERVED, { variable: own })
  const other = vault.entries.find((entry) => given(entry.name, entry.kind).some((variable) => mine.includes(variable)))
  return other ? t(TAKEN, { name: other.name }) : ""
}

/** The secret fields' elements, by name: read when the entry is sent, emptied once it is. */
type Secrets = Map<string, HTMLInputElement | HTMLTextAreaElement>

const SecretsContext = React.createContext<Secrets>(new Map())

/** The length a secret field counts toward `SHORTEST`: as the server strips it. */
const lengthOf = (typed: string, kind: string) => (kind === "note" ? typed.replace(/^\n+|\n+$/g, "") : typed.trim()).length

/** How long the typing pauses before what is wrong with a field is said. */
const PAUSE = 1000

/** Starts a new round of fields once an entry is kept: none of them has been typed in. */
const RoundContext = React.createContext(0)

/** What `formInput`'s rule says of its value now, given the whole draft: "" when nothing is wrong. */
function ruled(formInput: FormInputInterface, data: Draft): string {
  try {
    formInput.validator?.(formInput.value, data)
    return ""
  } catch (error) {
    return error instanceof Error ? error.message : String(error)
  }
}

/* A field and what is wrong with it, under it: one line, no explanation.
 *
 * Said while it is typed, without waiting for the form to be sent: the rule
 * the form checks at sending is read again here at each change, and what it
 * says is shown once the typing has paused for `PAUSE` — gone at once when it
 * is right. A field nobody typed in says nothing. What the sending refused —
 * the form's rules, or the server's — is drawn as it is, until the field
 * changes. */
function Field({ formInput, onChange, formInputComponent: Control }: FormGroupProviderPropsInterface) {
  const t = useT()
  const { form } = useFormContext()
  const data = form.data as Draft
  // A login's site is where Ponos's browser signs in with it: not optional in the same way.
  const label = formInput.name === "url" && data.kind === "login" ? "Site (sign-in page)" : String(formInput.label ?? "")
  const id = formInput.id ?? `vault-${formInput.name}`
  const [typed, setTyped] = React.useState(false)
  const [shown, setShown] = React.useState("")
  const live = typed ? ruled(formInput, data) : ""
  const value = JSON.stringify(formInput.value ?? null)
  React.useEffect(() => {
    if (!live) {
      setShown("")
      return
    }
    const timer = window.setTimeout(() => setShown(live), PAUSE)
    return () => window.clearTimeout(timer)
  }, [live, value])
  const refused = formInput.violations?.map((one: ViolationInterface) => one.message).join(" ")
  const problem = refused || shown
  return (
    <div className="flex flex-col gap-1.5 text-sm" data-field={formInput.name}>
      <label htmlFor={id} className="font-medium">
        {t(label)}
      </label>
      <Control
        formInput={{ ...formInput, id, violations: problem ? [{ propertyPath: formInput.name, message: problem }] : [] }}
        onChange={(next) => {
          setTyped(true)
          // Changed: what the sending refused is about a value that is no more.
          onChange({ ...next, violations: [] })
        }}
      />
      {problem ? (
        <p id={`${id}-problem`} role="alert" className="text-destructive text-xs" data-slot="vault-problem">
          {problem}
        </p>
      ) : null}
    </div>
  )
}

const invalid = (formInput: FormInputInterface) =>
  formInput.violations?.length ? { "aria-invalid": true, "aria-errormessage": `${formInput.id}-problem` } : {}

const KindController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const t = useT()
  const { updateData } = useFormContext()
  return (
    <select
      id={formInput.id}
      className={SELECT}
      value={String(formInput.value ?? "token")}
      onChange={(event) => {
        onChange({ ...formInput, value: event.target.value })
        // Another kind, other fields: what was typed in the old ones is gone with them.
        updateData({ value: 0, user: 0, password: 0 })
      }}
      data-slot="vault-kind"
    >
      {KINDS.map((one) => (
        <option key={one.kind} value={one.kind}>
          {t(one.label)}
        </option>
      ))}
    </select>
  )
}

const NameController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const { form } = useFormContext()
  const data = form.data as Draft
  const name = normalized(String(formInput.value ?? ""))
  return (
    <>
      <Input
        id={formInput.id}
        value={String(formInput.value ?? "")}
        onChange={(event) => onChange({ ...formInput, value: event.target.value })}
        placeholder="UMAMI"
        className="font-mono"
        autoComplete="off"
        spellCheck={false}
        data-slot="vault-name"
        {...invalid(formInput)}
      />
      {name && !formInput.violations?.length ? (
        <span className="text-muted-foreground font-mono text-xs break-words" data-slot="vault-variables">
          {given(name, data.kind, Boolean(data.url.trim())).join(", ")}
        </span>
      ) : null}
    </>
  )
}

/* Uncontrolled: the value stays in the element, and the form is told its length alone. */
const SecretController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const secrets = React.use(SecretsContext)
  const { form } = useFormContext()
  const kind = (form.data as Draft).kind
  const field = String(formInput.name)
  const hold = (element: HTMLInputElement | HTMLTextAreaElement | null) => {
    if (element) secrets.set(field, element)
    else secrets.delete(field)
  }
  const told = (event: React.FormEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    onChange({ ...formInput, value: lengthOf(event.currentTarget.value, kind) })
  const shared = { id: formInput.id, name: `vault-${field}`, autoComplete: "off", onInput: told, "data-slot": `vault-${field}`, ...invalid(formInput) }
  if (field === "value" && kind === "note")
    return <Textarea ref={hold} rows={5} spellCheck={false} className="font-mono text-xs" {...shared} />
  return <Input ref={hold} type="password" {...shared} />
}

const UrlController: InputControllerComponentInterface = ({ formInput, onChange }) => {
  const { form } = useFormContext()
  return (
    <Input
      id={formInput.id}
      value={String(formInput.value ?? "")}
      onChange={(event) => onChange({ ...formInput, value: event.target.value })}
      placeholder={(form.data as Draft).kind === "login" ? "https://umami.example.com/login" : "https://openrouter.ai/settings/keys"}
      autoComplete="off"
      spellCheck={false}
      inputMode="url"
      data-slot="vault-url"
      {...invalid(formInput)}
    />
  )
}

/** The vault as last read: the projects to tick, and the names already given. */
const VaultContext = React.createContext<Vault | null>(null)

const ProjectsController: InputControllerComponentInterface = ({ formInput, onChange }) => (
  <Projects
    known={React.use(VaultContext)?.projects ?? []}
    chosen={(formInput.value as string[] | undefined) ?? []}
    onChange={(projects) => onChange({ ...formInput, value: projects })}
  />
)

const TextController: InputControllerComponentInterface = ({ formInput, onChange }) => (
  <Input
    id={formInput.id}
    type={formInput.type === "date" ? "date" : "text"}
    value={String(formInput.value ?? "")}
    onChange={(event) => onChange({ ...formInput, value: event.target.value })}
    {...invalid(formInput)}
  />
)

/* The fields, laid out as the card wants them rather than in a column. */
function NewFields() {
  const { form } = useFormContext()
  const inputs = new Map(getFormInputsFromForm(form).map((formInput) => [String(formInput.name), formInput]))
  const field = (name: string) => {
    const formInput = inputs.get(name)
    return formInput ? <InputControllerProvider formInput={formInput} /> : null
  }
  const login = (form.data as Draft).kind === "login"
  return (
    <React.Fragment key={React.use(RoundContext)}>
      <div className="grid gap-3 sm:grid-cols-2">
        {field("kind")}
        {field("name")}
      </div>
      {login ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {field("user")}
          {field("password")}
        </div>
      ) : (
        field("value")
      )}
      {field("url")}
      {field("projects")}
      <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
        {field("description")}
        {field("expires")}
      </div>
    </React.Fragment>
  )
}

/** What the server refused with that belongs to no field, and what kept the entry from being sent. */
const ProblemContext = React.createContext("")

function NewProblems() {
  const { form } = useFormContext()
  const problem = React.use(ProblemContext)
  const said = [...(form.errors ?? []), ...(problem ? [problem] : [])]
  if (!said.length) return null
  return (
    <Alert variant="destructive">
      <AlertDescription>{said.join(" ")}</AlertDescription>
    </Alert>
  )
}

function NewSubmit() {
  const t = useT()
  const { form, isLoading } = useFormContext()
  return (
    <div>
      <Button type="submit" size="sm" disabled={isLoading.value || !String(form.data.name ?? "").trim()} data-slot="vault-create">
        <Plus />
        {t("Keep in the vault")}
      </Button>
    </div>
  )
}

function NewForm({ children }: FormDecoratorPropsInterface) {
  const { onSubmit } = useFormContext()
  return (
    <form
      className="flex flex-col gap-3"
      noValidate
      autoComplete="off"
      onSubmit={(event) => {
        event.preventDefault()
        void onSubmit()
      }}
    >
      {children}
    </form>
  )
}

/** The declaration, read once: what changes — the entries, the projects — is read through `known`. */
function newForm(known: React.RefObject<Vault>): FormInterface<Draft> {
  const secret = (name: "value" | "user" | "password", label: string): FormInputInterface<number, Draft> => ({
    label,
    controller: SecretController,
    hidden: (data) => (data.kind === "login") === (name === "value"),
    validator: (length) => {
      if (name === "user") {
        if (!length) throw new Error(t(NO_USER))
      } else if ((length ?? 0) < SHORTEST)
        throw new Error(t(name === "password" ? SHORT_PASSWORD : SHORT_VALUE, { count: String(SHORTEST) }))
    },
  })
  return {
    showSuccess: false,
    components: { formDecorator: NewForm, formInputs: NewFields, formGroupProvider: Field, formErrors: NewProblems, formSubmitAction: NewSubmit },
    inputs: {
      kind: { label: "Kind", controller: KindController },
      name: {
        label: "Variable name",
        controller: NameController,
        validator: (typed, data) => {
          const problem = nameProblem(String(typed ?? ""), data?.kind ?? "token", known.current)
          if (problem) throw new Error(problem)
        },
      },
      value: secret("value", "Value"),
      user: secret("user", "User"),
      password: secret("password", "Password"),
      url: {
        label: "Site (optional)",
        controller: UrlController,
        validator: (typed) => {
          if (siteAddress(String(typed ?? "")) === null) throw new Error(t(NO_SITE))
        },
      },
      projects: { label: "Projects allowed", controller: ProjectsController },
      description: { label: "Description", controller: TextController },
      expires: { label: "Expires on (optional)", type: "date", controller: TextController },
    },
  }
}

export function New({ vault, guard, onMade }: { vault: Vault; guard: Guard; onMade: () => void }) {
  const t = useT()
  const [problem, setProblem] = React.useState("")
  const [round, setRound] = React.useState(0)
  const known = React.useRef(vault)
  known.current = vault
  const [secrets] = React.useState<Secrets>(() => new Map())
  const [form] = React.useState(() => newForm(known))
  const latest = React.useRef<FormContextOutput<Draft> | null>(null)

  const read = (field: string) => secrets.get(field)?.value ?? ""
  const empty = () => {
    for (const element of secrets.values()) element.value = ""
  }

  const context = useForm<Draft>({
    form,
    data: { kind: "token", ...EMPTY },
    onSubmit: async (draft) => {
      setProblem("")
      const values = draft.kind === "login" ? { user: read("user"), password: read("password") } : { value: read("value") }
      const { kind, name, projects, description, expires, url } = draft
      let made: VaultEntry
      try {
        made = await guard(() => api.createVaultEntry({ name, kind, projects, description, expires, url, ...values }))
      } catch (error) {
        // Given up at the password: everything stays where it was typed.
        if (error instanceof StillLocked) return
        // Refused field by field: each sentence under its field, and the rest kept to fix that one.
        if (error instanceof ApiError && error.data.violations?.length)
          throw { violations: error.data.violations.map((one) => ({ ...one, message: said(one.message) })) }
        setProblem(said(why(error)))
        return
      }
      empty()
      const seen = made.url_variable ? [...made.variables, made.url_variable] : made.variables
      toast.success(t("{{name}} is kept: its sessions see {{variables}}", { name: made.name, variables: seen.join(", ") }))
      latest.current?.updateData({ kind, ...EMPTY }, false)
      setRound((done) => done + 1)
      onMade()
    },
  })
  latest.current = context

  return (
    <Card data-card="vault-new" className="gap-0 py-0">
      <CardHeader className="px-5 pt-5 pb-3 sm:px-6">
        <CardTitle className="text-base">{t("New entry")}</CardTitle>
      </CardHeader>
      <CardContent className="px-5 pb-5 sm:px-6">
        <VaultContext value={vault}>
          <SecretsContext value={secrets}>
            <ProblemContext value={problem}>
              <RoundContext value={round}>
                <FormElement {...context} />
              </RoundContext>
            </ProblemContext>
          </SecretsContext>
        </VaultContext>
      </CardContent>
    </Card>
  )
}

/** What an entry's site is for, by kind: a login's is the only place Ponos's browser types it. */
function siteHelp(kind: string) {
  return kind === "login"
    ? "Ponos's browser signs in here with it, and types it on no other site."
    : "Where it is managed or renewed — a dashboard, a settings page."
}

/** An entry's site: where a login signs in, where a key is managed. Given to sessions as <NAME>_URL. */
function SiteField({ kind, name, url, onChange }: { kind: string; name: string; url: string; onChange: (url: string) => void }) {
  const t = useT()
  const wrong = siteAddress(url) === null
  const variable = `${name.trim() || "<NAME>"}_URL`
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-medium">{t(kind === "login" ? "Site (sign-in page)" : "Site (optional)")}</span>
      <Input
        value={url}
        onChange={(event) => onChange(event.target.value)}
        placeholder={kind === "login" ? "https://dokploy.example.com/login" : "https://openrouter.ai/settings/keys"}
        autoComplete="off"
        spellCheck={false}
        inputMode="url"
        aria-invalid={wrong || undefined}
        data-slot="vault-url"
      />
      <span className={wrong ? "text-destructive text-xs" : "text-muted-foreground text-xs"} data-slot="vault-url-help">
        {wrong ? t(NO_SITE) : `${t(siteHelp(kind))} ${t("Its sessions see it as {{variable}}.", { variable })}`}
      </span>
    </label>
  )
}

function Moments({ entry }: { entry: VaultEntry }) {
  const t = useT()
  const [moments, setMoments] = React.useState<VaultMoment[] | null>(null)
  React.useEffect(() => {
    api.vaultHistory(entry.id).then(
      (read) => setMoments(read.entries),
      () => setMoments([])
    )
  }, [entry.id, entry.updated, entry.last_used])
  if (!moments) return null
  return (
    <ul className="text-muted-foreground mt-2 flex flex-col gap-0.5 text-xs" data-slot="vault-history">
      {moments.map((moment, index) => (
        <li key={index}>
          {when(moment.at)} — {t(ACTIONS[moment.action])}
          {moment.action === "url" ? ` · ${moment.detail || t("removed")}` : ""}
          {moment.ticket ? ` · ${t("ticket")} ${moment.ticket}` : ""}
          {moment.project ? ` · ${moment.project}` : ""}
          {moment.by ? ` · ${moment.by}` : ""}
        </li>
      ))}
    </ul>
  )
}

function Row({ entry, vault, guard, onChanged }: { entry: VaultEntry; vault: Vault; guard: Guard; onChanged: () => void }) {
  const t = useT()
  const [projects, setProjects] = React.useState<string[]>(entry.projects)
  const [url, setUrl] = React.useState(entry.url)
  const [history, setHistory] = React.useState(false)
  const value = React.useRef<HTMLInputElement | HTMLTextAreaElement>(null)
  const user = React.useRef<HTMLInputElement>(null)
  const password = React.useRef<HTMLInputElement>(null)
  const known = [...new Set([...vault.projects, ...entry.projects])].sort((a, b) => a.localeCompare(b))

  // Given up at the password: the window stays open, with what was typed in it.
  const failed = (what: string, error: unknown) => {
    if (!(error instanceof StillLocked)) toast.error(t(what), { description: said(why(error)) })
    return false
  }
  const replace = async () => {
    const given = values(entry.kind, value, user, password)
    try {
      await guard(() => api.changeVaultEntry(entry.id, given))
    } catch (error) {
      if (!(error instanceof StillLocked)) emptied(value, user, password)
      return failed("The value could not be replaced", error)
    }
    emptied(value, user, password)
    toast.success(t("{{name}}: value replaced", { name: entry.name }))
    onChanged()
  }
  const regrant = async () => {
    try {
      await guard(() => api.changeVaultEntry(entry.id, { projects }))
    } catch (error) {
      return failed("The projects could not be changed", error)
    }
    onChanged()
  }
  const resite = async () => {
    if (siteAddress(url) === null) {
      toast.error(t("The site could not be changed"), { description: t(NO_SITE) })
      return false
    }
    try {
      await guard(() => api.changeVaultEntry(entry.id, { url }))
    } catch (error) {
      return failed("The site could not be changed", error)
    }
    onChanged()
  }
  const revoke = async () => {
    try {
      await guard(() => api.revokeVaultEntry(entry.id))
    } catch (error) {
      return failed("The entry could not be revoked", error)
    }
    toast.success(t("{{name}} is revoked", { name: entry.name }))
    onChanged()
  }

  return (
    <li className="flex flex-col gap-1 py-3" data-vault={entry.name}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {/* A basis of its own: on a phone the buttons go under it, rather than squeezing it to a word a line. */}
        <div className="min-w-0 flex-1 basis-64">
          <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
            <code className="font-mono">{entry.name}</code>
            <Badge variant="outline">{t(labelOf(entry.kind))}</Badge>
            {entry.print ? <span className="text-muted-foreground font-mono text-xs" title={t("The end of the value")}>{entry.print}</span> : null}
          </p>
          <p className="text-muted-foreground text-xs">
            {entry.projects.length ? entry.projects.join(", ") : <span className="text-destructive">{t("no project: given to no session")}</span>}
            {entry.kind === "login" ? ` · ${entry.variables.join(", ")}` : ""}
            {entry.url ? (
              <>
                {" · "}
                <SiteLink url={entry.url} />
              </>
            ) : null}
            {entry.description ? ` · ${entry.description}` : ""}
          </p>
          <p className="text-muted-foreground text-xs">
            {t("created {{created}}, changed {{updated}}", { created: when(entry.created), updated: when(entry.updated) })}
            {" · "}
            {entry.last_used ? t("last given {{when}}", { when: when(entry.last_used) }) : t("never given yet")}
            {entry.expires ? ` · ${t("expires {{when}}", { when: entry.expires })}` : ""}
          </p>
        </div>
        <ConfirmDialog
          title={t("Replace the value of {{name}}", { name: entry.name })}
          description={t("The old value is gone for good: it is not shown, and cannot be read back.")}
          confirm={t("Replace")}
          onConfirm={replace}
          multiline={entry.kind === "note"}
          trigger={
            <Button variant="ghost" size="sm" data-slot="vault-replace">
              <RefreshCw />
              {t("Replace")}
            </Button>
          }
        >
          <div className="flex flex-col gap-3">
            <ValueFields kind={entry.kind} value={value} user={user} password={password} />
          </div>
        </ConfirmDialog>
        <ConfirmDialog
          title={t("Projects allowed for {{name}}", { name: entry.name })}
          description={t("Only the sessions of these projects are given it.")}
          confirm={t("Save")}
          onConfirm={regrant}
          onOpenChange={(open) => open && setProjects(entry.projects)}
          trigger={
            <Button variant="ghost" size="sm" data-slot="vault-regrant">
              <Users />
              {t("Projects")}
            </Button>
          }
        >
          <Projects known={known} chosen={projects} onChange={setProjects} />
        </ConfirmDialog>
        <ConfirmDialog
          title={t("Site of {{name}}", { name: entry.name })}
          description={t(siteHelp(entry.kind))}
          confirm={t("Save")}
          onConfirm={resite}
          onOpenChange={(open) => open && setUrl(entry.url)}
          trigger={
            <Button variant="ghost" size="sm" data-slot="vault-site">
              <Globe />
              {t("Site")}
            </Button>
          }
        >
          <SiteField kind={entry.kind} name={entry.name} url={url} onChange={setUrl} />
        </ConfirmDialog>
        <Button variant="ghost" size="icon-sm" onClick={() => setHistory((was) => !was)} aria-label={t("History of {{name}}", { name: entry.name })} aria-pressed={history}>
          <History />
        </Button>
        <ConfirmDialog
          destructive
          title={t("Revoke {{name}}?", { name: entry.name })}
          description={t("Deleted for good: no session is given it any more, and it cannot be brought back. What happened to it stays in the journal.")}
          confirm={t("Revoke")}
          onConfirm={revoke}
          trigger={
            <Button variant="ghost" size="icon-sm" aria-label={t("Revoke {{name}}", { name: entry.name })} data-slot="vault-revoke">
              <Trash2 />
            </Button>
          }
        />
      </div>
      {history ? <Moments entry={entry} /> : null}
    </li>
  )
}

function Key({ vault }: { vault: Vault }) {
  const t = useT()
  const { source, where } = vault.key
  return (
    <Card data-card="vault-key" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
        <CardTitle className="flex items-center gap-2 text-base">
          <KeyRound className="size-4" />
          {t("Where the key is")}
        </CardTitle>
        <CardDescription className="text-[13px]">
          {t("Each entry is sealed on its own with AES-256-GCM, under a key kept apart from vault.db. A copy of vault.db alone opens nothing; somebody with the Unix account that runs Ponos can open everything.")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 px-5 pb-5 text-sm sm:px-6">
        {source ? (
          <p>
            <code className="bg-muted rounded px-1.5 py-0.5 font-mono text-xs break-all" data-slot="vault-key-where">
              {where}
            </code>
          </p>
        ) : (
          <p className="text-muted-foreground">{t("No key yet: one is drawn with the first entry — in the system keyring when secret-tool is there.")}</p>
        )}
        {source === "file" ? (
          <Alert data-slot="vault-key-file">
            <AlertDescription>
              {t("Neither secret-tool nor PONOS_VAULT_KEY: the key is a file. A backup that holds it with vault.db holds every key — keep it out of the state's backups, or give the key in PONOS_VAULT_KEY.")}
            </AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  )
}

function VaultTab() {
  const t = useT()
  const [vault, setVault] = React.useState<Vault | null>(null)
  const [problem, setProblem] = React.useState("")
  // When the vault was last used from this page, for the line that says it locks itself.
  const [used, setUsed] = React.useState(0)
  const [asleep, setAsleep] = React.useState(false)
  const [asking, setAsking] = React.useState(false)
  const answered = React.useRef<((unlocked: boolean) => void) | null>(null)
  const read = React.useCallback(() => {
    api.vault().then(
      (fresh) => {
        setVault(fresh)
        setProblem("")
        if (fresh.proven) setUsed(Date.now())
      },
      (error: unknown) => setProblem(why(error))
    )
  }, [])
  React.useEffect(() => read(), [read])
  const relocks = (vault?.relocks_after ?? 15 * 60) * 1000
  React.useEffect(() => {
    if (!used) return
    setAsleep(false)
    const timer = window.setTimeout(() => setAsleep(true), relocks)
    return () => window.clearTimeout(timer)
  }, [used, relocks])

  const answer = React.useCallback((unlocked: boolean) => {
    const waiting = answered.current
    answered.current = null
    setAsking(false)
    waiting?.(unlocked)
  }, [])
  const guard = React.useCallback<Guard>(
    async (send) => {
      for (;;) {
        try {
          const done = await send()
          setUsed(Date.now())
          return done
        } catch (error) {
          if (!locked(error)) throw error
        }
        // Locked meanwhile: the password over the page, and the same write again.
        const unlocked = await new Promise<boolean>((resolve) => {
          answered.current?.(false)
          answered.current = resolve
          setAsking(true)
        })
        if (!unlocked) throw new StillLocked()
      }
    },
    []
  )
  const lock = async () => {
    try {
      await api.lockVault()
    } catch (error) {
      toast.error(t("The vault could not be locked"), { description: why(error) })
      return
    }
    setUsed(0)
    setVault((was) => (was ? { ...was, proven: false } : was))
  }
  const opened = () => {
    setVault((was) => (was ? { ...was, proven: true } : was))
    read()
  }

  return (
    <div className="flex max-w-[760px] min-w-0 flex-col gap-4" data-page="vault">
      {problem ? (
        <Alert variant="destructive">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      ) : null}
      {vault && !vault.proven ? (
        <Locked onUnlocked={opened} />
      ) : vault ? (
        <>
          <State minutes={Math.round(relocks / 60000)} asleep={asleep} onLock={() => void lock()} />
          <Key vault={vault} />
          <New vault={vault} guard={guard} onMade={read} />
          <Card data-card="vault-list" className="gap-0 py-0">
            <CardHeader className="gap-1 px-5 pt-5 pb-1 sm:px-6">
              <CardTitle className="text-base">{t("In the vault")}</CardTitle>
              <CardDescription className="text-[13px]">
                {t("A value is never shown again: replace it, or revoke it.")}
              </CardDescription>
            </CardHeader>
            <CardContent className="px-5 pb-3 sm:px-6">
              {vault.entries.length ? (
                <ul className="divide-y" data-testid="vault-list">
                  {vault.entries.map((entry) => (
                    <Row key={entry.id} entry={entry} vault={vault} guard={guard} onChanged={read} />
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground py-3 text-sm">{t("Nothing in the vault yet.")}</p>
              )}
            </CardContent>
          </Card>
          <Relock open={asking} answer={answer} />
        </>
      ) : problem ? null : (
        <p className="text-muted-foreground text-sm">{t("Reading the vault…")}</p>
      )}
    </div>
  )
}

export function VaultPage() {
  return (
    <Worded words={settingsFrench}>
      <VaultTab />
    </Worded>
  )
}
