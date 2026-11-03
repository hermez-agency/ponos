import { useT } from "@/lib/i18n"
import { money } from "@/lib/numbers"
import type { Estimate } from "@/lib/types"
import { brief } from "@/lib/worktime"

/* What a ticket is likely to cost and take, before it is launched: the median
 * of the tickets like it that ran, and the 80th centile as « up to » — the
 * server's (`estimates.py`). Without enough of them there is no estimate, and
 * nothing is drawn: no figure is not a zero. */
export function TicketEstimate({ estimate, className }: { estimate?: Estimate | null; className?: string }) {
  const t = useT()
  if (!estimate) return null
  const time = brief(estimate.seconds)
  return (
    <span
      data-slot="ticket-estimate"
      className={className ?? "text-muted-foreground whitespace-nowrap tabular-nums"}
      title={t("Estimated from {{count}} similar tickets: the median, and the 80th centile", {
        count: String(estimate.tickets),
      })}
    >
      {t("≈ {{cost}} · {{time}}, up to {{high}}", {
        cost: money(estimate.cost),
        time: t(time.key, time.params),
        high: money(estimate.cost_high),
      })}
    </span>
  )
}
