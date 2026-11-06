import * as React from "react"
import { ArrowRight } from "lucide-react"

import { Said, StepCard } from "@/components/console/setup/bits"
import { useKnown } from "@/components/console/setup/known"
import { ProviderChoices } from "@/components/console/setup/provider-choices"
import { CliLogin, KeyForm, type Login } from "@/components/console/setup/provider-forms"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { Provider } from "@/lib/types"

/* -- 2. the provider -------------------------------------------------------- */

export function ProviderStep({ container, onNext }: { container: boolean; onNext: () => void }) {
  const t = useT()
  const [chosen, setChosen] = React.useState<Provider | null>(null)
  const [key, setKey] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [said, setSaid] = React.useState<{ ok: boolean; text: string } | null>(null)
  // What `claude` answered last: installed or not, and the commands that follow.
  const [login, setLogin] = React.useState<Login | null>(null)
  const { summary, reread } = useKnown()
  const seeded = React.useRef(false)

  React.useEffect(() => {
    // What the file already says, so coming back to the step shows it chosen —
    // once: a summary read again after a save does not undo a click.
    if (!summary || seeded.current) return
    seeded.current = true
    if (summary.provider.stated) setChosen(summary.provider.provider)
    if (summary.provider.stated && summary.provider.provider === "cli") void checkLogin(false)
    // `checkLogin` is called once, behind `seeded`: a new one each render is no
    // reason to look again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary])

  const save = async (provider: Provider) => {
    setBusy(true)
    setSaid(null)
    try {
      const answer = await api.saveProvider({
        provider,
        key: key.trim(),
      })
      if (answer.command)
        setLogin({ installed: answer.installed ?? true, install: answer.install ?? "", command: answer.command })
      setSaid({
        ok: answer.ok,
        text: answer.ok
          ? t("Written to the configuration: {{said}}", { said: answer.said })
          : answer.said,
      })
      if (answer.ok) setKey("")
      reread()
    } catch (error) {
      setSaid({ ok: false, text: why(error) })
    } finally {
      setBusy(false)
    }
  }

  // Asked on its own when the CLI is chosen, the summary is not read again: it
  // asked `claude` the same question. A click may follow a sign-in, and does.
  const checkLogin = async (again = true) => {
    setBusy(true)
    try {
      const answer = await api.claudeLogin()
      setLogin(answer)
      setSaid({
        ok: answer.ok,
        text: answer.ok ? t("Claude Code is signed in as {{who}}.", { who: answer.said }) : answer.said,
      })
      if (again) reread()
    } catch (error) {
      setSaid({ ok: false, text: why(error) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <StepCard
      title={t("Who answers the sessions")}
      blurb={t(
        "The choice that matters most: it decides who bills the work, which models a ticket can name, and whether a ticket can use the browser. It can be changed later in the settings."
      )}
      footer={
        <Button type="button" variant="outline" onClick={onNext}>
          {t("Continue")}
          <ArrowRight />
        </Button>
      }
    >
      <ProviderChoices
        chosen={chosen}
        onChoose={(choice) => {
          setChosen(choice)
          setSaid(null)
          setKey("")
          // The CLI is asked at once: installed? signed in? — not at the summary.
          if (choice === "cli") void checkLogin(false)
        }}
      />

      {chosen === "cli" ? (
        <CliLogin
          container={container}
          login={login}
          signed={Boolean(said?.ok)}
          busy={busy}
          onUse={() => void save("cli")}
          onCheck={() => void checkLogin()}
          onKey={() => {
            setChosen("api_key")
            setSaid(null)
          }}
        />
      ) : chosen === "api_key" || chosen === "openrouter" ? (
        <KeyForm
          chosen={chosen}
          value={key}
          busy={busy}
          onType={setKey}
          onSave={() => void save(chosen)}
        />
      ) : null}

      {said ? <Said ok={said.ok} text={said.text} /> : null}
    </StepCard>
  )
}
