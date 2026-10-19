import * as React from "react"

import { money, number } from "@/lib/numbers"
import type { StatisticsDay } from "@/lib/types"
import { cn } from "@/lib/utils"

/* What came in, what went out, and what is left — one chart, day by day.
 *
 * It was two: the created and the closed in one, the open ones in another.
 * The second is the first added up, and two panels side by side made it look
 * like a second fact. So the flows are bars, two a day, and the stock is the
 * line drawn over them: a day with more bars of one colour is the line going
 * up or down, and both are read in the same glance.
 *
 * The stock lives on its own scale, on the right, when it is of another size
 * than the flows — forty tickets open against three a day would be a ruler
 * nobody reads the bars on — and shares the left one otherwise, so a chart
 * with one axis is not read as two.
 *
 * The spending is a second line, on a scale of its own, further right: dollars
 * are not tickets, and a day at three dollars would be flat against forty
 * open ones. `cost` comes from the API added up from the first day; the line
 * draws what each day spent, so it is the difference with the day before.
 *
 * Still an SVG drawn in the pixels it is given and nothing a chart library
 * would add: a few quiet rules, a legend, the day's three numbers under the
 * pointer, and the same numbers in a table a screen reader reads instead.
 */

const MARGIN = { top: 12, bottom: 24, side: 34 }

/** A step for the rules that lands on a round number: 1, 2, 5, 10, 20… */
function niceStep(rough: number): number {
  if (rough <= 0) return 1
  const power = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 5, 10].map((factor) => factor * power).find((candidate) => candidate >= rough)
  return Math.max(1, Math.ceil(step ?? 10 * power))
}

/** The top of an axis over `highest`, and its step, for `count` rules or so. */
function scale(highest: number, count: number): { top: number; step: number } {
  const step = niceStep(highest / count)
  return { top: Math.max(step, Math.ceil(highest / step) * step), step }
}

export interface ActivityLabels {
  created: string
  closed: string
  open: string
  spent: string
}

export function ActivityChart({
  points,
  labels,
  label,
  day,
  longDay,
  height = 200,
  className,
}: {
  points: StatisticsDay[]
  labels: ActivityLabels
  /** What the chart shows, for whoever cannot see it. */
  label: string
  /** The short date under the axis. */
  day: (point: StatisticsDay) => string
  /** The date in the tooltip and the table. */
  longDay: (point: StatisticsDay) => string
  /** In pixels, axis included. */
  height?: number
  className?: string
}) {
  const frame = React.useRef<HTMLDivElement>(null)
  const [width, setWidth] = React.useState(0)
  const [hovered, setHovered] = React.useState<number | null>(null)

  React.useLayoutEffect(() => {
    const element = frame.current
    if (!element) return
    setWidth(element.clientWidth)
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const flows = Math.max(0, ...points.flatMap((point) => [point.created, point.closed]))
  const stock = Math.max(0, ...points.map((point) => point.open))
  // Twice the other's size or more: on its own axis.
  const apart = Math.max(flows, stock) > 2 * Math.max(1, Math.min(flows, stock))
  const count = Math.max(2, Math.round(height / 50))
  const left = scale(apart ? flows : Math.max(flows, stock), count)
  const right = apart ? scale(stock, count) : left

  // Cents, so that the differences of rounded totals do not drift.
  const spent = points.map((point, index) => Math.round((point.cost - (index ? points[index - 1].cost : 0)) * 100) / 100)
  const expense = Math.max(0, ...spent)
  const dear = scale(expense, count)

  const margin = { left: MARGIN.side, right: (apart ? MARGIN.side : 12) + (expense > 0 ? MARGIN.side + 6 : 0) }
  const inner = Math.max(0, width - margin.left - margin.right)
  const tall = height - MARGIN.top - MARGIN.bottom
  const slot = points.length ? inner / points.length : 0
  // Two bars side by side in each day's slot, with air between the days.
  const bar = Math.max(1, Math.min(14, (slot * 0.7) / 2))
  const x = (index: number) => margin.left + slot * (index + 0.5)
  const y = (value: number, axis: { top: number }) => MARGIN.top + tall - (value / axis.top) * tall

  const rules: number[] = []
  for (let value = 0; value <= left.top + left.step / 2; value += left.step) rules.push(value)
  const dollars: number[] = []
  if (expense > 0) for (let value = 0; value <= dear.top + dear.step / 2; value += dear.step) dollars.push(value)
  const others: number[] = []
  if (apart) for (let value = 0; value <= right.top + right.step / 2; value += right.step) others.push(value)

  // One date every eighty pixels or so, always the last.
  const every = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(inner / 80))))
  const ticks = points
    .map((_, index) => index)
    .filter((index) => index % every === 0 && points.length - 1 - index >= every / 2)
  if (points.length) ticks.push(points.length - 1)

  const pick = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!points.length || inner <= 0) return
    const offset = event.clientX - event.currentTarget.getBoundingClientRect().left - margin.left
    setHovered(Math.min(points.length - 1, Math.max(0, Math.floor(offset / slot))))
  }

  const series = [
    { key: "created", label: labels.created, color: "var(--series-1)", value: (_: StatisticsDay) => _.created, format: number },
    { key: "closed", label: labels.closed, color: "var(--series-2)", value: (_: StatisticsDay) => _.closed, format: number },
    { key: "open", label: labels.open, color: "var(--series-3)", value: (_: StatisticsDay) => _.open, format: number },
    { key: "spent", label: labels.spent, color: "var(--series-4)", value: (_: StatisticsDay, index: number) => spent[index], format: money },
  ]
  const line = points.map((point, index) => `${index ? "L" : "M"}${x(index)},${y(point.open, right)}`).join("")
  const spending = points.map((_, index) => `${index ? "L" : "M"}${x(index)},${y(spent[index], dear)}`).join("")
  const at = hovered !== null ? points[hovered] : undefined

  return (
    <div className={cn("min-w-0", className)}>
      <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-hidden>
        {series.map((one) => (
          <li key={one.key} className="text-muted-foreground inline-flex items-center gap-1.5">
            <span
              className={one.key === "open" || one.key === "spent" ? "h-0.5 w-3 rounded-full" : "size-2.5 rounded-sm"}
              style={{ background: one.color }}
            />
            {one.label}
            {(one.key === "open" && apart) || (one.key === "spent" && expense > 0) ? " →" : null}
          </li>
        ))}
      </ul>

      <div ref={frame} className="relative w-full" style={{ height }}>
        {width > 0 ? (
          <svg
            width={width}
            height={height}
            role="img"
            aria-label={label}
            className="block touch-pan-y select-none"
            onPointerMove={pick}
            onPointerDown={pick}
            onPointerLeave={() => setHovered(null)}
            data-slot="activity-chart"
          >
            {rules.map((value) => (
              <g key={value}>
                <line
                  x1={margin.left}
                  x2={width - margin.right}
                  y1={y(value, left)}
                  y2={y(value, left)}
                  className="stroke-border"
                  strokeDasharray={value === 0 ? undefined : "2 4"}
                />
                <text
                  x={margin.left - 8}
                  y={y(value, left)}
                  dy="0.32em"
                  textAnchor="end"
                  className="fill-muted-foreground font-mono text-[0.65rem]"
                >
                  {number(value)}
                </text>
              </g>
            ))}

            {others.map((value) => (
              <text
                key={value}
                x={width - margin.right + 8}
                y={y(value, right)}
                dy="0.32em"
                textAnchor="start"
                className="font-mono text-[0.65rem]"
                style={{ fill: "var(--series-3)" }}
              >
                {number(value)}
              </text>
            ))}

            {dollars.map((value) => (
              <text
                key={value}
                x={width - margin.right + 8 + (apart ? MARGIN.side : 0)}
                y={y(value, dear)}
                dy="0.32em"
                textAnchor="start"
                className="font-mono text-[0.65rem]"
                style={{ fill: "var(--series-4)" }}
              >
                {money(value, 0)}
              </text>
            ))}

            {ticks.map((index) => (
              <text
                key={index}
                x={x(index)}
                y={height - 6}
                textAnchor={points.length > 1 && index === points.length - 1 ? "end" : "middle"}
                className="fill-muted-foreground font-mono text-[0.65rem]"
              >
                {day(points[index])}
              </text>
            ))}

            {hovered !== null ? (
              <rect
                x={margin.left + slot * hovered}
                y={MARGIN.top}
                width={slot}
                height={tall}
                className="fill-muted"
                opacity={0.6}
              />
            ) : null}

            {points.map((point, index) =>
              series.slice(0, 2).map((one, side) => {
                const value = one.value(point, index)
                if (!value) return null
                const top = y(value, left)
                return (
                  <rect
                    key={`${index}-${one.key}`}
                    x={x(index) + (side ? 0.5 : -bar - 0.5)}
                    y={top}
                    width={bar}
                    height={Math.max(1, MARGIN.top + tall - top)}
                    rx={Math.min(2, bar / 3)}
                    fill={one.color}
                  />
                )
              })
            )}

            {points.length ? (
              <path
                d={line}
                fill="none"
                stroke="var(--series-3)"
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ) : null}

            {points.length ? (
              <path
                d={spending}
                fill="none"
                stroke="var(--series-4)"
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ) : null}

            {hovered !== null && at ? (
              <>
                <circle
                  cx={x(hovered)}
                  cy={y(at.open, right)}
                  r={4}
                  fill="var(--series-3)"
                  className="stroke-card"
                  strokeWidth={2}
                />
                <circle
                  cx={x(hovered)}
                  cy={y(spent[hovered], dear)}
                  r={4}
                  fill="var(--series-4)"
                  className="stroke-card"
                  strokeWidth={2}
                />
              </>
            ) : null}
          </svg>
        ) : null}

        {hovered !== null && at ? (
          <div
            className="bg-popover text-popover-foreground pointer-events-none absolute top-1 z-10 min-w-32 rounded-md border px-2.5 py-1.5 text-xs shadow-md"
            style={x(hovered) > width / 2 ? { right: width - x(hovered) + slot / 2 + 6 } : { left: x(hovered) + slot / 2 + 6 }}
            data-slot="activity-tooltip"
          >
            <p className="text-muted-foreground mb-1 font-medium">{longDay(at)}</p>
            {series.map((one) => (
              <p key={one.key} className="flex items-center justify-between gap-3">
                <span className="inline-flex items-center gap-1.5">
                  <span className="size-2 rounded-full" style={{ background: one.color }} />
                  {one.label}
                </span>
                <span className="font-mono font-semibold tabular-nums">{one.format(one.value(at, hovered!))}</span>
              </p>
            ))}
          </div>
        ) : null}
      </div>

      {/* In a box of its own: a table does not shrink to the 1px `sr-only`
          gives it, and one as wide as its days pushed a phone's page sideways. */}
      <div className="sr-only">
        <table>
          <caption>{label}</caption>
          <thead>
            <tr>
              <th scope="col" />
              {series.map((one) => (
                <th key={one.key} scope="col">
                  {one.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {points.map((point, index) => (
              <tr key={index}>
                <th scope="row">{longDay(point)}</th>
                {series.map((one) => (
                  <td key={one.key}>{one.format(one.value(point, index))}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
