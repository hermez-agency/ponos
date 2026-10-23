import { cn } from "@/lib/utils"

/** A thin bar: `value` is a percentage, or absent when no length is known — then it only moves. */
function Progress({
  value,
  className,
  ...props
}: Omit<React.ComponentProps<"div">, "children"> & { value?: number }) {
  const known = typeof value === "number"
  return (
    <div
      data-slot="progress"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={known ? value : undefined}
      className={cn("bg-muted relative h-1.5 w-full overflow-hidden rounded-full", className)}
      {...props}
    >
      <div
        data-slot="progress-indicator"
        className={cn(
          "bg-tr-green h-full rounded-full",
          known
            ? "transition-[width] duration-500"
            : "w-2/5 animate-indeterminate motion-reduce:animate-none"
        )}
        style={known ? { width: `${Math.min(100, Math.max(0, value))}%` } : undefined}
      />
    </div>
  )
}

export { Progress }
