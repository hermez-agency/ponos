import * as React from "react"
import { ExternalLink, Globe, History, KeyRound, Lock, LockOpen, Plus, RefreshCw, Trash2, Users } from "lucide-react"
import { toast } from "sonner"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { ApiError, api, why } from "@/lib/api"
import { Worded, useT } from "@/lib/i18n"
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

const KINDS: { kind: VaultEntry["kind"]; label: string; help: string }[] = [
  { kind: "token", label: "API key / token", help: "One value, given as the variable itself." },
  { kind: "login", label: "Login + password", help: "Given as <NAME>_USER and <NAME>_PASSWORD." },
  { kind: "note", label: "Secret note", help: "Several lines — a certificate, say — given as the variable itself." },
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

function New({ vault, guard, onMade }: { vault: Vault; guard: Guard; onMade: () => void }) {
  const t = useT()
  const [kind, setKind] = React.useState<VaultEntry["kind"]>("token")
  const [name, setName] = React.useState("")
  const [projects, setProjects] = React.useState<string[]>([])
  const [description, setDescription] = React.useState("")
  const [expires, setExpires] = React.useState("")
  const [url, setUrl] = React.useState("")
  const [problem, setProblem] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const value = React.useRef<HTMLInputElement | HTMLTextAreaElement>(null)
  const user = React.useRef<HTMLInputElement>(null)
  const password = React.useRef<HTMLInputElement>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (siteAddress(url) === null) {
      setProblem(t(NO_SITE))
      return
    }
    setBusy(true)
    setProblem("")
    const given = values(kind, value, user, password)
    try {
      const made = await guard(() => api.createVaultEntry({ name, kind, projects, description, expires, url, ...given }))
      emptied(value, user, password)
      const seen = made.url_variable ? [...made.variables, made.url_variable] : made.variables
      toast.success(t("{{name}} is kept: its sessions see {{variables}}", { name: made.name, variables: seen.join(", ") }))
      setName("")
      setProjects([])
      setDescription("")
      setExpires("")
      setUrl("")
      onMade()
    } catch (error) {
      if (!(error instanceof StillLocked)) {
        emptied(value, user, password)
        setProblem(why(error))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card data-card="vault-new" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
        <CardTitle className="text-base">{t("New entry")}</CardTitle>
        <CardDescription className="text-[13px]">
          {t("Given to the sessions of the projects you tick, as an environment variable: the prompt names it, and never says its value.")}
        </CardDescription>
      </CardHeader>
      <CardContent className="px-5 pb-5 sm:px-6">
        <form className="flex flex-col gap-3" onSubmit={(event) => void submit(event)} autoComplete="off">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">{t("Kind")}</span>
              <select className={SELECT} value={kind} onChange={(event) => setKind(event.target.value as VaultEntry["kind"])} data-slot="vault-kind">
                {KINDS.map((one) => (
                  <option key={one.kind} value={one.kind}>
                    {t(one.label)}
                  </option>
                ))}
              </select>
              <span className="text-muted-foreground text-xs">{t(KINDS.find((one) => one.kind === kind)?.help ?? "")}</span>
            </label>
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">{t("Variable name")}</span>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="LEADZ_DOKPLOY_TOKEN"
                className="font-mono"
                autoComplete="off"
                spellCheck={false}
                data-slot="vault-name"
              />
            </label>
          </div>
          <ValueFields kind={kind} value={value} user={user} password={password} />
          <SiteField kind={kind} name={name} url={url} onChange={setUrl} />
          <div className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium">{t("Projects allowed")}</span>
            <Projects known={vault.projects} chosen={projects} onChange={setProjects} />
          </div>
          <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">{t("Description")}</span>
              <Input value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">{t("Expires on (optional)")}</span>
              <Input type="date" value={expires} onChange={(event) => setExpires(event.target.value)} />
            </label>
          </div>
          {problem ? (
            <Alert variant="destructive">
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          ) : null}
          <div>
            <Button type="submit" size="sm" disabled={busy || !name.trim()} data-slot="vault-create">
              <Plus />
              {t("Keep in the vault")}
            </Button>
          </div>
        </form>
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
    if (!(error instanceof StillLocked)) toast.error(t(what), { description: why(error) })
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
