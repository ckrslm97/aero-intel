import { campaignRouteLabel } from "@/lib/campaigns";
import type { PromotionOut } from "@/lib/types";

/** The five numbers at the top of the page.
 *
 * Deliberately NOT KPI cards. The house KPI card carries a delta, a sparkline
 * and a shadow, and five of them across the top of a page would be the first
 * 200 pixels of a page whose whole brief is "the reader understands a campaign
 * in three to five seconds". This is one hairline-divided band: label, number,
 * nothing else, no colour, no icon.
 *
 * Every number is computed over the CURRENTLY VISIBLE set, filters included.
 * A summary that kept reporting the unfiltered totals while the list under it
 * showed nine rows would be the page contradicting itself, and the reader
 * would have to guess which half to believe.
 */
export interface CampaignSummaryCounts {
  active: number;
  upcoming: number;
  /** NULL WHEN `/promotions/expiring` DID NOT ANSWER, and that is the whole
   * reason this field is nullable while the other four are not. The four are
   * computed from rows already on screen, so they cannot fail independently;
   * this one is its own request. Caught into `[]`, its failure printed
   * "Bitmek üzere: 0" -- a revenue desk being told that nothing closes this
   * week by the one number on the page whose entire job is urgency. */
  expiring: number | null;
  carriers: number;
  routes: number;
}

/** ROUTES counts distinct route LABELS, not distinct OND pairs.
 *
 * An OND-only count would read 2 on a day when eleven carriers each announced
 * a network-wide sale, because `ond` is null on every one of them. The label
 * is what the reader sees in the rows, so counting labels is the only count
 * whose number they can go and verify. "—" (no route stated at all) is not a
 * route and is not counted. */
export function summarise(
  rows: readonly PromotionOut[],
  /** The expiring rows, or `null` when that source could not be read. */
  expiring: readonly PromotionOut[] | null,
): CampaignSummaryCounts {
  const carriers = new Set<string>();
  const routes = new Set<string>();
  let active = 0;
  let upcoming = 0;
  for (const promo of rows) {
    carriers.add(promo.airline_code);
    const route = campaignRouteLabel(promo);
    if (route !== "—") routes.add(route);
    if (promo.status === "ACTIVE_BOOKING") active += 1;
    if (promo.status === "UPCOMING") upcoming += 1;
  }
  return {
    active,
    upcoming,
    expiring: expiring === null ? null : expiring.length,
    carriers: carriers.size,
    routes: routes.size,
  };
}

export function CampaignSummary({
  counts,
  filtered,
}: {
  counts: CampaignSummaryCounts;
  /** Whether any filter is lit, so the band can say what it is counting. */
  filtered: boolean;
}) {
  const items: { label: string; value: number | null; hint: string }[] = [
    {
      label: "Satıştaki kampanya",
      value: counts.active,
      hint: "Bugün bilet alınabilen kampanyalar",
    },
    { label: "Yakında", value: counts.upcoming, hint: "Duyuruldu, satışı henüz açılmadı" },
    {
      label: "Bitmek üzere",
      value: counts.expiring,
      hint:
        counts.expiring === null
          ? "Bu sayaç okunamadı — bu hafta kapanan kampanya olmadığı anlamına gelmez"
          : "Satışı 7 gün içinde kapanacak kampanyalar",
    },
    { label: "Taşıyıcı", value: counts.carriers, hint: "Listede kampanyası olan havayolu" },
    {
      label: "Rota / pazar",
      value: counts.routes,
      hint: "Listedeki farklı rota ve pazar tanımı",
    },
  ];

  // The hairlines are a `bg-border` grid gap showing between `bg-card` cells,
  // which costs no extra element -- but it also means an EMPTY cell renders as
  // a grey block. Five items into two or three columns always leaves one, so
  // the last item spans the remainder and every row is full at every width.
  return (
    <dl
      aria-label={filtered ? "Seçili filtrelerin özeti" : "Kampanya özeti"}
      className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border [&>*:last-child]:col-span-2 sm:grid-cols-3 lg:grid-cols-5 lg:[&>*:last-child]:col-span-1"
    >
      {items.map((item) => (
        <div key={item.label} title={item.hint} className="flex flex-col gap-0.5 bg-card px-3 py-2">
          <dt className="truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {item.label}
          </dt>
          {/* A count, or the word for "we did not read it". Never a zero
              standing in for the second one: on this band zero is an
              instruction to stop worrying. */}
          {item.value === null ? (
            <dd className="text-xs font-semibold leading-none text-warning">okunamadı</dd>
          ) : (
            <dd className="text-xl font-semibold leading-none tabular-nums">{item.value}</dd>
          )}
        </div>
      ))}
    </dl>
  );
}

/** Kept next to the band it describes: the caption under it changes with the
 * filter state, and the two must not drift apart. */
export function summaryCaption(filtered: boolean, total: number): string {
  return filtered
    ? `Seçili filtrelerle ${total} kampanya`
    : `Süresi dolmuş kampanyalar hariç, yayımlanabilir ${total} kampanya`;
}
