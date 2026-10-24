import * as React from "react"
import { CopyIcon, PlugZap, RefreshCw } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"
import { copy } from "@/lib/copy"
import { useT } from "@/lib/i18n"
import type { McpOverview, McpServers, McpTest } from "@/lib/types"

/* The settings' MCP page: what an MCP is, how to plug Ponos's into a client,
 * and which ones the sessions start with.
 *
 * It holds no secret and asks for none. The address is pasted; a key, for a
 * client that cannot sign in by itself, is drawn on the machine with
 * `ponos mcp token` — see `web/mcp_setup.py` for why it is not a button here.
 */

type Client = "claude-code" | "claude-desktop" | "other"

/** Where the client will reach the console: from this machine, or from elsewhere. */
type Where = "local" | "public"

/** A command or a block to paste, with the button that copies it. */
function Copyable({ text, label }: { text: string; label: string }) {
  const t = useT()
  const copyIt = () => void copy(text, label)
  return (
    <div className="bg-muted flex items-start gap-2 rounded-md border py-1 pr-1 pl-3">
      <pre className="min-w-0 flex-1 overflow-x-auto py-1.5 font-mono text-xs" data-testid="mcp-snippet">
        {text}
      </pre>
      <Button type="button" variant="ghost" size="icon-sm" onClick={copyIt} aria-label={`${t("Copy")} ${label}`}>
        <CopyIcon />
      </Button>
    </div>
  )
}

/** One numbered step of the wizard. */
function Step({ number, title, children }: { number: number; title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5" data-step={number}>
      <h4 className="flex items-center gap-2 text-sm font-semibold">
        <span className="bg-muted text-muted-foreground flex size-5 items-center justify-center rounded-full text-xs">
          {number}
        </span>
        {title}
      </h4>
      <div className="flex flex-col gap-2.5 pl-7 text-sm">{children}</div>
    </section>
  )
}

/** What each way the test can fail is most likely caused by, and what to do about it. */
function Failure({ test, address }: { test: McpTest; address: string }) {
  const t = useT()
  const says: Record<string, [string, string]> = {
    "no-address": [
      t("No public address is set, so there is nothing to reach from elsewhere."),
      t("Fill in “Public address” in the General settings, then come back."),
    ],
    unreachable: [
      t("Nothing answers at {{address}}: the console is not running there, or the port is not the one it listens on.", {
        address,
      }),
      t("Start the console, check the port in the General settings — and for a public address, the proxy or the tunnel in front of it."),
    ],
    timeout: [
      t("{{address}} did not answer in time.", { address }),
      t("Check that the machine is on and the proxy or the tunnel is up, and that a firewall lets the connection through."),
    ],
    "unknown-host": [
      t("The name in {{address}} does not lead anywhere.", { address }),
      t("Check the spelling of the “Public address”, and that its DNS record points to this machine."),
    ],
    certificate: [
      t("The certificate of {{address}} is not trusted.", { address }),
      t("Renew it or let your proxy issue one: Claude refuses an address whose certificate it cannot verify."),
    ],
    "not-found": [
      t("The address answers, but not with Ponos: there is nothing at /mcp."),
      t("The address probably leads to another service. Point the proxy to this console, whole, without rewriting the path."),
    ],
    misrouted: [
      t("The console refused the name it was reached by (421)."),
      t("The proxy has to pass the name it serves on — the “Public address” — as the Host header."),
    ],
    "not-mcp": [
      t("Something answers at {{address}}, but not as an MCP server would.", { address }),
      t("Check that the address ends in /mcp and that nothing in front of the console rewrites its answers."),
    ],
    "address-mismatch": [
      t("The console reads itself under another address than the one you reached it by: {{seen}}.", {
        seen: test.seen || "?",
      }),
      t("Set the “Public address” to exactly the address you paste, with its https://, and restart the console if it was changed."),
    ],
    unexpected: [
      t("Unexpected answer from {{address}} (HTTP {{status}}).", { address, status: String(test.status) }),
      t("Look at what stands in front of the console — a proxy, a login page — and let /mcp through."),
    ],
  }
  const [cause, todo] = says[test.code] ?? says.unexpected
  return (
    <Alert variant="destructive" data-testid="mcp-test-result" data-result="failed">
      <AlertDescription className="flex flex-col gap-1">
        <span className="font-medium">{t("The connection failed.")}</span>
        <span>{t("Probable cause: {{cause}}", { cause })}</span>
        <span>{t("What to do: {{todo}}", { todo })}</span>
      </AlertDescription>
    </Alert>
  )
}

/* The verification step: it asks the console's own MCP address what a client
 * would ask first, and says in a sentence what it found. */
function TestConnection({ where, address }: { where: Where; address: string }) {
  const t = useT()
  const [busy, setBusy] = React.useState(false)
  const [result, setResult] = React.useState<McpTest | null>(null)
  const [broken, setBroken] = React.useState("")

  // Another address is another question: what was answered about the last is not an answer to it.
  React.useEffect(() => {
    setResult(null)
    setBroken("")
  }, [where])

  const run = async () => {
    setBusy(true)
    setResult(null)
    setBroken("")
    try {
      setResult(await api.testMcp(where))
    } catch (error) {
      setBroken(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div>
        <Button size="sm" variant="outline" onClick={() => void run()} disabled={busy}>
          <PlugZap />
          {busy ? t("Testing…") : t("Test the connection")}
        </Button>
      </div>
      {result?.ok ? (
        <Alert variant="success" data-testid="mcp-test-result" data-result="ok">
          <AlertDescription>
            {t("Ponos answers at {{address}} and asks for a key, as it should: a client can connect.", { address })}
          </AlertDescription>
        </Alert>
      ) : null}
      {result && !result.ok ? <Failure test={result} address={address} /> : null}
      {broken ? (
        <Alert variant="destructive" data-testid="mcp-test-result" data-result="failed">
          <AlertDescription className="flex flex-col gap-1">
            <span className="font-medium">{t("The test itself could not run.")}</span>
            <span>{t("Probable cause: {{cause}}", { cause: broken })}</span>
            <span>
              {t("What to do: {{todo}}", { todo: t("Check that the console is still running, then try again.") })}
            </span>
          </AlertDescription>
        </Alert>
      ) : null}
    </>
  )
}

/* The step-by-step: which client, what to paste with the instance's own
 * values filled in, and the check. */
function Wizard({ overview }: { overview: McpOverview }) {
  const t = useT()
  const [client, setClient] = React.useState<Client>("claude-code")
  const [where, setWhere] = React.useState<Where>(overview.public ? "public" : "local")
  const address = where === "public" ? overview.public : overview.local

  const clients: [Client, string][] = [
    ["claude-code", t("Claude Code")],
    ["claude-desktop", t("Claude desktop")],
    ["other", t("Another client")],
  ]
  const desktopBlock = JSON.stringify(
    { mcpServers: { ponos: { command: "npx", args: ["-y", "mcp-remote", address] } } },
    null,
    2
  )

  return (
    <Card data-card="mcp-wizard" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
        <CardTitle className="text-base">{t("Plug Ponos into a client")}</CardTitle>
        <CardDescription className="text-[13px]">
          {t("Three steps. The address below is this console’s own: nothing to look up.")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5 px-5 pb-5 sm:px-6">
        <Step number={1} title={t("Choose your client")}>
          <div className="flex flex-wrap gap-2" role="group" aria-label={t("Client")}>
            {clients.map(([key, label]) => (
              <Button
                key={key}
                size="sm"
                variant={client === key ? "default" : "outline"}
                aria-pressed={client === key}
                onClick={() => setClient(key)}
              >
                {label}
              </Button>
            ))}
          </div>
          {overview.public ? (
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t("Reached from")}>
              <span className="text-muted-foreground text-xs">{t("Reached from")}</span>
              {(["public", "local"] as const).map((key) => (
                <Button
                  key={key}
                  size="xs"
                  variant={where === key ? "secondary" : "ghost"}
                  aria-pressed={where === key}
                  onClick={() => setWhere(key)}
                >
                  {key === "public" ? t("Elsewhere (public address)") : t("This machine")}
                </Button>
              ))}
            </div>
          ) : null}
        </Step>

        <Step number={2} title={t("Paste it")}>
          {client === "claude-code" ? (
            <>
              <p>{t("In a terminal, add the server:")}</p>
              <Copyable text={`claude mcp add --transport http ponos ${address}`} label={t("the command")} />
              <p className="text-muted-foreground">
                {t("Then, in Claude Code, type /mcp, choose ponos and Authenticate: the browser opens, you accept, and that is all. No key to copy.")}
              </p>
            </>
          ) : null}
          {client === "claude-desktop" ? (
            <>
              {overview.public ? (
                <>
                  <p>{t("In Claude: Settings, Connectors, Add custom connector. Paste this address:")}</p>
                  <Copyable text={overview.public} label={t("the address")} />
                  <p className="text-muted-foreground">
                    {t("The connector is reached by Anthropic’s servers, hence the public address.")}
                  </p>
                </>
              ) : (
                <Alert>
                  <AlertDescription>
                    {t("A connector needs an address reachable from the Internet, and none is set: fill in “Public address” in the General settings to use it.")}
                  </AlertDescription>
                </Alert>
              )}
              <p>{t("Or, for the desktop app on this machine, add this block to claude_desktop_config.json (it needs Node.js):")}</p>
              <Copyable text={desktopBlock} label={t("the configuration block")} />
            </>
          ) : null}
          {client === "other" ? (
            <>
              <p>{t("The address of the server (Streamable HTTP):")}</p>
              <Copyable text={address} label={t("the address")} />
              <p>
                {t("A client that cannot sign in by itself needs a key. Draw one in a terminal on the machine that runs Ponos — it is shown once, and never here:")}
              </p>
              <Copyable text="ponos mcp token" label={t("the command")} />
              <p className="text-muted-foreground">
                {t("The client sends it as the header Authorization: Bearer <key>. “ponos mcp revoke” takes it back.")}
              </p>
            </>
          ) : null}
        </Step>

        <Step number={3} title={t("Check that it answers")}>
          <p className="text-muted-foreground">
            {t("Before you try from the client, make sure the console is reachable at this address.")}
          </p>
          <TestConnection where={where} address={address} />
          <p className="text-muted-foreground">
            {t("In the client, the first call to try is “whoami”: it says whose console it is and whether the key reads or writes.")}
          </p>
        </Step>
      </CardContent>
    </Card>
  )
}

/** The clients that already hold a key, by name and by scope. */
function Clients({ overview }: { overview: McpOverview }) {
  const t = useT()
  return (
    <p className="text-muted-foreground text-[13px]" data-testid="mcp-clients">
      {overview.clients.length
        ? `${t("Clients that connected:")} ${overview.clients
            .map((one) => (one.scope ? `${one.name} (${one.scope})` : `${one.name} (${t("no live key")})`))
            .join(", ")}.`
        : t("No client has connected yet.")}
    </p>
  )
}

/* The MCP servers a session starts with — Notion, GitHub, a browser… — as
 * Claude Code holds them, each with what it answered. Read on demand: it
 * starts the servers to ask them, which takes a few seconds. */
function Servers() {
  const t = useT()
  const [read, setRead] = React.useState<McpServers | null>(null)
  const [asking, setAsking] = React.useState(false)

  const load = React.useCallback(async () => {
    setAsking(true)
    try {
      setRead(await api.mcpServers())
    } catch {
      setRead({ available: true, failed: true, servers: [] })
    } finally {
      setAsking(false)
    }
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  const states = {
    ok: [t("Connected"), "success"],
    auth: [t("To sign in"), "warn"],
    error: [t("Failing"), "error"],
  } as const

  return (
    <Card data-card="mcp-servers" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-base">{t("MCP servers of the sessions")}</CardTitle>
          <Button size="xs" variant="outline" onClick={() => void load()} disabled={asking}>
            <RefreshCw className={asking ? "animate-spin" : undefined} />
            {asking ? t("Checking…") : t("Check again")}
          </Button>
        </div>
        <CardDescription className="text-[13px]">
          {t("The ones Claude Code holds for the sessions Ponos starts: your own, and those of the project the console runs in.")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 px-5 pb-5 text-sm sm:px-6">
        {!read ? <p className="text-muted-foreground">{t("Asking Claude Code…")}</p> : null}
        {read && !read.available ? (
          <Alert>
            <AlertDescription>
              {t("Claude Code is not installed on this machine, so there is nothing to list. Install it, then check again.")}
            </AlertDescription>
          </Alert>
        ) : null}
        {read?.available && read.failed ? (
          <Alert variant="destructive">
            <AlertDescription>
              {t("Claude Code did not answer. Try “claude mcp list” in a terminal to see why.")}
            </AlertDescription>
          </Alert>
        ) : null}
        {read?.available && !read.failed && !read.servers.length ? (
          <p className="text-muted-foreground">{t("No MCP server is configured yet.")}</p>
        ) : null}
        {read?.servers.length ? (
          <ul className="divide-y" data-testid="mcp-servers">
            {read.servers.map((server) => {
              const [label, tone] = states[server.state]
              return (
                <li
                  key={server.name}
                  data-server={server.name}
                  data-state={server.state}
                  className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0"
                >
                  <span className="min-w-0">
                    <span className="block font-medium">{server.name}</span>
                    <span className="text-muted-foreground block truncate font-mono text-xs">{server.target}</span>
                  </span>
                  <Badge
                    variant="outline"
                    className={
                      tone === "success"
                        ? "text-tr-green border-tr-green/30"
                        : tone === "warn"
                          ? "text-tr-amber border-tr-amber/30"
                          : "text-destructive border-destructive/30"
                    }
                  >
                    {label}
                  </Badge>
                </li>
              )
            })}
          </ul>
        ) : null}
        <div className="flex flex-col gap-2 border-t pt-3">
          <p className="font-medium">{t("Add one")}</p>
          <p className="text-muted-foreground">
            {t("In a terminal, from the folder of the project that needs it (or with --scope user for all of them):")}
          </p>
          <Copyable text="claude mcp add --transport http <name> <address>" label={t("the command")} />
          <p className="text-muted-foreground">
            {t("Replace <name> and <address> with those the service gives. For a server that runs a command: claude mcp add <name> -- npx -y <package>. Then check again here.")}
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

export function McpPage() {
  const t = useT()
  const [overview, setOverview] = React.useState<McpOverview | null>(null)
  const [failed, setFailed] = React.useState("")

  React.useEffect(() => {
    let live = true
    api.mcp().then(
      (read) => live && setOverview(read),
      (error) => live && setFailed(error instanceof Error ? error.message : String(error))
    )
    return () => {
      live = false
    }
  }, [])

  return (
    <div className="flex max-w-[720px] min-w-0 flex-col gap-5" data-page="mcp">
      <Card data-card="mcp-what" className="gap-0 py-0">
        <CardHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
          <CardTitle className="text-base">{t("What is an MCP?")}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 px-5 pb-5 text-sm leading-relaxed sm:px-6">
          <p>
            {t("An MCP (Model Context Protocol) is a plug that lets Claude use a tool or a service: read a page, open an issue, drive a browser. Each service offers its own, and Claude uses the ones it is given.")}
          </p>
          <p>
            {t("For Ponos it works both ways. The sessions it starts use MCPs: it is thanks to the Notion one that a session reads a ticket and writes its report back.")}
          </p>
          <p>
            {t("And Ponos has one of its own: plugged into Claude, it lets you list your tasks, create one or answer a blocked ticket from a conversation, without opening the console.")}
          </p>
        </CardContent>
      </Card>
      {failed ? (
        <Alert variant="destructive">
          <AlertDescription>{failed}</AlertDescription>
        </Alert>
      ) : null}
      {overview ? (
        <>
          <Wizard overview={overview} />
          <Clients overview={overview} />
        </>
      ) : failed ? null : (
        <p className="text-muted-foreground text-sm">{t("Reading the addresses…")}</p>
      )}
      <Servers />
    </div>
  )
}
