import * as React from "react"

import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

import { TextPartView, ThinkingPartView, ToolCallPartView, ToolResultPartView } from "./chat-parts"
import type { ChatMessageData, ChatPart, ToolCallPart, ToolResultPart } from "./chat-types"

/* A message, drawn part by part — Brand Assets' `chat-message`, its words
 * through `t()`. The user speaks in a bubble, the assistant across the whole
 * width. `streaming` marks the message being written: its last part gets the
 * caret. */
function ChatMessage({
  message,
  streaming = false,
  onApprove,
  className,
}: {
  message: ChatMessageData
  streaming?: boolean
  onApprove?: (approvalId: string, approved: boolean) => void
  className?: string
}) {
  const t = useT()
  const parts = message.parts as ReadonlyArray<ChatPart>
  const calls = new Map<string, ToolCallPart>()
  const results = new Map<string, ToolResultPart>()
  for (const part of parts) {
    if (part.type === "tool-call") calls.set(part.id, part)
    if (part.type === "tool-result") results.set(part.toolCallId, part)
  }

  const isUser = message.role === "user"
  const last = parts.length - 1

  const content = parts.map((part, index): React.ReactNode => {
    const live = streaming && index === last
    switch (part.type) {
      case "text":
        return isUser ? (
          <p key={index} className="text-message font-medium break-words whitespace-pre-wrap">
            {part.content}
          </p>
        ) : (
          <TextPartView key={index} part={part} streaming={live} />
        )
      case "thinking":
        return <ThinkingPartView key={index} part={part} streaming={live} defaultOpen={live} />
      case "tool-call":
        return (
          <ToolCallPartView
            key={part.id}
            part={part}
            result={results.get(part.id)}
            onApprove={onApprove}
          />
        )
      case "tool-result":
        return (
          <ToolResultPartView
            key={`${part.toolCallId}-result`}
            part={part}
            toolName={calls.get(part.toolCallId)?.name}
          />
        )
      default:
        return null
    }
  })

  return (
    <article
      data-slot="chat-message"
      data-role={message.role}
      aria-label={isUser ? t("You") : t("Assistant")}
      className={cn("flex w-full", isUser ? "justify-end" : "justify-start", className)}
    >
      <div
        className={cn(
          "flex min-w-0 flex-col gap-3",
          isUser
            ? "bg-primary text-primary-foreground max-w-[85%] rounded-3xl rounded-br-lg px-4 py-2.5"
            : "w-full"
        )}
      >
        {content}
      </div>
    </article>
  )
}

export { ChatMessage }
