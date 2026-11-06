/* Whether the bell can be pushed to this browser, held to what it says.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { deviceLabel, keyBytes, pushOffer } from "./push.ts"

const ready = {
  available: true,
  secure: true,
  supported: true,
  ios: false,
  standalone: false,
  permission: "default" as const,
  subscribed: false,
}

test("a phone on HTTPS with Web Push can switch it on, and off once on", () => {
  assert.equal(pushOffer(ready), "off")
  assert.equal(pushOffer({ ...ready, permission: "granted", subscribed: true }), "on")
  assert.equal(pushOffer({ ...ready, permission: "default", subscribed: true }), "off", "a permission reset is off")
})

test("what stands in the way is said in the order it has to be removed", () => {
  assert.equal(pushOffer({ ...ready, available: false, secure: false }), "unavailable")
  assert.equal(pushOffer({ ...ready, secure: false, ios: true }), "insecure")
  assert.equal(pushOffer({ ...ready, ios: true, supported: false }), "home-screen")
  assert.equal(pushOffer({ ...ready, ios: true, standalone: true }), "off", "added to the home screen")
  assert.equal(pushOffer({ ...ready, supported: false }), "unsupported")
  assert.equal(pushOffer({ ...ready, permission: "denied" }), "denied")
})

test("the key is base64url, without its padding", () => {
  assert.deepEqual([...keyBytes("BAE")], [4, 1])
  assert.deepEqual([...keyBytes("-_8")], [251, 255])
  assert.equal(keyBytes("B" + "A".repeat(86)).length, 65)
})

test("a device is named by what it is", () => {
  assert.equal(deviceLabel("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)", "iPhone", 5), "iPhone")
  assert.equal(deviceLabel("Mozilla/5.0 (Macintosh)", "MacIntel", 5), "iPad")
  assert.equal(deviceLabel("Mozilla/5.0 (Linux; Android 15)", "Linux armv8l", 5), "Android")
  assert.equal(deviceLabel("Mozilla/5.0 (X11; Linux x86_64)", "Linux x86_64", 0), "Linux")
})
