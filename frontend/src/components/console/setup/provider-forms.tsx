import { RefreshCw } from "lucide-react"

import { Command, Field } from "@/components/console/setup/bits"
import { Rich } from "@/components/console/text"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { useT } from "@/lib/i18n"

/** What `claude` answered last: installed or not, and the commands that follow. */
export interface Login {
  installed: boolean
  install: string
  command: string
}

/** The CLI, chosen: how to install it or sign it in, here or in the container. */
export function CliLogin({
  container,
  login,
  signed,
  busy,
  onUse,
  onCheck,
  onKey,
}: {
  container: boolean
  login: Login | null
  signed: boolean
  busy: boolean
  onUse: () => void
  onCheck: () => void
  onKey: () => void
}) {
  const t = useT()
  return (
    <div className="flex flex-col gap-3" data-testid="provider-cli-login">
      {login && !login.installed ? (
        <>
          <p className="text-muted-foreground text-sm leading-relaxed">
            <Rich
              text={
                container
                  ? t(
                      "Claude Code is not installed in the container. In its terminal — Dokploy's Terminal tab on the service, or `docker compose exec ponos bash` — install it, then sign it in:"
                    )
                  : t("Claude Code is not installed on this machine. In a terminal, install it, then sign it in:")
              }
            />
          </p>
          <Command text={login.install} />
          <Command text={login.command} />
        </>
      ) : signed ? null : (
        <>
          <p className="text-muted-foreground text-sm leading-relaxed">
            <Rich
              text={
                container
                  ? t(
                      "Open a terminal in the container — Dokploy's Terminal tab on the service, or `docker compose exec ponos bash` — and sign in there. The sign-in is kept in the `~/.claude` volume."
                    )
                  : t("In a terminal on this machine, sign Claude Code in:")
              }
            />
          </p>
          <Command text={login?.command || "claude auth login"} />
        </>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={busy} onClick={onUse}>
          {t("Use the CLI")}
        </Button>
        <Button type="button" variant="outline" disabled={busy} onClick={onCheck}>
          <RefreshCw />
          {t("Check again")}
        </Button>
      </div>
      {login && !signed ? (
        <p className="text-muted-foreground text-xs leading-relaxed">
          {t("Rather not install the CLI? An API key needs nothing on this machine.")}{" "}
          <button type="button" className="text-foreground underline underline-offset-2" onClick={onKey}>
            {t("Use an Anthropic API key")}
          </button>
        </p>
      ) : null}
    </div>
  )
}

/** A key, chosen: Anthropic's or OpenRouter's, checked against its provider before it is written. */
export function KeyForm({
  chosen,
  value,
  routed,
  busy,
  onType,
  onRoute,
  onSave,
}: {
  chosen: "api_key" | "openrouter"
  value: string
  routed: boolean
  busy: boolean
  onType: (value: string) => void
  onRoute: (routed: boolean) => void
  onSave: () => void
}) {
  const t = useT()
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault()
        onSave()
      }}
    >
      <Field
        id="provider-key"
        label={chosen === "api_key" ? t("Anthropic API key") : t("OpenRouter key")}
        type="password"
        placeholder={chosen === "api_key" ? "sk-ant-…" : "sk-or-…"}
        value={value}
        onChange={(event) => onType(event.target.value)}
        hint={t(
          "Left empty, the key already in the configuration — or in the container's environment — is the one checked."
        )}
      />
      {chosen === "openrouter" ? (
        <label className="flex items-start gap-2 text-sm">
          <Checkbox checked={routed} onCheckedChange={(checked) => onRoute(checked === true)} className="mt-0.5" />
          <span>
            <span className="font-medium">{t("Run the sessions on OpenRouter")}</span>
            <span className="text-muted-foreground block text-xs leading-relaxed">
              {t("Off, the key is only handed to the sessions, and they keep running on the CLI's sign-in.")}
            </span>
          </span>
        </label>
      ) : null}
      <div>
        <Button type="submit" disabled={busy}>
          {busy ? t("Checking…") : t("Check and save")}
        </Button>
      </div>
    </form>
  )
}
