import { toast } from "sonner"

import { why } from "./api"

/* An action drawn before the server has agreed to it.
 *
 * A click used to wait for the answer — often the board's, a second or three
 * away — before closing its window or showing its result. Here the page takes
 * the write for granted: `apply` draws the expected state now, `request` goes
 * out behind it, and when it is refused `rollback` puts the page back and a
 * toast says why. The stream stays the truth (see `board-store.ts`): whatever
 * it sends next replaces what was drawn, right or wrong.
 *
 * One mechanism for every write, so that none of them writes its own
 * try/catch — and none of them leaves a button disabled "while it works".
 * What must not run twice (a double send) is deduplicated by the caller, not
 * by freezing the page.
 *
 * Never rejects: a failure is already said. Resolves to whether the write went
 * through, for the few callers that go on afterwards. */
export interface Optimistic<T> {
  /** Draws the expected state, synchronously, before anything is sent. */
  apply: () => void
  /** The write itself. */
  request: () => Promise<T>
  /** Puts the page back as `apply` found it. */
  rollback: (error: unknown) => void
  /** Said in the error toast, above the reason the server gave. */
  failure: string
  /** Said at the click, not when the server answers. */
  success?: { title: string; description?: string }
  /** Runs with the answer, once the write went through. */
  settled?: (answer: T) => void
}

export async function optimistic<T>(action: Optimistic<T>): Promise<boolean> {
  action.apply()
  if (action.success) toast.success(action.success.title, { description: action.success.description })
  let answer: T
  try {
    answer = await action.request()
  } catch (error) {
    action.rollback(error)
    toast.error(action.failure, { description: why(error) })
    return false
  }
  action.settled?.(answer)
  return true
}
