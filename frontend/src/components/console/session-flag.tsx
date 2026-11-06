import { useT } from "@/lib/i18n"
import type { ChatSession } from "@/lib/types"

/* What a conversation of the list is doing while it is not the one on screen:
 * answering, waiting for a place, or answered and not read yet. A dot and not
 * a badge — the list is read at a glance, and three of them may be answering
 * at once. The words are there for whoever hears the page and not sees it. */
export function SessionFlag({ session }: { session: Pick<ChatSession, "busy" | "waiting" | "unread"> }) {
  const t = useT()
  const label = session.busy
    ? t("Answering")
    : session.waiting
      ? t("Waiting for a free place")
      : session.unread
        ? t("Unread answer")
        : ""
  if (!label) return null
  return (
    <span
      data-session-flag={session.busy ? "busy" : session.waiting ? "waiting" : "unread"}
      title={label}
      className="inline-flex shrink-0 items-center"
    >
      <span
        aria-hidden
        className={
          session.busy
            ? "bg-primary size-2 animate-pulse rounded-full"
            : session.waiting
              ? "border-muted-foreground size-2 rounded-full border"
              : "bg-primary size-2 rounded-full"
        }
      />
      <span className="sr-only">{label}</span>
    </span>
  )
}
