import Link from "next/link";

import { Card } from "@/components/ui/card";
import { DenseTable, DenseTd, DenseTh } from "@/components/ui/dense-table";
import { StatusPill, statusToneOf } from "@/components/ui/status-pill";
import { formatRelativeTr } from "@/lib/format";
import type { SignalOut } from "@/lib/types";

/**
 * The two of `/signals`' seven streams that have nowhere else to live on this
 * page.
 *
 * Of the seven: `kokpit` is Market Pulse's bands and Günün Özeti (sections 2
 * and 4); `campaign_alerts` and `risk` are the Alert Merkezi (section 9);
 * `network` and `momentum` are the Rekabet cells (section 7). That leaves
 * rival events and strategic developments, which appear nowhere else -- so
 * this board carries exactly those two and nothing else.
 *
 * Getting this filter wrong fails in one of two silent ways: too narrow and
 * the board is permanently empty, too wide and it reprints the alert centre
 * two sections above it. Hence the test.
 */
export const KOKPIT_STREAMS = new Set(["rival_events", "strategic"]);

const ROW_LIMIT = 6;

export function selectStreamSignals(rows: SignalOut[], limit = ROW_LIMIT): SignalOut[] {
  // The backend's own `sort_signals` ordering is preserved -- it ranks by
  // severity and recency together, and re-sorting here would silently disagree
  // with /sinyaller about which signal matters most.
  return rows.filter((row) => KOKPIT_STREAMS.has(row.stream)).slice(0, limit);
}

/**
 * SİNYAL PANOSU -- rival events and strategic developments, six rows.
 *
 * There is no YÖN (direction) column. The owner's sketch asked for one, but a
 * rival announcing a route or a regulator issuing a ruling has no direction:
 * `SignalOut` carries no such field, and deriving one from a headline would be
 * us inventing the most decision-relevant thing on the row. The column is TÜR
 * instead, filled from each stream's own vocabulary ("Yeni hat", "Stratejik").
 *
 * IT FETCHES NOTHING. `/signals` is read ONCE, on the server, in app/page.tsx,
 * and handed to this board, the Alert Merkezi and the Rekabet cells alike. It
 * used to fetch `/signals?days=30` for itself while the Alert Merkezi fetched
 * `/risks` and `/campaign-alerts` for the same rows -- three requests, three
 * runs of the same 14-day clustering, and two components free to disagree
 * about which four rows mattered most. There is one list on this page now, and
 * it is the list /sinyaller draws.
 *
 * This board is deliberately the HEAD of that list and says so: `total` is how
 * many rows the two streams produced, and the footer prints it whenever more
 * were produced than fit. A truncated board that stayed silent would read as
 * "these are all of them".
 */
export function SignalStream({ signals }: { signals: SignalOut[] }) {
  const all = signals.filter((row) => KOKPIT_STREAMS.has(row.stream));
  const rows = selectStreamSignals(signals);

  if (rows.length === 0) {
    return (
      // One line, not a padded panel. A section with nothing in it still says
      // so -- zero is a reading -- but it does not get to spend 50px doing it
      // while three sections below the fold are all saying the same thing.
      <p className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
        Rakip olayı veya stratejik gelişme sinyali yok.
      </p>
    );
  }

  return (
    <Card className="p-0">
      <div className="overflow-x-auto">
        <DenseTable>
          <thead>
            <tr>
              <DenseTh>Sinyal</DenseTh>
              <DenseTh className="hidden sm:table-cell">Tür</DenseTh>
              <DenseTh>Etki</DenseTh>
              <DenseTh>Zaman</DenseTh>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                title={row.severity_basis_tr}
                className="border-b border-border/60 last:border-0"
              >
                <DenseTd className="max-w-0">
                  {row.href ? (
                    <Link
                      href={row.href}
                      className="block truncate rounded font-medium hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                    >
                      {row.title_tr}
                    </Link>
                  ) : (
                    <span className="block truncate font-medium">{row.title_tr}</span>
                  )}
                </DenseTd>
                <DenseTd className="hidden text-muted-foreground sm:table-cell">
                  {row.type_label_tr}
                </DenseTd>
                <DenseTd>
                  <StatusPill tone={statusToneOf(row.severity)}>{row.severity_label_tr}</StatusPill>
                </DenseTd>
                <DenseTd className="whitespace-nowrap text-muted-foreground">
                  {/* Never defaulted to "now": an undated signal says so. */}
                  {row.detected_at ? formatRelativeTr(row.detected_at) : "—"}
                </DenseTd>
              </tr>
            ))}
          </tbody>
        </DenseTable>
      </div>
      {all.length > rows.length && (
        <p className="border-t border-border/60 px-3 py-1.5 text-[10px] text-muted-foreground">
          Bu iki akıştaki {all.length} sinyalden ilk {rows.length} tanesi.{" "}
          <Link
            href="/sinyaller"
            className="rounded font-medium underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Tümü Sinyaller’de →
          </Link>
        </p>
      )}
    </Card>
  );
}
