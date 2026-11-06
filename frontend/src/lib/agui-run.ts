/* What `agui.ts` posts for a run, apart from it so that `node --test` reads it
 * as it is (`agui.ts` imports the API client). */

/** What a run posts: the message just written, never the thread before it.
 *
 * The server holds the thread and the session, and answers the last user
 * message only (`agui.last_user`); posting every turn made the body grow with
 * the conversation until it passed the server's limit.
 */
export const newMessages = <T extends { role: string }>(messages: readonly T[] | T[]): T[] => {
  for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "user") return [messages[i]]
  return []
}
