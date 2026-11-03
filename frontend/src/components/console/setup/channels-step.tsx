import * as React from "react"
import { ArrowRight } from "lucide-react"

import { Field, Report, Said, StepCard } from "@/components/console/setup/bits"
import { useKnown } from "@/components/console/setup/known"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { ChannelsProvisioned } from "@/lib/types"

/* -- 6. channels ------------------------------------------------------------ */

export function ChannelsStep({ container, onNext }: { container: boolean; onNext: () => void }) {
  const t = useT()
  const [typed, setTyped] = React.useState({
    telegram_token: "",
    telegram_chat: "",
    slack_token: "",
    slack_channel: "",
  })
  const [busy, setBusy] = React.useState(false)
  const [done, setDone] = React.useState<ChannelsProvisioned | null>(null)
  const [problem, setProblem] = React.useState("")
  const { reread } = useKnown()
  const set = (key: keyof typeof typed) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setTyped({ ...typed, [key]: event.target.value })

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setProblem("")
    try {
      const answer = await api.saveChannels(typed)
      setDone(answer)
      if (!answer.problem)
        setTyped({ telegram_token: "", telegram_chat: "", slack_token: "", slack_channel: "" })
      reread()
    } catch (error) {
      setProblem(why(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(event) => void save(event)}>
      <StepCard
        title={t("Being told, and answering")}
        blurb={
          container
            ? t(
                "Optional — but on a server, the only way to hear about a blocked ticket: no desktop notification reaches you from a container. A question asked there is answered in the chat, and the answer lands on the ticket."
              )
            : t(
                "Optional. A blocked ticket asks its question there, and what you answer lands on the ticket."
              )
        }
        footer={
          <Button type="button" variant="outline" onClick={onNext}>
            {t("Continue")}
            <ArrowRight />
          </Button>
        }
      >
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-1 text-sm font-semibold">Telegram</legend>
          <Field
            id="telegram-token"
            label={t("Bot token")}
            type="password"
            value={typed.telegram_token}
            onChange={set("telegram_token")}
            hint={t(
              "@BotFather → `/newbot`, then say anything to your new bot: the chat id is read back from it."
            )}
          />
          <Field
            id="telegram-chat"
            label={t("Chat id")}
            value={typed.telegram_chat}
            onChange={set("telegram_chat")}
            hint={t("Found on its own — leave it empty unless you know it.")}
          />
        </fieldset>
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-1 text-sm font-semibold">Slack</legend>
          <Field
            id="slack-token"
            label={t("Slack bot token")}
            type="password"
            placeholder="xoxb-…"
            value={typed.slack_token}
            onChange={set("slack_token")}
          />
          <Field
            id="slack-channel"
            label={t("Slack channel ID")}
            value={typed.slack_channel}
            onChange={set("slack_channel")}
            hint={t("Then `/invite @your-bot` in the channel — the step everyone forgets.")}
          />
        </fieldset>
        <div>
          <Button type="submit" disabled={busy || !Object.values(typed).some((value) => value.trim())}>
            {busy ? t("Checking…") : t("Save and check")}
          </Button>
        </div>
        <Report done={done} />
        {done?.channels.map((channel) => (
          <Said key={channel.name} ok={channel.ok} text={`${channel.name} — ${channel.said}`} />
        ))}
        <Said ok={false} text={problem} />
      </StepCard>
    </form>
  )
}
