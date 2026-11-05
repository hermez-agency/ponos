import * as React from "react"
import { BellRing, Trash2 } from "lucide-react"

import { Rich } from "@/components/console/text"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { isIos } from "@/lib/install"
import { deviceLabel, pushOffer, type PushOffer } from "@/lib/push"
import { currentPush, pushSupported, standalone, subscribeToPush } from "@/lib/service-worker"
import type { Push } from "@/lib/types"

/* The bell, pushed to this phone: the top of Settings › Communication.
 *
 * Not a field of `config.toml`: a subscription is this browser's, made by the
 * browser's push service for it alone, and only this page can ask for one. So
 * it is a card of its own, above the channels — a switch for this device, a
 * push to see it arrive, and the devices that already receive it, each of
 * which can be let go of (a phone lost or replaced keeps its subscription
 * until its push service says it is gone).
 *
 * What stands in the way is said rather than greyed out: HTTPS, the home
 * screen of an iPhone, a permission refused — see `lib/push.ts`.
 */
const BLOCKED: Record<Exclude<PushOffer, "on" | "off">, string> = {
  unavailable:
    "This installation cannot send push notifications: the `cryptography` package is missing. Update Ponos.",
  insecure:
    "Push notifications need the console over HTTPS: Tailscale gives it a certificate (`tailscale serve`), as does a reverse proxy.",
  "home-screen":
    "On an iPhone, add the console to the home screen first (Share, then Add to Home Screen), and open it from there.",
  unsupported: "This browser cannot receive push notifications.",
  denied: "Notifications are refused for this site: allow them in the browser's settings, then come back here.",
}

export function PushCard() {
  const t = useT()
  const [state, setState] = React.useState<Push | null>(null)
  const [mine, setMine] = React.useState<PushSubscription | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [said, setSaid] = React.useState<{ text: string; bad: boolean } | null>(null)

  React.useEffect(() => {
    let live = true
    Promise.all([api.push(), currentPush().catch(() => null)]).then(
      ([read, subscription]) => {
        if (!live) return
        setState(read)
        // A subscription the console does not list is one it lost: off, until switched on again.
        setMine(subscription && read.devices.some((d) => d.endpoint === subscription.endpoint) ? subscription : null)
      },
      () => undefined
    )
    return () => {
      live = false
    }
  }, [])

  if (!state) return null
  const offer = pushOffer({
    available: state.available,
    secure: window.isSecureContext,
    supported: pushSupported(),
    ios: isIos(navigator.userAgent, navigator.platform, navigator.maxTouchPoints),
    standalone: standalone(),
    permission: "Notification" in window ? Notification.permission : "default",
    subscribed: mine !== null,
  })

  const act = async (work: () => Promise<void>) => {
    setBusy(true)
    setSaid(null)
    try {
      await work()
    } catch (error) {
      setSaid({ text: why(error), bad: true })
    } finally {
      setBusy(false)
    }
  }

  const toggle = (on: boolean) =>
    act(async () => {
      if (on) {
        const subscription = await subscribeToPush(state.key).catch((error: unknown) => {
          // The browser said no: what to do about it is the card's line, not an error.
          if (error instanceof Error && error.message === "denied") return null
          throw error
        })
        if (!subscription) {
          setMine(null)
          return
        }
        const label = deviceLabel(navigator.userAgent, navigator.platform, navigator.maxTouchPoints)
        setState(await api.subscribePush(subscription.toJSON(), label))
        setMine(subscription)
      } else if (mine) {
        const endpoint = mine.endpoint
        await mine.unsubscribe().catch(() => false)
        setState(await api.unsubscribePush(endpoint))
        setMine(null)
      }
    })

  const test = () =>
    act(async () => {
      if (!mine) return
      const sent = await api.testPush(mine.endpoint)
      setSaid(
        sent.status >= 200 && sent.status < 300
          ? { text: t("Sent: it should arrive within a few seconds."), bad: false }
          : { text: t("The push service refused it ({status}).", { status: sent.status || "—" }), bad: true }
      )
    })

  const forget = (endpoint: string) =>
    act(async () => {
      if (mine?.endpoint === endpoint) {
        await mine.unsubscribe().catch(() => false)
        setMine(null)
      }
      setState(await api.unsubscribePush(endpoint))
    })

  return (
    <Card data-card="push" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
        <CardTitle className="text-base">{t("Notifications on this device")}</CardTitle>
        <CardDescription className="text-[13px]">
          {t(
            "The bell, pushed to this phone even when the console is closed: a question, a pull request to review, a red CI, a failure or a block — once per ticket. Touching it opens the ticket's decision."
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 px-5 pb-5 text-sm sm:px-6">
        {offer === "on" || offer === "off" ? (
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 font-medium">
              <Switch
                checked={offer === "on"}
                disabled={busy}
                onCheckedChange={(on) => void toggle(on)}
                data-testid="push-switch"
              />
              {t("Notify this device")}
            </label>
            {offer === "on" ? (
              <Button size="xs" variant="outline" disabled={busy} onClick={() => void test()}>
                <BellRing />
                {t("Send a test")}
              </Button>
            ) : null}
          </div>
        ) : (
          <p className="text-muted-foreground text-[13px] leading-relaxed" data-testid="push-blocked">
            <Rich text={t(BLOCKED[offer])} />
          </p>
        )}
        {said ? (
          <p className={said.bad ? "text-destructive text-[13px]" : "text-[13px] text-emerald-700 dark:text-emerald-400"}>
            {said.text}
          </p>
        ) : null}
        {state.devices.length ? (
          <div className="flex flex-col gap-1">
            <p className="text-muted-foreground text-xs font-medium">{t("Devices notified")}</p>
            <ul className="divide-y rounded-md border" data-testid="push-devices">
              {state.devices.map((device) => (
                <li key={device.endpoint} className="flex items-center gap-2 px-3 py-1.5 text-[13px]">
                  <span className="min-w-0 flex-1 truncate">
                    {device.label || t("A browser")}
                    {mine?.endpoint === device.endpoint ? ` · ${t("this one")}` : ""}
                    {device.who ? <span className="text-muted-foreground"> · {device.who}</span> : null}
                  </span>
                  <span className="text-muted-foreground text-xs">{device.created.slice(0, 10)}</span>
                  <Button
                    size="icon-xs"
                    variant="ghost"
                    disabled={busy}
                    aria-label={t("Stop notifying this device")}
                    onClick={() => void forget(device.endpoint)}
                  >
                    <Trash2 />
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
