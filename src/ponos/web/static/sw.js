/* The console's service worker: the shell, and nothing else.
 *
 * What it keeps is the bundle's own files — `assets/`, whose names change with
 * what they hold, so a cached one is never stale — and the page shown when the
 * server does not answer. The tickets are not kept: every `/api/` call, the
 * event stream and the page itself go to the network, always, because a board
 * drawn from last week's cache would be worse than a board that says it cannot
 * be reached.
 *
 * `vite.config.ts` writes this file into the build with `02bd18fd61aa` replaced by
 * a hash of the files it shipped: a new deployment is a different `sw.js`, which
 * is how the browser knows to install it — and the old cache is dropped when
 * the new worker takes over. It does not take over by itself: the page asks
 * (`lib/service-worker.ts`), so a window in the middle of something is not
 * reloaded under its user.
 *
 * It also shows the bell pushed to a phone (`src/ponos/push.py`): one
 * notification per ticket — its `tag`, so a ticket that asks again replaces
 * what it said rather than stacking under it — and touching it opens the
 * ticket's decision, in the console already open when there is one.
 */
const BUILD = "02bd18fd61aa"
const CACHE = `ponos-shell-${BUILD}`
const OFFLINE = "/static/offline.html"

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll([OFFLINE, "/static/pwa/icon-192.png"])))
})

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((name) => name !== CACHE).map((name) => caches.delete(name))))
      .then(() => self.clients.claim())
  )
})

self.addEventListener("message", (event) => {
  if (event.data === "skip-waiting") self.skipWaiting()
})

self.addEventListener("fetch", (event) => {
  const request = event.request
  if (request.method !== "GET") return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  if (url.pathname.startsWith("/static/assets/")) {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const kept = await cache.match(request)
        if (kept) return kept
        const response = await fetch(request)
        if (response.ok) cache.put(request, response.clone())
        return response
      })
    )
    return
  }

  // The icon the offline page draws: kept at install, or it would be a broken one.
  if (url.pathname === "/static/pwa/icon-192.png") {
    event.respondWith(caches.match(request).then((kept) => kept || fetch(request)))
    return
  }

  // A page that cannot be had is the one thing with a fallback.
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE)))
  }
})

self.addEventListener("push", (event) => {
  let said = {}
  try {
    said = event.data ? event.data.json() : {}
  } catch {
    said = { body: event.data ? event.data.text() : "" }
  }
  event.waitUntil(
    self.registration.showNotification(said.title || "Ponos", {
      body: said.body || "",
      tag: said.tag || undefined,
      // A ticket that asks again is worth a second buzz: the tag replaces, this rings.
      renotify: Boolean(said.tag),
      requireInteraction: said.kind === "question",
      icon: "/static/pwa/icon-192.png",
      badge: "/static/pwa/icon-192.png",
      data: { url: said.url || "/" },
    })
  )
})

self.addEventListener("notificationclick", (event) => {
  event.notification.close()
  const target = new URL(event.notification.data?.url || "/", self.location.origin)
  if (target.origin !== self.location.origin) return
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (windows) => {
      const open = windows.find((client) => new URL(client.url).origin === target.origin)
      if (open) {
        await open.focus()
        return open.navigate(target.href).catch(() => self.clients.openWindow(target.href))
      }
      return self.clients.openWindow(target.href)
    })
  )
})
