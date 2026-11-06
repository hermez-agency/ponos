import * as React from "react"

import { installOffer, isIos, type InstallOffer } from "./install"
import { keyBytes } from "./push"

/* The console as an installed app: its worker, its update, its install button.
 *
 * Three small stores in one place, because they all hang off the same two
 * browser objects — the worker's registration and `beforeinstallprompt` — and
 * the page reads them the same way (`useSyncExternalStore`).
 *
 * Registered in a build only: the dev server serves modules, not hashed
 * files, and a worker holding one of them would outlive the edit.
 */

interface InstallPrompt extends Event {
  prompt(): Promise<unknown>
}

const listeners = new Set<() => void>()
const changed = () => listeners.forEach((listener) => listener())
const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

let prompt: InstallPrompt | null = null
let waiting: ServiceWorker | null = null
let applying = false

export const standalone = () =>
  window.matchMedia("(display-mode: standalone)").matches ||
  // iOS says it here and nowhere else.
  (navigator as Navigator & { standalone?: boolean }).standalone === true

/** Called once, before the first render. */
export function startServiceWorker() {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault() // the browser's own mini-bar: the button is ours
    prompt = event as InstallPrompt
    changed()
  })
  window.addEventListener("appinstalled", () => {
    prompt = null
    changed()
  })

  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return

  /* A new worker that installed while another one controls the page is a new
   * version: it waits there until the page says so. The first ever install has
   * no controller, and nothing to ask about. */
  const watch = (worker: ServiceWorker | null) =>
    worker?.addEventListener("statechange", () => {
      if (worker.state === "installed" && navigator.serviceWorker.controller) {
        waiting = worker
        changed()
      }
    })

  navigator.serviceWorker.register("/sw.js").then((registration) => {
    if (registration.waiting && navigator.serviceWorker.controller) {
      waiting = registration.waiting
      changed()
    }
    watch(registration.installing)
    registration.addEventListener("updatefound", () => watch(registration.installing))
    // An installed app is rarely launched again: ask for a new version when it
    // comes back into view, and once an hour while it stays open.
    const check = () => void registration.update().catch(() => {})
    document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && check())
    setInterval(check, 60 * 60 * 1000)
  })

  // Only what the page asked for reloads it: the first worker ever installed
  // takes control too, and a console that blinked on its first visit would be
  // a console that lost what its user had just typed.
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (applying) location.reload()
  })
}

/** Whether a new version is installed and waiting for the page to take it. */
export function useUpdateWaiting(): boolean {
  return React.useSyncExternalStore(subscribe, () => waiting !== null)
}

/** Take the waiting version: the page reloads on the new one. */
export function applyUpdate() {
  applying = true
  waiting?.postMessage("skip-waiting")
}

/** What the install button should do, if anything. */
export function useInstallOffer(): InstallOffer {
  return React.useSyncExternalStore(subscribe, () =>
    installOffer({
      standalone: standalone(),
      promptReady: prompt !== null,
      ios: isIos(navigator.userAgent, navigator.platform, navigator.maxTouchPoints),
    })
  )
}

export async function install() {
  const asked = prompt
  if (!asked) return
  prompt = null // an event is good for one prompt
  changed()
  await asked.prompt()
}

/* -- the bell, pushed (`src/ponos/push.py`) --------------------------------- */

/** Whether this page can subscribe at all: a build's worker, and a browser with Web Push. */
export const pushSupported = () =>
  import.meta.env.PROD && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window

/** This browser's subscription, if it has one. */
export async function currentPush(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null
  const registration = await navigator.serviceWorker.getRegistration()
  return (await registration?.pushManager.getSubscription()) ?? null
}

/** Asks the browser — its permission, then its push service — for a subscription to `key`.
 *
 * One kept from before is dropped first: switching on is what somebody does
 * when pushes stopped arriving, and an old subscription may be to a key the
 * console no longer has. */
export async function subscribeToPush(key: string): Promise<PushSubscription> {
  const permission = await Notification.requestPermission()
  if (permission !== "granted") throw new Error(permission)
  const registration = await navigator.serviceWorker.ready
  await (await registration.pushManager.getSubscription())?.unsubscribe()
  return registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) })
}
