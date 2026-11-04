import * as React from "react"
import { ArrowRight, RefreshCw } from "lucide-react"

import { ConnectGithub, TokenForm } from "@/components/console/github-page"
import { Command, Said, StepCard } from "@/components/console/setup/bits"
import { useKnown } from "@/components/console/setup/known"
import { Rich } from "@/components/console/text"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { useFrench, useT } from "@/lib/i18n"
import { settingsFrench } from "@/lib/settings-store"
import type { Summary } from "@/lib/types"

/* -- 4. github -------------------------------------------------------------- */

export function GithubStep({ container, onNext }: { container: boolean; onNext: () => void }) {
  const t = useT()
  const [github, setGithub] = React.useState<Summary["github"] | null>(null)
  const [busy, setBusy] = React.useState(false)
  const { reread } = useKnown()
  // The button and the token's form are the GitHub tab's, and say its words.
  const worded = useFrench(settingsFrench)

  const check = React.useCallback(async () => {
    setBusy(true)
    try {
      setGithub(await api.github())
    } catch (error) {
      setGithub({ state: "error", account: "", via: "gh", said: why(error), command: "", create_url: "" })
    } finally {
      setBusy(false)
    }
  }, [])

  React.useEffect(() => {
    void check()
  }, [check])

  return (
    <StepCard
      title={t("GitHub, for the pull requests")}
      blurb={t(
        "A code ticket comes back as a pull request. Connect GitHub in one click: Ponos creates its own GitHub App and you choose the repositories it reaches. Or paste an access token. Without either, `gh` is used — signed in with `gh auth login`, or given a token in `GH_TOKEN`, the way a container usually is."
      )}
      footer={
        <>
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => {
              void check()
              reread()
            }}
          >
            <RefreshCw />
            {t("Check again")}
          </Button>
          <Button type="button" variant="outline" onClick={onNext}>
            {t("Continue")}
            <ArrowRight />
          </Button>
        </>
      }
    >
      {worded && github?.via !== "app" && github?.via !== "token" ? <ConnectGithub /> : null}
      {worded && github?.via !== "app" && github?.via !== "token" ? (
        <details data-testid="github-token-choice">
          <summary className="cursor-pointer text-sm font-medium">{t("Or use an access token instead")}</summary>
          <div className="pt-3">
            <TokenForm
              createUrl={github?.create_url ?? ""}
              onSaved={() => {
                void check()
                reread()
              }}
            />
          </div>
        </details>
      ) : null}
      {github ? (
        github.account ? (
          <Said
            ok
            text={
              github.via === "app"
                ? t("Pull requests are opened as {{account}}, through the GitHub App.", {
                    account: github.account,
                  })
                : github.via === "token"
                ? t("Pull requests are opened as {{account}}, with the access token.", {
                    account: github.account,
                  })
                : github.via === "GH_TOKEN"
                ? t("Pull requests are opened as {{account}}, with the token in `GH_TOKEN`.", {
                    account: github.account,
                  })
                : t("Pull requests are opened as {{account}}.", { account: github.account })
            }
          />
        ) : (
          <>
            <Said ok={false} text={github.said || t("gh is not signed in.")} />
            <p className="text-muted-foreground text-sm leading-relaxed">
              {t("Or, without the app:")}{" "}
              <Rich
                text={
                  container
                    ? t(
                        "Set `GH_TOKEN` in the service's environment and redeploy — or sign in from its terminal:"
                      )
                    : t("In a terminal on this machine:")
                }
              />
            </p>
            <Command text={github.command || "gh auth login"} />
          </>
        )
      ) : (
        <p className="text-muted-foreground text-sm">{t("Asking gh…")}</p>
      )}
    </StepCard>
  )
}
