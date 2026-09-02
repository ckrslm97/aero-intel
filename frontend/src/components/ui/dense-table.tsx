import { cn } from "@/lib/utils";

/**
 * The 28px table row.
 *
 * Kokpit's existing tables run `px-3 py-2.5` -- a 38px row, which is right for
 * a page whose job is one table, and wrong for an executive board where the FX
 * table has to fit nine rows inside the fold alongside four other sections.
 * This is that same table at the density the fold contract (see app/page.tsx)
 * is arithmetically built on.
 *
 * The header is `sticky top-0`, WHICH DOES NOTHING ON A PAGE SCROLL and is not
 * meant to. Sticky positions against the nearest scrolling ancestor, and both
 * current callers wrap this in `<Card className="p-0">` (overflow-hidden) with
 * an `overflow-x-auto` div inside -- a box whose height is its content's, so
 * it never scrolls vertically and the header never lifts. It is kept for the
 * caller that gives its scroll box a `max-height`: at that point the header
 * does stick, and `bg-card/95 backdrop-blur` (rather than an opaque fill, which
 * would cut a seam across the card's `bg-card-sheen`) is what makes it legible
 * over the rows sliding under it. If you are reading this because you expected
 * a page-scroll sticky header, the fix is a `max-h-… overflow-auto` on the
 * wrapper, not a change here.
 *
 * NOTE FOR THE CALLER: `Card` carries `overflow-hidden`, so a table that needs
 * to scroll must be wrapped in `<Card className="p-0">` with its own
 * `overflow-x-auto` div inside -- the pattern campaign-analyst-table.tsx uses.
 */
export function DenseTable({
  children,
  className,
  ...props
}: React.ComponentProps<"table">) {
  return (
    <table className={cn("w-full text-xs", className)} {...props}>
      {children}
    </table>
  );
}

export function DenseTh({
  children,
  numeric = false,
  className,
  ...props
}: React.ComponentProps<"th"> & { numeric?: boolean }) {
  return (
    <th
      scope="col"
      className={cn(
        "sticky top-0 z-10 bg-card/95 px-3 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground backdrop-blur",
        numeric && "text-right",
        className,
      )}
      {...props}
    >
      {children}
    </th>
  );
}

export function DenseTd({
  children,
  numeric = false,
  className,
  ...props
}: React.ComponentProps<"td"> & { numeric?: boolean }) {
  return (
    <td
      className={cn(
        "px-3 py-1.5 align-middle",
        // Monospace ONLY inside a column: at 13px in a column the figures line
        // up and scan vertically, which is the whole point. The same face at
        // 26px in a Market Pulse cell reads as source code rather than as an
        // instrument, which is why N1 is not mono.
        numeric && "text-right font-mono tabular-nums",
        className,
      )}
      {...props}
    >
      {children}
    </td>
  );
}
