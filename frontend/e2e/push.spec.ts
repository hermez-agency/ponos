import { expect, test } from "@playwright/test"

/* The bell on a phone: Settings › Communication subscribes this browser, and
 * the worker shows what is pushed to it.
 *
 * The push service is Google's, which a test does not reach: the browser's
 * `pushManager.subscribe` is replaced by one that hands back a subscription
 * of the shape it would — an HTTPS endpoint, two keys — so that what is tested
 * is the console's side of it, through the real server. And a push is handed
 * to the worker by DevTools (`ServiceWorker.deliverPushMessage`), as the push
 * service would hand it: what the worker then shows is the notification, with
 * the ticket as its tag and the decision as where it leads. The encryption and
 * the signature are `tests/test_push.py`'s.
 */

test.use({ viewport: { width: 1440, height: 900 } })

const SECTION = "/?view=console/settings/read/config/communication"

test("a browser subscribes from the settings, and the worker shows a pushed ticket", async ({ page, context }) => {
  const origin = String(test.info().project.use.baseURL)
  await context.grantPermissions(["notifications"], { origin })
  await context.addCookies([{ name: "ponos_token", value: "e2e", url: origin }])
  const endpoint = `https://push.example.test/e2e/${test.info().workerIndex}-${Date.now()}`
  await page.addInitScript((address) => {
    let held: object | null = null
    const subscription = {
      endpoint: address,
      toJSON: () => ({ endpoint: address, keys: { p256dh: "B" + "A".repeat(86), auth: "A".repeat(22) } }),
      unsubscribe: async () => {
        held = null
        return true
      },
    }
    PushManager.prototype.subscribe = async function () {
      held = subscription
      return subscription as unknown as PushSubscription
    }
    PushManager.prototype.getSubscription = async function () {
      return held as PushSubscription | null
    }
  }, endpoint)

  await page.goto(SECTION)
  const card = page.locator('[data-card="push"]')
  await expect(card.getByText("Notifications on this device")).toBeVisible()
  const toggle = card.getByTestId("push-switch")
  await expect(toggle).toHaveAttribute("aria-checked", "false")

  await toggle.click()
  await expect(toggle).toHaveAttribute("aria-checked", "true")
  await expect(card.getByRole("button", { name: "Send a test" })).toBeVisible()
  const devices = card.getByTestId("push-devices")
  await expect(devices).toContainText("this one")
  const listed = (await (await page.request.get("/api/push")).json()) as { devices: { endpoint: string }[] }
  expect(listed.devices.map((device) => device.endpoint)).toContain(endpoint)

  // What the push service would hand the worker, as DevTools hands it.
  const session = await context.newCDPSession(page)
  const registration = await page.evaluate(async () => {
    const ready = await navigator.serviceWorker.ready
    return ready.active?.scriptURL ?? ""
  })
  expect(registration).toContain("/sw.js")
  await session.send("ServiceWorker.enable")
  const registrationId = await new Promise<string>((resolve) => {
    session.on("ServiceWorker.workerRegistrationUpdated", ({ registrations }) => {
      const found = registrations.find((item) => item.scopeURL === `${origin}/`)
      if (found) resolve(found.registrationId)
    })
  })
  await session.send("ServiceWorker.deliverPushMessage", {
    origin,
    registrationId,
    data: JSON.stringify({
      title: "Blocked · Le header",
      body: "Which colour?",
      tag: "00000000000000000000000000000a5c",
      kind: "question",
      url: "/?view=console/tickets/read/00000000000000000000000000000a5c&tab=discussion",
    }),
  })
  await expect
    .poll(() =>
      page.evaluate(async () =>
        (await (await navigator.serviceWorker.ready).getNotifications()).map((shown) => ({
          title: shown.title,
          tag: shown.tag,
          url: (shown.data as { url: string }).url,
        }))
      )
    )
    .toEqual([
      {
        title: "Blocked · Le header",
        tag: "00000000000000000000000000000a5c",
        url: "/?view=console/tickets/read/00000000000000000000000000000a5c&tab=discussion",
      },
    ])

  await toggle.click()
  await expect(toggle).toHaveAttribute("aria-checked", "false")
  const left = (await (await page.request.get("/api/push")).json()) as { devices: { endpoint: string }[] }
  expect(left.devices.map((device) => device.endpoint)).not.toContain(endpoint)
})
