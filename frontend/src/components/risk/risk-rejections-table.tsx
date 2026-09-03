"use client";

import { ExternalLink } from "lucide-react";

import { Card } from "@/components/ui/card";
import { DenseTable, DenseTd, DenseTh } from "@/components/ui/dense-table";
import { relativeTimeTr } from "@/lib/campaigns";
import {
  confidenceGateLabel,
  rejectionPlaceLabel,
  riskSourceTierLabel,
  scoreOrUnscored,
} from "@/lib/risk";
import type { RiskRejection } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Fixed widths, and the table scrolls horizontally rather than reflowing --
 * the same rule campaign-analyst-table.tsx follows. An analyst's table that
 * rewraps at every breakpoint cannot be scanned down a column, which is the
 * only reason to render one.
 *
 * The three score columns sit adjacent on purpose: a reader diagnosing "why is
 * this not on the radar" reads across them, and "ölçülmedi" in one of them is
 * the answer more often than a low number in another. */
const HEADERS: { label: string; numeric?: boolean; width: string; title?: string }[] = [
  { label: "Başlık", width: "w-[20rem]" },
  { label: "Kaynak", width: "w-[8rem]" },
  { label: "Yayın", width: "w-[5.5rem]" },
  { label: "Sebep", width: "w-[9rem]" },
  {
    label: "Güven",
    numeric: true,
    width: "w-[5rem]",
    title: "Çapraz kaynak doğrulama skoru (0-1). Eşik: 0.60",
  },
  {
    label: "Havacılık",
    numeric: true,
    width: "w-[5.5rem]",
    title: "Operasyonel havacılık ilgisi (0-1). Eşik: 0.70",
  },
  { label: "Konum", width: "w-[11rem]", title: "Tespit edilen yer ve konum güveni. İğne eşiği: 0.70" },
  { label: "Anılan yerler", width: "w-[13rem]" },
];

/** The rejected candidates, one row each, with the values the rule read.
 *
 * WHY THE NUMBERS ARE IN THE TABLE and not behind a click: a row that says
 * "havacılıkla ilgisiz" and nothing else asks the reader to trust the label,
 * which is the exact failure this whole revision exists to fix. The score, the
 * placement and the places the article named are what let them disagree with
 * it.
 *
 * `mentioned_locations` carries the role each place played, and the role is
 * the point -- "United States (source)" beside a story about Japan is the
 * Washington/Japan bug rendered legible. Without it, "konum doğrulanamadı" is
 * unanswerable and a correct refusal cannot be told from a broken resolver.
 */
export function RiskRejectionsTable({ rows }: { rows: readonly RiskRejection[] }) {
  return (
    <Card size="sm" className="p-0">
      <div className="overflow-x-auto">
        <DenseTable className="min-w-[78rem] table-fixed">
          <thead>
            <tr className="border-b border-border">
              {HEADERS.map((header) => (
                <DenseTh
                  key={header.label}
                  numeric={header.numeric}
                  title={header.title}
                  className={header.width}
                >
                  {header.label}
                </DenseTh>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {rows.map((row) => (
              <Row key={`${row.article_id}-${row.reason}`} row={row} />
            ))}
          </tbody>
        </DenseTable>
      </div>
    </Card>
  );
}

function Row({ row }: { row: RiskRejection }) {
  return (
    <tr className="align-top transition-colors hover:bg-accent/60">
      <DenseTd>
        <a
          href={row.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-start gap-1 text-xs leading-snug hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <span className="line-clamp-2">{row.title}</span>
          <ExternalLink className="mt-0.5 size-2.5 shrink-0 opacity-60" aria-hidden />
        </a>
        {row.risk_type && (
          <span className="mt-0.5 block text-[10px] text-muted-foreground">
            {row.risk_type}
            {row.risk_severity ? ` · ${row.risk_severity}` : ""}
          </span>
        )}
      </DenseTd>

      <DenseTd>
        <span className="block truncate text-[11px]">{row.source_name || "—"}</span>
        <span className="text-[10px] text-muted-foreground">
          {riskSourceTierLabel(row.source_tier)}
        </span>
      </DenseTd>

      <DenseTd>
        {/* Relative, not absolute: on this screen the publication date only
            ever answers "is this inside the window", and "6 gün önce" answers
            it without the reader doing arithmetic against today. */}
        <span className="text-[11px] text-muted-foreground">
          {row.published_at ? relativeTimeTr(row.published_at) : "—"}
        </span>
      </DenseTd>

      <DenseTd>
        <span className="inline-flex w-fit rounded-full border border-critical/40 bg-critical/10 px-1.5 py-px text-[10px] font-medium text-critical">
          {row.reason_label_tr}
        </span>
        {/* The other gates it would ALSO have failed. Empty is the good case:
            fix the one rule and the article appears. Saying nothing here would
            let a reader fix the named reason and watch the row stay hidden. */}
        {row.also_failed.length > 0 && (
          <span
            className="mt-0.5 block text-[10px] leading-relaxed text-muted-foreground"
            title="Bu satır aşağıdaki kapılarda da elenirdi; sebep sütunu yalnızca İLK kapıyı gösterir."
          >
            + {row.also_failed.join(", ")}
          </span>
        )}
      </DenseTd>

      <DenseTd numeric>
        <Score value={row.confidence_score} threshold={0.6} />
        {/* The gate's own verdict, under its number -- the same pairing the
            aviation column uses. A blank score beside a passing gate reads as
            "measured and fine"; it usually means the gate declined to judge an
            unmeasured row, and that is a different piece of work. */}
        <span className="mt-0.5 block text-[10px] font-normal text-muted-foreground">
          {confidenceGateLabel(row.confidence_gate_reason)}
        </span>
      </DenseTd>

      <DenseTd numeric>
        <Score value={row.aviation_relevance_score} threshold={0.7} />
        {row.aviation_relevance_source && (
          <span className="mt-0.5 block text-[10px] font-normal text-muted-foreground">
            {row.aviation_relevance_source}
          </span>
        )}
      </DenseTd>

      <DenseTd>
        <span className="text-[11px]">{rejectionPlaceLabel(row)}</span>
      </DenseTd>

      <DenseTd>
        {row.mentioned_locations.length === 0 ? (
          <span className="text-[11px] text-muted-foreground">—</span>
        ) : (
          <span className="flex flex-wrap gap-1">
            {row.mentioned_locations.map((mention) => (
              <span
                key={`${mention.name}-${mention.kind}`}
                title={`${mention.kind} · ${mention.role}`}
                className={cn(
                  "rounded border px-1 text-[10px]",
                  mention.role === "event"
                    ? "border-border text-foreground"
                    : "border-dashed border-border text-muted-foreground",
                )}
              >
                {mention.name}
                <span className="opacity-60"> · {mention.role}</span>
              </span>
            ))}
          </span>
        )}
      </DenseTd>
    </tr>
  );
}

/** A score against the gate it was judged by.
 *
 * Null renders as "ölçülmedi" and never as 0.00: the three gates publish
 * unscored rows on purpose, and a table that draws "nobody measured this" and
 * "measured, scored zero" identically re-creates on screen the exact bug the
 * backend spent a phase removing. */
function Score({ value, threshold }: { value: number | null; threshold: number }) {
  if (value === null) {
    return <span className="text-[10px] font-normal text-muted-foreground">ölçülmedi</span>;
  }
  return (
    <span
      className={cn("text-[11px] tabular-nums", value < threshold && "text-critical")}
      title={`Eşik: ${threshold.toFixed(2)}`}
    >
      {scoreOrUnscored(value)}
    </span>
  );
}
