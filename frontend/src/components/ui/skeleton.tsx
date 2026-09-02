import { cn } from "@/lib/utils"

/** The loading placeholder.
 *
 * The pulse is INFINITE, and deliberately so, but it is now guarded. On this
 * product an empty section and a loading section say two different things --
 * "the stream answered and had nothing" versus "we have not asked yet" -- and
 * several Kokpit surfaces are legitimately empty on a quiet day. A static grey
 * block would make those two states pixel-identical, which is the one thing
 * the page's honesty contract cannot afford. So the motion stays as the signal
 * that a request is still in flight.
 *
 * What was wrong was that it kept looping for a reader who had asked the OS to
 * stop motion: Tailwind's stock `animate-pulse` carries no reduced-motion
 * guard, unlike this repo's own `animate-pulse-once`. The net now lives in
 * globals.css and covers `animate-pulse` and `animate-spin` alike, so under
 * `prefers-reduced-motion: reduce` this renders as a still block.
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      role="status"
      aria-label="Yükleniyor"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  )
}

export { Skeleton }
