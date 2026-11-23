import { copy } from "@/lib/copy"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

/* The ticket's public id — `PON-142` — said right after its title, and copied by
 * a click: it is what one says out loud, writes in a message or types after
 * `ponos show`. A button, so that a keyboard reaches it; it stops the click
 * where it is, since it sits inside links that open the ticket. The id is the
 * text of the button and "Copied" is the toast's — `copy` says it with the id
 * under it, and says so too when the clipboard refused. Nothing for a ticket
 * that has none. */
export function TicketId({ id, className }: { id?: string; className?: string }) {
  const t = useT()
  if (!id) return null
  return (
    <button
      type="button"
      data-slot="ticket-id"
      title={t("Copy the id {{id}}", { id })}
      aria-label={t("Copy the id {{id}}", { id })}
      draggable={false}
      onClick={(event) => {
        event.preventDefault()
        event.stopPropagation()
        void copy(id, id)
      }}
      className={cn(
        "text-muted-foreground hover:text-foreground focus-visible:ring-ring cursor-copy rounded-sm font-mono text-xs font-normal whitespace-nowrap outline-none focus-visible:ring-2",
        className
      )}
    >
      {id}
    </button>
  )
}
