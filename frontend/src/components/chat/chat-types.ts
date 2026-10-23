/* The types of the chat kit, from Brand Assets (`chat-types` in the `hermez`
 * registry). They are the shape of TanStack AI's messages (`useChat` of
 * `@tanstack/ai-react`): a message has `parts`, a part has a `type`. The
 * components depend on that shape, never on the package.
 *
 * One change from the registry: a tool call also reads `complete` and `error`,
 * the states TanStack AI 1.0 leaves on a call once its result has come back.
 */

export type ToolCallState =
  | "awaiting-input"
  | "input-streaming"
  | "input-complete"
  | "approval-requested"
  | "approval-responded"
  | "complete"
  | "error"

export interface TextPart {
  type: "text"
  content: string
}

export interface ThinkingPart {
  type: "thinking"
  content: string
}

export interface ToolCallPart {
  type: "tool-call"
  id: string
  name: string
  /** The arguments, as JSON — possibly incomplete while they stream. */
  arguments: string
  state: ToolCallState
  approval?: { id: string; needsApproval: boolean; approved?: boolean }
  output?: unknown
}

export interface ToolResultPart {
  type: "tool-result"
  toolCallId: string
  content: string
  state: "streaming" | "complete" | "error"
  error?: string
}

export type ChatPart = TextPart | ThinkingPart | ToolCallPart | ToolResultPart

export interface ChatMessageData {
  id: string
  role: "system" | "user" | "assistant"
  /** Parts of any other type (image, audio…) are not drawn. */
  parts: ReadonlyArray<ChatPart | { type: string }>
  createdAt?: Date
}

/** The state a tool call is shown in. */
export type ToolStatus = "pending" | "running" | "done" | "error" | "approval" | "denied"

/** The shown state of a tool call, from its TanStack AI state and its result. */
export function toolStatus(call: ToolCallPart, result?: ToolResultPart): ToolStatus {
  if (result?.state === "error" || call.state === "error") return "error"
  if (result?.state === "complete" || call.output !== undefined) return "done"
  if (call.state === "approval-requested") return "approval"
  if (call.approval?.approved === false) return "denied"
  if (call.state === "awaiting-input") return "pending"
  return "running"
}
