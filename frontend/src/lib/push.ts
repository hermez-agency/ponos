/* Whether this browser can have the bell pushed to it, and what stands in the way.
 *
 * Kept free of the DOM, and of imports, so that `node --test` reads it as it is.
 *
 * Web Push asks for three things the console does not decide: a browser that
 * has it (`PushManager`), a page served over HTTPS — `localhost` aside, which
 * a phone never is: Tailscale or a reverse proxy gives the console its
 * certificate — and, on an iPhone, the console added to the home screen,
 * since Safari pushes to installed apps only. Then the permission, which the
 * browser asks once and a refusal of which only its own settings take back.
 */
export type PushOffer =
  | "unavailable" // the installation cannot send: `cryptography` is missing
  | "insecure" // plain HTTP: no push without a certificate
  | "home-screen" // an iPhone, in Safari: add it to the home screen first
  | "unsupported" // a browser without Web Push
  | "denied" // refused once: only the browser's settings can say yes now
  | "off" // can be switched on
  | "on" // this browser is subscribed

export function pushOffer(state: {
  available: boolean
  secure: boolean
  supported: boolean
  ios: boolean
  standalone: boolean
  permission: "default" | "granted" | "denied"
  subscribed: boolean
}): PushOffer {
  if (!state.available) return "unavailable"
  if (!state.secure) return "insecure"
  if (state.ios && !state.standalone) return "home-screen"
  if (!state.supported) return "unsupported"
  if (state.permission === "denied") return "denied"
  return state.subscribed && state.permission === "granted" ? "on" : "off"
}

/** The console's key as the browser takes it: base64url, decoded to bytes. */
export function keyBytes(key: string): Uint8Array<ArrayBuffer> {
  const padded = key.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (key.length % 4)) % 4)
  const text = atob(padded)
  const bytes = new Uint8Array(new ArrayBuffer(text.length))
  for (let index = 0; index < text.length; index++) bytes[index] = text.charCodeAt(index)
  return bytes
}

/** What the list of devices calls this one: what it is, not which browser build. */
export function deviceLabel(userAgent: string, platform: string, touchPoints: number): string {
  if (/iPhone/.test(userAgent)) return "iPhone"
  if (/iPad/.test(userAgent) || (platform === "MacIntel" && touchPoints > 1)) return "iPad"
  if (/Android/.test(userAgent)) return "Android"
  if (/Mac/.test(platform)) return "Mac"
  if (/Win/.test(platform)) return "Windows"
  if (/Linux/.test(platform)) return "Linux"
  return ""
}
