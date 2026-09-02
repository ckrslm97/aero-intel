import Link from "next/link";

import { MotionRail } from "@/components/motion/motion-list";

/** The one section heading Kokpit uses, so eleven sections don't each invent
 * their own rhythm.
 *
 * Deliberately a server component: it is a heading, a rail and an optional
 * link, and making it a client component would have pulled every section of
 * the page across the boundary for nothing. `MotionRail` is the only client
 * piece and it crosses on its own.
 */
export function SectionHeader({
  title,
  caption,
  glowVar = "var(--primary)",
  action,
}: {
  title: string;
  /** The scope/provenance line. Printed under the title rather than in a
   * tooltip: a caveat a reader has to hover to find is not a caveat. */
  caption?: string;
  glowVar?: string;
  action?: { href: string; label: string };
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          {title}
        </h2>
        {action && (
          <Link
            href={action.href}
            className="rounded text-xs font-medium text-muted-foreground underline-offset-2 transition-colors hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {action.label} →
          </Link>
        )}
      </div>
      <MotionRail style={{ "--glow-color": glowVar } as React.CSSProperties} />
      {caption && <p className="text-[10px] leading-relaxed text-muted-foreground">{caption}</p>}
    </div>
  );
}
