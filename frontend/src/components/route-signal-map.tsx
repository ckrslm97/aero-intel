"use client";

import ReactECharts from "echarts-for-react";
import { useReducedMotion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { baseOption, lineGlow, useChartTheme } from "@/lib/chart-theme";
import { ensureWorldMap, symbolSize } from "@/lib/echarts-world";
import { airlineTabs } from "@/lib/nav";
import type { RouteSignalArticle } from "@/lib/types";
import { cn } from "@/lib/utils";

/* ===========================================================================
 * Where the new competition is landing.
 *
 * This replaced a region donut. The donut said "Avrupa: 12" -- a number a bar
 * could carry, and one the chip row underneath already states. The question a
 * route-signal page is actually asked is *where*, and only a map answers it:
 * twelve European signals landing on Milan and Barcelona is a different piece
 * of news from twelve spread across twelve countries, and the donut renders
 * both identically.
 * ======================================================================== */

/** Where each carrier flies *from*, for the arc origins -- [lon, lat].
 *
 * A static table, and deliberately a short one. The backend emits the
 * *destination* airports a story names; it does not emit an origin, because a
 * route story does not reliably state one in a form the extractor can trust.
 * So an arc is only ever drawn for a carrier whose home base is a matter of
 * public record and is written down here. A carrier not in this table gets its
 * markers and no arcs -- the alternative is inventing an origin, which would
 * draw a confident line from a place the data never mentioned.
 */
const CARRIER_HUB: Record<string, { code: string; coord: [number, number] }> = {
  TK: { code: "IST", coord: [28.98, 41.01] },
  PC: { code: "SAW", coord: [29.31, 40.9] },
  VF: { code: "SAW", coord: [29.31, 40.9] },
  AF: { code: "CDG", coord: [2.55, 49.01] },
  BA: { code: "LHR", coord: [-0.45, 51.47] },
  EK: { code: "DXB", coord: [55.36, 25.25] },
  EY: { code: "AUH", coord: [54.65, 24.43] },
  KL: { code: "AMS", coord: [4.76, 52.31] },
  LH: { code: "FRA", coord: [8.57, 50.03] },
  QR: { code: "DOH", coord: [51.61, 25.27] },
};

const AIRLINE_BY_CODE = new Map(airlineTabs.map((a) => [a.code, a]));

/** The lit-chip pattern shared with the signal ledger below and with
 * Gazete/Öneriler. */
const chip = (active: boolean) =>
  cn(
    "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow-soft"
      : "border border-border text-muted-foreground hover:bg-accent",
  );

/* --- brand hex, made legible on this particular surface -------------------
 * The arc wears the carrier's own brand color, which is the point of it. But
 * several of those brands are navy at the bottom of the range -- Air France
 * #002157, Lufthansa #05164d -- and a navy hairline on the dark map's #1a1a19
 * landmass is not a subdued line, it is an invisible one. So the hue is kept
 * and only the lightness is moved, and only as far as it has to be: the
 * carrier is still recognisably itself, and the arc is still visible. Nothing
 * is adjusted when the brand already reads.
 */
/** Returns `#rrggbb`, not `rgb()`. The result is handed to `lineGlow`, which
 * runs it through `withAlpha` to build the dark-mode bloom, and `withAlpha`
 * parses hex -- an `rgb()` string produced `rgba(NaN, ...)` and silently cost
 * the glow. */
function mix(hex: string, target: number, amount: number): string {
  const n = parseInt(hex.replace("#", ""), 16);
  const channel = (shift: number) => {
    const c = (n >> shift) & 0xff;
    return Math.round(c + (target - c) * amount)
      .toString(16)
      .padStart(2, "0");
  };
  return `#${channel(16)}${channel(8)}${channel(0)}`;
}

function relativeLuminance(hex: string): number {
  const n = parseInt(hex.replace("#", ""), 16);
  const srgb = [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff].map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * srgb[0] + 0.7152 * srgb[1] + 0.0722 * srgb[2];
}

function readableBrand(hex: string, isDark: boolean): string {
  const luminance = relativeLuminance(hex);
  if (isDark && luminance < 0.16) return mix(hex, 255, 0.45);
  if (!isDark && luminance > 0.62) return mix(hex, 0, 0.3);
  return hex;
}

/** One destination, with every signal that landed on it folded together. */
interface Destination {
  code: string;
  city: string;
  country: string;
  lon: number;
  lat: number;
  count: number;
  carriers: string[];
}

interface RouteSignalMapProps {
  /** The unfiltered signal set -- the map is the overview, so it always shows
   * the whole month regardless of what the ledger below is filtered to. */
  signals: RouteSignalArticle[];
  /** Selected carrier: dims non-matching markers and draws that carrier's
   * arcs. Shared with the ledger's Havayolu filter, so the map's chip row and
   * the ledger's chip row are two affordances on one selection rather than
   * two competing ones. */
  carrier: string | null;
  onCarrierChange: (code: string | null) => void;
  /** Selected destination city, set by clicking a marker. */
  city: string | null;
  onCityChange: (city: string | null) => void;
}

export function RouteSignalMap({
  signals,
  carrier,
  onCarrierChange,
  city,
  onCityChange,
}: RouteSignalMapProps) {
  const [mapReady, setMapReady] = useState(false);
  const reduceMotion = useReducedMotion();
  const theme = useChartTheme();

  useEffect(() => {
    let active = true;
    ensureWorldMap().then(() => {
      if (active) setMapReady(true);
    });
    return () => {
      active = false;
    };
  }, []);

  const destinations = useMemo<Destination[]>(() => {
    const byCode = new Map<string, Destination & { carrierSet: Set<string> }>();
    for (const signal of signals) {
      for (const airport of signal.airports) {
        let entry = byCode.get(airport.code);
        if (!entry) {
          entry = {
            code: airport.code,
            city: airport.city,
            country: airport.country,
            lon: airport.lon,
            lat: airport.lat,
            count: 0,
            carriers: [],
            carrierSet: new Set<string>(),
          };
          byCode.set(airport.code, entry);
        }
        entry.count += 1;
        for (const code of signal.airlines) entry.carrierSet.add(code);
      }
    }
    return [...byCode.values()].map(({ carrierSet, ...rest }) => ({
      ...rest,
      carriers: [...carrierSet],
    }));
  }, [signals]);

  /** Only carriers that actually have a placed destination get a chip -- a
   * chip that dims every marker and draws nothing is a dead control. */
  const carriersOnMap = useMemo(() => {
    const counts = new Map<string, number>();
    for (const destination of destinations) {
      for (const code of destination.carriers) {
        counts.set(code, (counts.get(code) ?? 0) + 1);
      }
    }
    return airlineTabs
      .filter((a) => counts.has(a.code))
      .map((a) => ({ ...a, count: counts.get(a.code)! }));
  }, [destinations]);

  const option = useMemo(() => {
    const maxCount = Math.max(1, ...destinations.map((d) => d.count));
    const hub = carrier ? CARRIER_HUB[carrier] : undefined;
    const brand = carrier
      ? readableBrand(AIRLINE_BY_CODE.get(carrier)?.color ?? theme.primary, theme.isDark)
      : theme.primary;

    const points = destinations.map((destination) => {
      const matches = !carrier || destination.carriers.includes(carrier);
      const isSelected = city !== null && destination.city === city;
      return {
        name: destination.code,
        value: [destination.lon, destination.lat, destination.count],
        symbolSize: symbolSize(destination.count, maxCount),
        itemStyle: {
          color: theme.primary,
          opacity: matches ? 0.9 : 0.25,
          // A 2px ring in the surface color so overlapping destinations stay
          // countable; the selected one swaps that ring for the amber signal
          // accent, which is how a click reads back on the map.
          borderColor: isSelected ? theme.signal : theme.surface,
          borderWidth: isSelected ? 3 : 2,
        },
        destination,
      };
    });

    // Arcs from the selected carrier's hub to each place it is landing. The
    // hub's own marker is skipped: an arc from IST to IST is a dot, not a
    // route.
    const arcs =
      carrier && hub
        ? destinations
            .filter((d) => d.carriers.includes(carrier) && d.code !== hub.code)
            .map((d) => ({ coords: [hub.coord, [d.lon, d.lat]] }))
        : [];

    return {
      ...baseOption(theme, reduceMotion),
      backgroundColor: "transparent",
      tooltip: {
        ...baseOption(theme, reduceMotion).tooltip,
        trigger: "item",
        formatter: (params: { data?: { destination?: Destination } }) => {
          const destination = params.data?.destination;
          if (!destination) return "";
          const carriers = destination.carriers
            .map((code) => AIRLINE_BY_CODE.get(code)?.name ?? code)
            .join(", ");
          const head = `<b>${destination.city}</b> (${destination.code}) · ${destination.count} sinyal`;
          return carriers ? `${head}<br/>${carriers}` : head;
        },
      },
      geo: {
        map: "world",
        roam: true,
        center: [30, 25],
        zoom: 1.6,
        scaleLimit: { min: 1, max: 10 },
        label: { show: false },
        itemStyle: {
          areaColor: theme.isDark ? "#262624" : "#eceae2",
          borderColor: theme.surface,
          borderWidth: 0.6,
        },
        emphasis: {
          label: { show: false },
          itemStyle: { areaColor: theme.isDark ? "#33332f" : "#dcdacf" },
        },
        select: { disabled: true },
      },
      series: [
        {
          type: "lines",
          coordinateSystem: "geo",
          data: arcs,
          // Dark mode only for the bloom -- a glow on a near-white surface
          // reads as a printing error, not as light (see `lineGlow`).
          lineStyle: {
            ...lineGlow(brand, theme.isDark, 1.6),
            curveness: 0.3,
            opacity: 0.75,
          },
          // No `effect`: nothing on this page animates at idle. The arcs
          // arrive with ECharts' own data-change animation, which `baseOption`
          // already gates on reduced motion, and then they hold still.
          silent: true,
          zlevel: 1,
        },
        {
          type: "scatter",
          coordinateSystem: "geo",
          data: points,
          zlevel: 2,
        },
      ],
    };
  }, [destinations, carrier, city, theme, reduceMotion]);

  if (destinations.length === 0) {
    return (
      <div className="flex h-[360px] flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-border p-6 text-center">
        <p className="text-sm text-muted-foreground">
          Haritaya yerleştirilebilecek hat sinyali yok.
        </p>
        <p className="text-xs text-muted-foreground">
          Sinyaller yakalandı ama hiçbirinde tanınan bir havalimanı geçmiyor — aşağıdaki
          çözümlenemeyen sinyaller bölümüne bakın.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="w-16 shrink-0 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Taşıyıcı
        </span>
        <button type="button" onClick={() => onCarrierChange(null)} className={chip(!carrier)}>
          Tümü
        </button>
        {carriersOnMap.map((a) => (
          <button
            key={a.code}
            type="button"
            title={
              CARRIER_HUB[a.code]
                ? `${a.name} — ${CARRIER_HUB[a.code].code} hattından`
                : `${a.name} — ana üs kayıtlı değil, yay çizilmez`
            }
            onClick={() => onCarrierChange(carrier === a.code ? null : a.code)}
            className={cn(chip(carrier === a.code), "flex items-center gap-1 tabular-nums")}
          >
            <span
              className={cn(
                "flex size-4 items-center justify-center overflow-hidden rounded-[3px]",
                carrier === a.code && "bg-white/85",
              )}
            >
              <AirlineLogo code={a.code} name={a.name} className="size-4" />
            </span>
            {a.code}
            <span className="opacity-70">{a.count}</span>
          </button>
        ))}
      </div>

      {mapReady ? (
        <div className="rounded-xl border border-border bg-card p-2">
          <ReactECharts
            option={option}
            style={{ height: 360, width: "100%" }}
            // Canvas, not SVG: the world polygon set is heavy for the DOM.
            opts={{ renderer: "canvas" }}
            notMerge
            onEvents={{
              click: (params: { data?: { destination?: Destination } }) => {
                const clicked = params.data?.destination?.city;
                if (clicked) onCityChange(clicked === city ? null : clicked);
              },
            }}
          />
        </div>
      ) : (
        <div className="flex h-[360px] items-center justify-center rounded-xl border border-border bg-card">
          <span className="text-xs text-muted-foreground">Harita yükleniyor…</span>
        </div>
      )}

      <p className="px-1 text-[11px]" style={{ color: theme.ink }}>
        Nokta büyüklüğü o şehre inen sinyal sayısıdır; tıklayınca aşağıdaki defter o şehre
        iner. Bir taşıyıcı seçin: kendi ana üssünden indiği şehirlere kendi renginde yaylar
        çizilir. Ana üssü tabloda kayıtlı olmayan taşıyıcıların yayı çizilmez.
      </p>
    </div>
  );
}
