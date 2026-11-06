import * as React from "react"
import { Plus, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { useT } from "@/lib/i18n"
import type { ProjectSettings } from "@/lib/types"

import { Rich } from "./text"

/* What this project's diagnostics may reach, and where their fix tickets land.
 *
 * A diagnostic reads: its repository and Ponos's own state always, and on top of
 * them what is declared here — the admin MCP servers worth asking, the machines
 * it may open a shell on with an entry of the vault, the production addresses it
 * may `curl`. Nothing here is a write access; the session is told so.
 *
 * Typed and saved with its button, as the setup and the preview are; the switch
 * of the fix tickets saves as it is flipped, with what is saved of the rest. */

type Diagnostic = ProjectSettings["diagnostic"]
type Host = Diagnostic["hosts"][number]
export type DiagnosticSaved = Pick<Diagnostic, "mcp" | "hosts" | "urls" | "ready">

const listed = (text: string) =>
  text
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)

const blank: Host = { address: "", entry: "", label: "" }

export function DiagnosticCard({
  diagnostic,
  saving,
  onSave,
}: {
  diagnostic: Diagnostic
  saving: boolean
  onSave: (diagnostic: DiagnosticSaved) => Promise<void>
}) {
  const t = useT()
  const [mcp, setMcp] = React.useState(diagnostic.mcp.join(", "))
  const [urls, setUrls] = React.useState(diagnostic.urls.join(", "))
  const [hosts, setHosts] = React.useState<Host[]>(diagnostic.hosts)
  const kept = hosts.filter((host) => host.address.trim())
  const typed: DiagnosticSaved = {
    mcp: listed(mcp),
    urls: listed(urls),
    hosts: kept.map((host) => ({
      address: host.address.trim(),
      entry: host.entry.trim(),
      label: host.label.trim(),
    })),
    ready: diagnostic.ready,
  }
  const saved: DiagnosticSaved = {
    mcp: diagnostic.mcp,
    urls: diagnostic.urls,
    hosts: diagnostic.hosts,
    ready: diagnostic.ready,
  }
  const changed = JSON.stringify(typed) !== JSON.stringify(saved)
  const edit = (index: number, change: Partial<Host>) =>
    setHosts((now) => now.map((host, at) => (at === index ? { ...host, ...change } : host)))
  return (
    <Card data-card="project-diagnostic" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-2 sm:px-6">
        <CardTitle className="text-base">{t("Diagnostic")}</CardTitle>
        <CardDescription className="text-[13px] leading-relaxed">
          {t(
            "A diagnostic ticket investigates « X does not work » without changing anything, then writes the tickets that fix it. It always reads the repository and Ponos; declare here what else it may read."
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="px-5 pb-4 sm:px-6">
        <div className="flex items-start justify-between gap-4 py-3" data-field="project-diagnostic-ready">
          <div className="min-w-0">
            <Label htmlFor="project-diagnostic-ready" className="leading-snug font-semibold">
              {t("Fix tickets straight to Ready")}
            </Label>
            <p className="text-muted-foreground mt-1 text-[13px] leading-snug">
              {diagnostic.ready
                ? t("They start as soon as the diagnostic is closed, each after the ones it depends on.")
                : t("Off: they are created as drafts, for you to read before they run.")}
            </p>
          </div>
          <div className="shrink-0 pt-0.5">
            <Switch
              id="project-diagnostic-ready"
              checked={diagnostic.ready}
              disabled={saving}
              onCheckedChange={(ready) => void onSave({ ...saved, ready })}
            />
          </div>
        </div>
        <form
          className="space-y-3 border-t py-3"
          data-field="project-diagnostic-access"
          onSubmit={(event) => {
            event.preventDefault()
            if (changed) void onSave(typed)
          }}
        >
          <div>
            <Label htmlFor="project-diagnostic-mcp" className="leading-snug font-semibold">
              {t("Admin MCP servers")}
            </Label>
            <p className="text-muted-foreground mt-1 text-[13px] leading-snug">
              <Rich text={t("Their names in `claude mcp list`, separated by commas. Only their tools that read are called.")} />
            </p>
            <Input
              id="project-diagnostic-mcp"
              className="mt-1.5 font-mono text-[13px]"
              autoComplete="off"
              spellCheck={false}
              placeholder="lead-finder"
              value={mcp}
              onChange={(event) => setMcp(event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="project-diagnostic-urls" className="leading-snug font-semibold">
              {t("Production addresses")}
            </Label>
            <p className="text-muted-foreground mt-1 text-[13px] leading-snug">
              {t("Read with GET requests only, separated by commas.")}
            </p>
            <Input
              id="project-diagnostic-urls"
              className="mt-1.5 font-mono text-[13px]"
              autoComplete="off"
              spellCheck={false}
              placeholder="https://example.com"
              value={urls}
              onChange={(event) => setUrls(event.target.value)}
            />
          </div>
          <div>
            <p className="text-sm leading-snug font-semibold">{t("SSH hosts")}</p>
            <p className="text-muted-foreground mt-1 text-[13px] leading-snug">
              {t(
                "Read-only commands only. The vault entry holds what opens the machine; empty, the keys this machine already has."
              )}
            </p>
            <datalist id="project-diagnostic-entries">
              {diagnostic.entries.map((entry) => (
                <option key={entry} value={entry} />
              ))}
            </datalist>
            <div className="mt-2 flex flex-col gap-2" data-slot="diagnostic-hosts">
              {hosts.map((host, index) => (
                <div key={index} className="flex flex-wrap gap-2 sm:flex-nowrap" data-slot="diagnostic-host">
                  <Input
                    aria-label={t("SSH address")}
                    className="font-mono text-[13px] sm:flex-[3]"
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="deck@steamdeck.local"
                    value={host.address}
                    onChange={(event) => edit(index, { address: event.target.value })}
                  />
                  <Input
                    aria-label={t("Vault entry")}
                    className="font-mono text-[13px] sm:flex-[2]"
                    autoComplete="off"
                    spellCheck={false}
                    list="project-diagnostic-entries"
                    placeholder="DECK_SSH_KEY"
                    value={host.entry}
                    onChange={(event) => edit(index, { entry: event.target.value })}
                  />
                  <Input
                    aria-label={t("What it is")}
                    className="text-[13px] sm:flex-[2]"
                    autoComplete="off"
                    placeholder={t("the console")}
                    value={host.label}
                    onChange={(event) => edit(index, { label: event.target.value })}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={t("Remove this host")}
                    onClick={() => setHosts((now) => now.filter((_, at) => at !== index))}
                  >
                    <X />
                  </Button>
                </div>
              ))}
              <div>
                <Button type="button" variant="outline" size="sm" onClick={() => setHosts((now) => [...now, blank])}>
                  <Plus />
                  {t("Add a host")}
                </Button>
              </div>
            </div>
          </div>
          <div>
            <Button type="submit" variant="outline" disabled={!changed || saving}>
              {t("Save")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}
