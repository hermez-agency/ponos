import * as React from "react"
import { ArrowRight } from "lucide-react"

import { Field, Said, StepCard } from "@/components/console/setup/bits"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { useLanguage, useT } from "@/lib/i18n"
import { accessProblem } from "@/lib/setup"
import type { SetupState } from "@/lib/types"

/* -- 1. access -------------------------------------------------------------- */

export function AccessStep({ state, onClaimed }: { state: SetupState; onClaimed: () => Promise<void> }) {
  const t = useT()
  const language = useLanguage()
  const [typed, setTyped] = React.useState({ code: "", email: "", password: "", confirm: "" })
  const [problem, setProblem] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const set = (key: keyof typeof typed) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setTyped({ ...typed, [key]: event.target.value })

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const refused = accessProblem(typed, state.code)
    if (refused) {
      setProblem(t(refused))
      return
    }
    setBusy(true)
    setProblem("")
    try {
      await api.claim({ ...typed, language })
      await onClaimed()
    } catch (error) {
      setProblem(why(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <StepCard
        title={t("Who opens this console")}
        blurb={t(
          "Nobody has claimed this console yet. The email and the password typed here are what it asks for from now on — and what closes this page behind you."
        )}
        footer={
          <Button type="submit" disabled={busy || (state.code && !state.code_drawn)}>
            {busy ? t("Claiming…") : t("Claim the console")}
            <ArrowRight />
          </Button>
        }
      >
        {state.code ? (
          state.code_drawn ? (
            <Field
              id="code"
              label={t("Installation code")}
              hint={t(
                "Printed by the console when it started — in a container, its logs (`docker compose logs ponos`, or the Logs tab in Dokploy). It is asked because this page is reached from outside the machine."
              )}
              value={typed.code}
              onChange={set("code")}
              placeholder="XXXX-XXXX"
              autoFocus
            />
          ) : (
            <Said
              ok={false}
              text={t(
                "This console is reached from outside its machine and was started without an installation code: restart it, and read the code in its logs."
              )}
            />
          )
        ) : null}
        <Field
          id="email"
          label={t("Email")}
          type="email"
          autoComplete="username"
          value={typed.email}
          onChange={set("email")}
          autoFocus={!state.code}
        />
        <Field
          id="password"
          label={t("Password")}
          type="password"
          autoComplete="new-password"
          value={typed.password}
          onChange={set("password")}
          hint={t(
            "8 characters at the least: behind this console sits a runner that runs code on its machine."
          )}
        />
        <Field
          id="confirm"
          label={t("The same password again")}
          type="password"
          autoComplete="new-password"
          value={typed.confirm}
          onChange={set("confirm")}
        />
        <Said ok={false} text={problem} />
      </StepCard>
    </form>
  )
}
