import { describe, expect, test } from "vitest"

import { withoutProtocol } from "./session-log"

/* What a session's last message shows: its words, not the lines the runner reads. */
describe("withoutProtocol", () => {
  test("drops the end-of-session lines and keeps the prose", () => {
    const said = [
      "J'ai terminé la boîte mail.",
      "",
      "DONE: boîte créée",
      "WHY: identifiants manquants",
      "CATEGORY: access",
      "QUESTION: Peux-tu fournir le jeton ?",
      "MODE: free",
      "CODE: access.credentials",
      "RESULT: blocked — il manque le jeton",
    ].join("\n")
    expect(withoutProtocol(said)).toBe("J'ai terminé la boîte mail.")
  })

  test("leaves a sentence that merely mentions a keyword", () => {
    expect(withoutProtocol("Le RESULT: de la CI est vert.")).toBe("Le RESULT: de la CI est vert.")
  })

  test("a message of protocol alone becomes empty", () => {
    expect(withoutProtocol("RESULT: ok — fait")).toBe("")
  })
})
