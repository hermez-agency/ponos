import * as React from "react"
import { CopyIcon, Trash2 } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/api"
import { copy } from "@/lib/copy"
import { Worded, useT } from "@/lib/i18n"
import { settingsFrench } from "@/lib/settings-store"
import type { Trigger, Triggers } from "@/lib/types"

/* The settings' Triggers page: the keys a tool calls to open a ticket.
 *
 * A key is said once, when it is made — the server keeps its digest and
 * nothing else (`triggers.py`) — so the address it forms is shown in the card
 * that follows the creation and in no list after it.
 */

const SELECT =
  "border-input bg-background h-9 w-full rounded-md border px-2 text-sm shadow-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"

type Draft = {
  name: string
  preset: string
  project: string
  status: string
  priority: string
  per_hour: string
  title: string
  brief: string
}

const EMPTY: Draft = {
  name: "",
  preset: "sentry",
  project: "",
  status: "draft",
  priority: "50",
  per_hour: "10",
  title: "",
  brief: "",
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-medium">{label}</span>
      {children}
    </label>
  )
}

function Created({ address, name, onDone }: { address: string; name: string; onDone: () => void }) {
  const t = useT()
  return (
    <Alert data-testid="trigger-created">
      <AlertDescription className="flex flex-col gap-2">
        <span className="font-medium">{t("“{{name}}” is ready. Paste this address into the tool — it is shown once.", { name })}</span>
        <div className="bg-muted flex items-center gap-2 rounded-md border py-1 pr-1 pl-3">
          <code className="min-w-0 flex-1 overflow-x-auto py-1.5 font-mono text-xs" data-testid="trigger-address">
            {address}
          </code>
          <Button type="button" variant="ghost" size="icon-sm" onClick={() => void copy(address, t("the address"))} aria-label={t("Copy the address")}>
            <CopyIcon />
          </Button>
        </div>
        <span className="text-muted-foreground">
          {t("From outside this machine, replace the start of the address by the one the tool can reach: the public address, or the Tailscale Funnel one.")}
        </span>
        <div>
          <Button size="xs" variant="outline" onClick={onDone}>
            {t("Done")}
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  )
}

function Form({ read, onCreated }: { read: Triggers; onCreated: (key: string, name: string) => void }) {
  const t = useT()
  const [draft, setDraft] = React.useState<Draft>({ ...EMPTY, project: read.projects[0]?.id ?? "" })
  const [problem, setProblem] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const preset = read.presets.find((item) => item.key === draft.preset)
  const set = (patch: Partial<Draft>) => setDraft((was) => ({ ...was, ...patch }))

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setProblem("")
    try {
      const made = await api.createTrigger({
        name: draft.name,
        preset: draft.preset,
        project: draft.project,
        status: draft.status,
        priority: draft.priority,
        per_hour: draft.per_hour,
        title: draft.title,
        brief: draft.brief,
      })
      onCreated(made.key, made.hook.name)
      setDraft({ ...EMPTY, project: draft.project })
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card data-card="trigger-new" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
        <CardTitle className="text-base">{t("New trigger")}</CardTitle>
        <CardDescription className="text-[13px]">
          {t("Templates take their values from the JSON received: {{title}}, {{url}}. {{either}} takes the first one that is filled in.", {
            title: "{{event.title}}",
            url: "{{event.url}}",
            either: "{{event.a | event.b}}",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="px-5 pb-5 sm:px-6">
        <form className="flex flex-col gap-3" onSubmit={(event) => void submit(event)}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("Name")}>
              <Input value={draft.name} onChange={(event) => set({ name: event.target.value })} placeholder="Sentry — shop" />
            </Field>
            <Field label={t("Tool")}>
              <select className={SELECT} value={draft.preset} onChange={(event) => set({ preset: event.target.value, title: "", brief: "" })}>
                {read.presets.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("Project")}>
              <select className={SELECT} value={draft.project} onChange={(event) => set({ project: event.target.value })}>
                {read.projects.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("Arrives as")}>
              <select className={SELECT} value={draft.status} onChange={(event) => set({ status: event.target.value })}>
                <option value="draft">{t("Draft")}</option>
                <option value="ready">{t("Ready")}</option>
              </select>
            </Field>
            <Field label={t("Priority (0–100)")}>
              <Input inputMode="numeric" value={draft.priority} onChange={(event) => set({ priority: event.target.value })} />
            </Field>
            <Field label={t("Tickets an hour, at most")}>
              <Input inputMode="numeric" value={draft.per_hour} onChange={(event) => set({ per_hour: event.target.value })} />
            </Field>
          </div>
          {draft.status === "ready" ? (
            <Alert>
              <AlertDescription>
                {t("A Ready ticket starts a session at once, on text anybody could have sent to the tool. Keep Draft unless you trust the source.")}
              </AlertDescription>
            </Alert>
          ) : null}
          <Field label={t("Title template")}>
            <Input value={draft.title} onChange={(event) => set({ title: event.target.value })} placeholder={preset?.title} />
          </Field>
          <Field label={t("Brief template")}>
            <Textarea rows={6} value={draft.brief} onChange={(event) => set({ brief: event.target.value })} placeholder={preset?.brief} />
          </Field>
          {problem ? (
            <Alert variant="destructive">
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          ) : null}
          <div>
            <Button type="submit" size="sm" disabled={busy || !draft.name.trim() || !draft.project}>
              {t("Create the trigger")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function Row({ hook, onRevoke }: { hook: Trigger; onRevoke: () => void }) {
  const t = useT()
  return (
    <li data-trigger={hook.id} data-revoked={hook.revoked} className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0">
      <span className="min-w-0">
        <span className="block truncate font-medium">{hook.name}</span>
        <span className="text-muted-foreground block truncate text-xs">
          {hook.project_name} · {hook.status === "ready" ? t("Ready") : t("Draft")} ·{" "}
          {t("{{count}} tickets", { count: String(hook.count) })}
          {hook.last_at ? ` · ${hook.last_at.replace("T", " ").slice(0, 16)}` : ""}
        </span>
      </span>
      {hook.revoked ? (
        <Badge variant="outline">{t("Revoked")}</Badge>
      ) : (
        <Button size="xs" variant="outline" onClick={onRevoke} aria-label={`${t("Revoke")} ${hook.name}`}>
          <Trash2 />
          {t("Revoke")}
        </Button>
      )}
    </li>
  )
}

export const TriggersPage = () => (
  <Worded words={settingsFrench}>
    <TriggersTab />
  </Worded>
)

function TriggersTab() {
  const t = useT()
  const [read, setRead] = React.useState<Triggers | null>(null)
  const [failed, setFailed] = React.useState("")
  const [created, setCreated] = React.useState<{ key: string; name: string } | null>(null)

  const load = React.useCallback(() => {
    api.triggers().then(setRead, (error) => setFailed(error instanceof Error ? error.message : String(error)))
  }, [])
  React.useEffect(() => {
    load()
  }, [load])

  const revoke = (hook: Trigger) => {
    api.revokeTrigger(hook.id).then(load, (error) => setFailed(error instanceof Error ? error.message : String(error)))
  }

  return (
    <div className="flex max-w-[720px] min-w-0 flex-col gap-5" data-page="triggers">
      <Card data-card="trigger-what" className="gap-0 py-0">
        <CardHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
          <CardTitle className="text-base">{t("Incoming triggers")}</CardTitle>
        </CardHeader>
        <CardContent className="px-5 pb-5 text-sm leading-relaxed sm:px-6">
          {t("A tool — Sentry, GitHub Actions, PagerDuty, anything that posts JSON — calls an address, and a ticket is born. The same event twice makes one ticket; a key makes a limited number an hour; a revoked key answers 404.")}
        </CardContent>
      </Card>
      {failed ? (
        <Alert variant="destructive">
          <AlertDescription>{failed}</AlertDescription>
        </Alert>
      ) : null}
      {created ? (
        <Created
          name={created.name}
          address={`${window.location.origin}/api/hooks/${created.key}`}
          onDone={() => setCreated(null)}
        />
      ) : null}
      {read ? (
        <>
          <Form
            read={read}
            onCreated={(key, name) => {
              setCreated({ key, name })
              load()
            }}
          />
          <Card data-card="trigger-list" className="gap-0 py-0">
            <CardHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
              <CardTitle className="text-base">{t("Keys")}</CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-5 text-sm sm:px-6">
              {read.hooks.length ? (
                <ul className="divide-y" data-testid="trigger-list">
                  {read.hooks.map((hook) => (
                    <Row key={hook.id} hook={hook} onRevoke={() => revoke(hook)} />
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">{t("No trigger yet.")}</p>
              )}
            </CardContent>
          </Card>
        </>
      ) : failed ? null : (
        <p className="text-muted-foreground text-sm">{t("Reading the triggers…")}</p>
      )}
    </div>
  )
}
