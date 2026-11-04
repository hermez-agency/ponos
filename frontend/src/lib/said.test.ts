/* What the first connection repeats from the server, held to a translation.
 *
 *     npm test          (node --test, nothing to install)
 */
import assert from "node:assert/strict"
import { test } from "node:test"

import { FRENCH as CONSOLE } from "./french.ts"
import { SETUP_FRENCH } from "./setup-french.ts"
import { explain, explainNeed, PLAIN } from "./said.ts"

// The steps are drawn once their own words are in, beside the console's.
const FRENCH: Record<string, string> = { ...CONSOLE, ...SETUP_FRENCH }

const NOTION = "no Notion token yet — the console's first connection, or `ponos init`, sets it"
const CONFIG =
  "notion.token (PONOS_NOTION_TOKEN, in /home/me/secrets.env or the environment), notion.workspace (or notion.tickets_database) in /home/me/config.toml must be set\n  ponos init <page-url>   builds the databases"

test("a sentence of the server is a key of French, its technical words kept apart", () => {
  const notion = explain(NOTION)
  assert.equal(notion.key, "There is no Notion token yet.")
  assert.equal(notion.detail, NOTION, "the original stays behind the details")
  const config = explain(CONFIG)
  assert.equal(config.key, "The Notion token and the board are not set yet.")
  assert.match(config.detail, /PONOS_NOTION_TOKEN/)
  assert.equal(explain("notion.workspace (or notion.tickets_database) in /c.toml must be set").key, "The Notion board is not chosen yet.")
  assert.equal(explain("not signed in — claude auth login").detail, "claude auth login")
})

test("a tool the machine lacks is said with its name, and the command behind it", () => {
  const [gh] = explainNeed({ name: "gh", said: "not installed", fix: "sudo apt-get install -y gh" })
  assert.deepEqual(gh, { key: "{{name}} is not installed", params: { name: "gh" }, detail: "sudo apt-get install -y gh" })
  const [claude] = explainNeed({ name: "claude", said: "Claude Code is not installed", fix: "curl -fsSL https://claude.ai/install.sh | bash" })
  assert.equal(claude.key, "Claude Code is not installed")
  assert.match(claude.detail, /^curl /)
  const disk = explainNeed({ name: "disk", said: "10 MB free", fix: "free 90 MB — a ticket starts above 100 MB (runner.min_free_disk_mb)" })
  assert.deepEqual(
    disk.map((one) => one.key),
    ["{{mb}} MB free on the disk", "Free {{missing}} MB: a ticket starts above {{minimum}} MB."]
  )
})

test("every sentence the steps repeat has its French", () => {
  const sayings = [
    ...PLAIN,
    NOTION,
    CONFIG,
    "notion.token (X) in y must be set",
    "notion.workspace in y must be set",
    'claude.provider = "api_key" with no key: claude.api_key, or ANTHROPIC_API_KEY',
    'claude.provider = "openrouter" with no key: openrouter.key, or OPENROUTER_API_KEY',
    "not signed in — claude auth login",
    "12 MB free",
    "free 88 MB — a ticket starts above 100 MB (runner.min_free_disk_mb)",
  ]
  for (const said of sayings) {
    const { key } = explain(said, "gh")
    assert.ok(key in FRENCH, `“${key}” has no French`)
    assert.notEqual(FRENCH[key], key)
  }
  assert.ok("{{name}} is not installed" in FRENCH)
  assert.ok("Failed" in FRENCH, "the demonstration ticket's status")
})

test("a sentence not on the list comes back whole", () => {
  assert.deepEqual(explain("something else"), { key: "something else", params: {}, detail: "" })
  assert.equal(explain("not installed").key, "not installed", "no tool to name")
})
