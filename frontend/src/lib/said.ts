/* What the first connection's steps repeat from the server, said in the page's language.
 *
 * A step shows what the machine answered — `gh` is not there, Claude Code is
 * not signed in — and those sentences are the Python's, in English
 * (`health.py`, `web/setup.py`, `provider.py`, `config.py`),
 * written for the journal and `ponos doctor` first. The page translates them
 * on arrival, like `refusals.ts` does for a refusal: the English sentence
 * recognised here is the key in `french.ts`, and what is technical in it — a
 * setting's name, a command, a path — is kept apart as the `detail`, which the
 * page puts behind a "Details" rather than in the middle of the sentence.
 *
 * A sentence this does not know comes back as it is, whole: better the
 * server's English than nothing (tests/test_release.py holds the list below to
 * the sources). Imports nothing, so that `node --test` reads it as it stands.
 */

export interface Explained {
  /** The English sentence, the key of the translation. */
  key: string
  params: Record<string, string>
  /** The technical words behind it — kept untranslated, shown on demand. */
  detail: string
}

/** The sentences the server says as they are, each a key of `french.ts`. */
export const PLAIN: readonly string[] = [
  "gh is not installed",
  "claude is not installed",
  "not signed in",
  "the sessions run on OpenRouter: name its slugs",
  "Claude Code is not installed",
]

/** A sentence with a part that varies: the expression that recognises it, the key it is said from, and the words that stay behind a "Details". */
const TEMPLATES: readonly {
  pattern: RegExp
  key: string
  params?: (found: RegExpExecArray) => Record<string, string>
  detail?: (found: RegExpExecArray, said: string) => string
}[] = [
  // provider.py: a provider chosen with no key.
  {
    pattern: /^claude\.provider = "api_key" with no key/,
    key: "No Anthropic API key is set.",
    detail: (_, said) => said,
  },
  {
    pattern: /^claude\.provider = "openrouter" with no key/,
    key: "No OpenRouter key is set.",
    detail: (_, said) => said,
  },
  // provider.py: Claude Code is there but nobody signed in.
  { pattern: /^not signed in — (.+)$/, key: "Claude Code is not signed in.", detail: (found) => found[1] },
  // prerequisites.py: a tool the machine lacks, said with its name, and the disk.
  { pattern: /^not installed$/, key: "{{name}} is not installed" },
  { pattern: /^(\d+) MB free$/, key: "{{mb}} MB free on the disk", params: (found) => ({ mb: found[1] }) },
  {
    pattern: /^free (\d+) MB — a ticket starts above (\d+) MB \(runner\.min_free_disk_mb\)$/,
    key: "Free {{missing}} MB: a ticket starts above {{minimum}} MB.",
    params: (found) => ({ missing: found[1], minimum: found[2] }),
    detail: () => "runner.min_free_disk_mb",
  },
]

/** A sentence of the server in its English key, its values, and the technical words that stay as written. */
export function explain(text: string, name = ""): Explained {
  const said = text.trim()
  if (PLAIN.includes(said)) return { key: said, params: {}, detail: "" }
  for (const { pattern, key, params, detail } of TEMPLATES) {
    const found = pattern.exec(said)
    if (!found || (key.includes("{{name}}") && !name)) continue
    return { key, params: { name, ...params?.(found) }, detail: detail?.(found, said) ?? "" }
  }
  return { key: said, params: {}, detail: "" }
}

/** What a missing tool says on the summary: its sentence, and the command that installs it behind it. */
export function explainNeed(need: { name: string; said: string; fix: string }): Explained[] {
  const main = explain(need.said, need.name)
  if (!need.fix) return [main]
  const fix = explain(need.fix, need.name)
  if (fix.key !== need.fix.trim()) return [main, fix]
  return [{ ...main, detail: need.fix }]
}
