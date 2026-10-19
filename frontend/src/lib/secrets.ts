/* Passwords and tokens, seen before a message leaves the page.
 *
 * What is typed at a ticket becomes a Notion comment, and a comment stays. The
 * runner masks what it recognises before writing it (see `redaction.py`), but
 * a person about to paste a password deserves to be told before it leaves the
 * page at all: so the bar holds the message back once, says why, and a second
 * press sends it — masked.
 *
 * The patterns are `redaction.py`'s, written again here: a test in
 * `tests/run.py` keeps the two lists of tokens identical. This module
 * imports nothing, so that `node --test` reads it as it is.
 */

/** Tokens that say what they are by their shape alone. */
export const TOKENS: readonly string[] = [
  String.raw`-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)`,
  String.raw`\bgh[pousr]_[A-Za-z0-9]{30,}`,
  String.raw`\bgithub_pat_[A-Za-z0-9_]{30,}`,
  String.raw`\bglpat-[A-Za-z0-9_-]{20,}`,
  String.raw`\bsk-[A-Za-z0-9_-]{20,}`,
  String.raw`\bxox[abposr]-[A-Za-z0-9-]{10,}`,
  String.raw`\bnpm_[A-Za-z0-9]{30,}`,
  String.raw`\b(?:ntn|secret)_[A-Za-z0-9]{30,}`,
  String.raw`\bAKIA[0-9A-Z]{16}\b`,
  String.raw`\b\d{8,10}:AA[A-Za-z0-9_-]{30,}`,
  String.raw`\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}`,
]

// JavaScript's `\b` knows no accent: « clé » ends where Python's would.
const LABELS =
  String.raw`passwords?|passwd|pwd|pass ?phrase|mots? de passe|mdp|` +
  String.raw`tokens?|jetons?|secrets?|api[ _-]?keys?|cl[ée]s? (?:d['’])?api|access[ _-]?keys?|` +
  String.raw`credentials?`

const LABELLED = new RegExp(
  String.raw`(?<![\p{L}\p{N}_])(?:${LABELS})(?![\p{L}\p{N}_])(?:[ \t]+[^\s:=]+){0,4}?` +
    String.raw`(?:[ \t]*([:=])[ \t]*|[ \t]+(?:is|est)[ \t]+(?:([:=])[ \t]*)?)` +
    String.raw`["'\x60«“]?[ \t]*([^\s"'\x60»”]{4,})`,
  "giu"
)

const IN_URL = /(?<=:\/\/)[^\s/:@]+:[^\s/@]+(?=@)/
const SHAPED = new RegExp(TOKENS.map((pattern) => `(?:${pattern})`).join("|"))

export type SecretKind = "token" | "password" | "address"

/** A value said with `is` / `est` that is only a word: « le token est expiré ». */
function plain(value: string): boolean {
  return /^\p{L}+$/u.test(value.replace(/[.,;!?]+$/, ""))
}

/** The kinds of secret in a message, in the order `redaction.found` gives them. */
export function secretsIn(text: string): SecretKind[] {
  const kinds: SecretKind[] = []
  if (SHAPED.test(text)) kinds.push("token")
  for (const match of text.matchAll(LABELLED)) {
    if (match[1] || match[2] || !plain(match[3])) {
      kinds.push("password")
      break
    }
  }
  if (IN_URL.test(text)) kinds.push("address")
  return kinds
}
