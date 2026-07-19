/** Stylized airline tail fins for the Gazete's carrier filter chips.
 *
 * Deliberately NOT the airlines' actual logos (those are trademarked
 * artwork): one original swept-fin shape, colored with each carrier's brand
 * color identity plus an accent band, which is enough for at-a-glance
 * recognition next to the IATA code.
 */

interface TailColors {
  fin: string;
  accent: string;
}

// fin = the carrier's primary brand color (matches nav.ts airlineTabs);
// accent = the secondary color the livery is known for.
const TAILS: Record<string, TailColors> = {
  TK: { fin: "#c70a20", accent: "#ffffff" },
  AF: { fin: "#002157", accent: "#e2231a" },
  BA: { fin: "#075aaa", accent: "#e2231a" },
  EK: { fin: "#d71921", accent: "#ffffff" },
  EY: { fin: "#bd8b13", accent: "#ffffff" },
  KL: { fin: "#00a1de", accent: "#ffffff" },
  LH: { fin: "#05164d", accent: "#f9ba00" },
  QR: { fin: "#5c0632", accent: "#ffffff" },
  PC: { fin: "#fdb913", accent: "#e2231a" },
  VF: { fin: "#f26722", accent: "#ffffff" },
};

export function TailIcon({ code, className }: { code: string; className?: string }) {
  const colors = TAILS[code] ?? { fin: "currentColor", accent: "transparent" };
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      style={{ display: "block" }}
    >
      {/* Swept vertical stabilizer with a short fuselage stub */}
      <path
        d="M3 21 L11 4 Q12 2.2 14.4 2.2 L17.5 2.2 Q16.6 9 14.2 15.5 L21 15.5 Q22 15.5 22 16.7 Q22 21 17 21 Z"
        fill={colors.fin}
      />
      {/* Accent band across the fin */}
      <path
        d="M8.1 10.2 L16.2 10.2 Q15.9 11.4 15.5 12.6 L7 12.6 Z"
        fill={colors.accent}
        opacity="0.9"
      />
    </svg>
  );
}
