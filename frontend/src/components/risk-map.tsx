"use client";

import ReactECharts from "echarts-for-react";
import { useEffect, useMemo, useState } from "react";

import { RiskMapPopover, type MapAnchor } from "@/components/risk/risk-map-popover";
import { useChartTheme, withAlpha } from "@/lib/chart-theme";
import { ensureWorldMap } from "@/lib/echarts-world";
import { GEO_FEATURE_BY_COUNTRY } from "@/lib/geo/risk-country-shapes";
import type { RiskCountry, RiskItem } from "@/lib/types";

/** Country centroids for the countries this classifier can actually name --
 * every key of backend COUNTRY_TO_REGION (50 entries), plus the handful of
 * others the LLM path can return. Approximate population-weighted centres, not
 * geometric ones: a marker on Turkey should sit near Ankara, not in the middle
 * of the Anatolian plateau. Used only when a city is unknown; a known city
 * beats a centroid every time (see CITY_COORDS).
 *
 * Centroids are ALL this page has. There are no event coordinates anywhere in
 * the pipeline -- the classifier resolves a place NAME, never a location -- so
 * a marker means "somewhere in this country/city", and the footnote under the
 * map says exactly that rather than letting the pin imply precision. */
const COUNTRY_COORDS: Record<string, [number, number]> = {
  turkey: [35.24, 39.06], "united kingdom": [-1.55, 52.36], france: [2.35, 46.6],
  germany: [10.45, 51.17], spain: [-3.7, 40.2], italy: [12.57, 42.5],
  netherlands: [5.29, 52.13], russia: [55.0, 57.0], greece: [22.0, 39.07],
  portugal: [-8.22, 39.4], switzerland: [8.23, 46.82], austria: [14.55, 47.52],
  belgium: [4.47, 50.5], poland: [19.15, 51.92], sweden: [16.32, 60.13],
  norway: [10.75, 61.5], denmark: [10.0, 56.0], finland: [25.75, 62.0],
  ireland: [-8.24, 53.41], iceland: [-19.02, 64.96],
  qatar: [51.18, 25.35], "united arab emirates": [54.0, 24.3],
  "saudi arabia": [45.08, 24.0], israel: [34.85, 31.5],
  egypt: [30.8, 27.0], "south africa": [24.0, -29.0], nigeria: [8.68, 9.08],
  kenya: [37.9, -0.02], morocco: [-7.09, 31.79],
  "united states": [-98.5, 39.0], canada: [-96.0, 56.0],
  mexico: [-102.55, 23.63], panama: [-80.78, 8.54], "costa rica": [-84.09, 9.75],
  brazil: [-51.93, -14.24], argentina: [-63.62, -38.42], chile: [-71.54, -35.68],
  colombia: [-74.3, 4.57], peru: [-75.02, -9.19], ecuador: [-78.18, -1.83],
  china: [104.2, 35.86], japan: [138.25, 36.2], "south korea": [127.77, 35.91],
  india: [78.96, 20.59],
  indonesia: [113.92, -0.79], thailand: [100.99, 15.87], vietnam: [108.28, 14.06],
  philippines: [121.77, 12.88], singapore: [103.82, 1.35],
  australia: [133.78, -25.27], "new zealand": [174.89, -40.9],
  // Countries the LLM path can name that the region table does not cover.
  ukraine: [31.17, 48.38], iran: [53.69, 32.43], iraq: [43.68, 33.22],
  syria: [39.0, 34.8], lebanon: [35.86, 33.85], jordan: [36.24, 30.59],
  pakistan: [69.35, 30.38], bangladesh: [90.36, 23.68], nepal: [84.12, 28.39],
  myanmar: [95.96, 21.91], malaysia: [101.98, 4.21], taiwan: [120.96, 23.7],
  venezuela: [-66.59, 6.42], bolivia: [-63.59, -16.29], guatemala: [-90.23, 15.78],
  haiti: [-72.29, 18.97], cuba: [-77.78, 21.52], algeria: [1.66, 28.03],
  tunisia: [9.54, 33.89], libya: [17.23, 26.34], ethiopia: [40.49, 9.15],
  sudan: [30.22, 12.86], croatia: [15.2, 45.1], serbia: [21.0, 44.02],
  romania: [24.97, 45.94], bulgaria: [25.49, 42.73], hungary: [19.5, 47.16],
  "czech republic": [15.47, 49.82], slovakia: [19.7, 48.67], lithuania: [23.88, 55.17],
  latvia: [24.6, 56.88], estonia: [25.01, 58.6], cyprus: [33.43, 35.13],
  azerbaijan: [47.58, 40.14], georgia: [43.36, 42.32], kazakhstan: [66.92, 48.02],
  uzbekistan: [64.59, 41.38], afghanistan: [67.71, 33.94], "sri lanka": [80.77, 7.87],
  "new caledonia": [165.62, -20.9], fiji: [178.07, -17.71],
};

/** Cities the backend gazetteer can name (app/llm/gazetteer.py
 * RISK_CITY_COUNTRY, 134 entries) plus a few the LLM path returns. Only the
 * ones likely to carry a risk event are listed -- an unlisted city falls back
 * to its country's centroid rather than dropping the marker. */
const CITY_COORDS: Record<string, [number, number]> = {
  istanbul: [28.98, 41.01], ankara: [32.85, 39.93], izmir: [27.14, 38.42],
  antalya: [30.71, 36.9], adana: [35.33, 37.0], kahramanmaras: [36.94, 37.58],
  hatay: [36.16, 36.2], gaziantep: [37.38, 37.07], bodrum: [27.43, 37.03],
  mugla: [28.36, 37.22], canakkale: [26.41, 40.15],
  london: [-0.13, 51.51], manchester: [-2.24, 53.48], edinburgh: [-3.19, 55.95],
  paris: [2.35, 48.86], marseille: [5.37, 43.3], lyon: [4.84, 45.76],
  berlin: [13.4, 52.52], munich: [11.58, 48.14], hamburg: [9.99, 53.55],
  madrid: [-3.7, 40.42], barcelona: [2.17, 41.39], seville: [-5.98, 37.39],
  rome: [12.5, 41.9], milan: [9.19, 45.46], naples: [14.27, 40.85],
  catania: [15.09, 37.5], amsterdam: [4.9, 52.37], brussels: [4.35, 50.85],
  vienna: [16.37, 48.21], zurich: [8.54, 47.38], geneva: [6.14, 46.2],
  lisbon: [-9.14, 38.72], porto: [-8.61, 41.15], athens: [23.73, 37.98],
  thessaloniki: [22.94, 40.64], rhodes: [28.22, 36.43], crete: [24.81, 35.24],
  warsaw: [21.01, 52.23], krakow: [19.94, 50.06], stockholm: [18.07, 59.33],
  oslo: [10.75, 59.91], copenhagen: [12.57, 55.68], helsinki: [24.94, 60.17],
  dublin: [-6.26, 53.35], reykjavik: [-21.83, 64.13], moscow: [37.62, 55.76],
  "st petersburg": [30.34, 59.93],
  dubai: [55.27, 25.2], "abu dhabi": [54.37, 24.45], doha: [51.53, 25.29],
  riyadh: [46.68, 24.71], jeddah: [39.2, 21.49], "tel aviv": [34.78, 32.09],
  jerusalem: [35.22, 31.77],
  cairo: [31.24, 30.04], alexandria: [29.92, 31.2], "sharm el sheikh": [34.33, 27.92],
  hurghada: [33.81, 27.26], johannesburg: [28.05, -26.2], "cape town": [18.42, -33.92],
  durban: [31.02, -29.86], lagos: [3.38, 6.52], abuja: [7.49, 9.06],
  nairobi: [36.82, -1.29], casablanca: [-7.59, 33.57], marrakech: [-7.98, 31.63],
  "new york": [-74.01, 40.71], "los angeles": [-118.24, 34.05], chicago: [-87.63, 41.88],
  miami: [-80.19, 25.76], houston: [-95.37, 29.76], dallas: [-96.8, 32.78],
  "san francisco": [-122.42, 37.77], seattle: [-122.33, 47.61], boston: [-71.06, 42.36],
  denver: [-104.99, 39.74], atlanta: [-84.39, 33.75], "new orleans": [-90.07, 29.95],
  toronto: [-79.38, 43.65], vancouver: [-123.12, 49.28], montreal: [-73.57, 45.5],
  calgary: [-114.07, 51.05], "mexico city": [-99.13, 19.43], cancun: [-86.85, 21.16],
  acapulco: [-99.82, 16.85], "panama city": [-79.52, 8.98],
  "sao paulo": [-46.63, -23.55], "rio de janeiro": [-43.17, -22.91],
  brasilia: [-47.88, -15.79], "porto alegre": [-51.23, -30.03],
  "buenos aires": [-58.38, -34.6], bogota: [-74.07, 4.71], medellin: [-75.56, 6.24],
  cali: [-76.52, 3.44], lima: [-77.04, -12.05], quito: [-78.47, -0.18],
  guayaquil: [-79.9, -2.19],
  beijing: [116.41, 39.9], shanghai: [121.47, 31.23], guangzhou: [113.26, 23.13],
  shenzhen: [114.06, 22.54], "hong kong": [114.17, 22.32], tokyo: [139.69, 35.69],
  osaka: [135.5, 34.69], sendai: [140.87, 38.27], fukuoka: [130.4, 33.59],
  seoul: [126.98, 37.57], busan: [129.08, 35.18], delhi: [77.21, 28.61],
  "new delhi": [77.21, 28.61], mumbai: [72.88, 19.08], chennai: [80.27, 13.08],
  kolkata: [88.36, 22.57], bengaluru: [77.59, 12.97], jakarta: [106.85, -6.21],
  bali: [115.19, -8.41], denpasar: [115.22, -8.65], surabaya: [112.75, -7.26],
  bangkok: [100.5, 13.76], phuket: [98.34, 7.88], "chiang mai": [98.98, 18.79],
  hanoi: [105.83, 21.03], "ho chi minh city": [106.63, 10.82], "da nang": [108.22, 16.05],
  manila: [120.98, 14.6], cebu: [123.89, 10.32], sydney: [151.21, -33.87],
  melbourne: [144.96, -37.81], brisbane: [153.03, -27.47], perth: [115.86, -31.95],
  adelaide: [138.6, -34.93], auckland: [174.76, -36.85], christchurch: [172.64, -43.53],
  wellington: [174.78, -41.29],
  kyiv: [30.52, 50.45], tehran: [51.39, 35.69], beirut: [35.5, 33.89],
  damascus: [36.29, 33.51], baghdad: [44.36, 33.31], flores: [121.0, -8.65],
};

const MIN_SYMBOL = 8;
const MAX_SYMBOL = 26;

/** Area, not radius, tracks count -- same rule as hub-map.tsx. Radius scaling
 * would make four articles look sixteen times worse than one, which on a
 * disaster page is not a rounding error but a lie. */
function symbolSize(count: number, max: number): number {
  if (max <= 0 || count <= 0) return MIN_SYMBOL;
  const area = (count / max) * (MAX_SYMBOL ** 2 - MIN_SYMBOL ** 2) + MIN_SYMBOL ** 2;
  return Math.sqrt(area);
}

const SEVERITY_WORD: Record<string, string> = {
  high: "Yüksek",
  medium: "Orta",
  low: "Düşük",
};

/** Four steps, not a continuous ramp.
 *
 * A continuous fill invites a reader to compare two countries that differ by
 * one low-severity article, which this data cannot support -- the underlying
 * number is a small integer sum of 3/2/1 weights over a news feed. Four buckets
 * say "more than / less than" and refuse to say more.
 *
 * The alphas top out well below opaque on purpose. A choropleth rewards
 * AREA, so Russia and Canada dominate the frame whatever their score is, and a
 * saturated top step turned the whole map into an alarm -- against this page's
 * own rule that the only loud things on screen are the few markers and cards
 * that earn it. Four steps that stay legible against both base fills, and the
 * markers still read on top of the darkest one. */
const FILL_STEPS = [0.08, 0.16, 0.26, 0.38];

interface MarkerBucket {
  lon: number;
  lat: number;
  family: string;
  country: string;
  city: string | null;
  typeLabel: string;
  severity: string;
  items: RiskItem[];
}

interface RiskPoint {
  name: string;
  value: [number, number, number];
  symbolSize: number;
  itemStyle: { color: string; opacity: number; borderColor: string; borderWidth: number };
  meta: { key: string; country: string; city: string | null; typeLabel: string; severity: string; count: number };
}

interface RiskMapProps {
  countries: RiskCountry[];
  selectedCountry: string | null;
  onSelectCountry: (country: string | null) => void;
  /** Opening one signal from a marker's popover. The map never renders the
   * detail itself -- it hands the item back and the page opens its drawer. */
  onOpenItem: (item: RiskItem) => void;
}

/**
 * Where the classified events are. Deliberately a plain `scatter`:
 * no effectScatter, no rippleEffect, no pulsing, not even on high severity.
 * A strobing red dot over a fatal earthquake is theatre, and this page's whole
 * contract is that emphasis comes from ranking and from a few lit edges, never
 * from motion.
 *
 * Three encodings, each independent and each spelled out in the legend:
 * family is SHAPE (triangle = natural hazard, diamond = conflict), severity is
 * COLOUR, and cluster size is AREA. The country polygon underneath carries the
 * country's weighted score as fill intensity, which is the same number "Sıcak
 * Noktalar" ranks by -- so the map and the ranking cannot disagree about which
 * country is worst.
 *
 * Clicking is two different questions: a polygon means "show me this country"
 * (it filters the page), a marker means "what are these" (it opens a popover
 * listing the events stacked at that point, each of which opens the drawer).
 */
export function RiskMap({
  countries,
  selectedCountry,
  onSelectCountry,
  onOpenItem,
}: RiskMapProps) {
  const [mapReady, setMapReady] = useState(false);
  const [popover, setPopover] = useState<{ anchor: MapAnchor; bucketKey: string } | null>(null);
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

  const { option, plotted, unplaced, buckets } = useMemo(() => {
    const severityColor: Record<string, string> = {
      high: theme.critical,
      // No --good anywhere on this page: a "low severity" war is still a war.
      medium: theme.signal,
      low: theme.neutral,
    };

    // One marker per (place, type, severity) so a country with a wildfire and
    // an earthquake shows both, rather than one blended dot.
    const bucketMap = new Map<string, MarkerBucket>();
    let unplacedCount = 0;

    for (const group of countries) {
      for (const item of group.items) {
        const cityKey = item.city?.toLowerCase() ?? "";
        const countryKey = (item.country ?? group.country).toLowerCase();
        const coords = CITY_COORDS[cityKey] ?? COUNTRY_COORDS[countryKey];
        if (!coords) {
          unplacedCount += 1;
          continue;
        }
        const key = `${coords[0]},${coords[1]},${item.risk_type},${item.severity}`;
        const existing = bucketMap.get(key);
        if (existing) {
          existing.items.push(item);
          continue;
        }
        bucketMap.set(key, {
          lon: coords[0],
          lat: coords[1],
          family: item.risk_family,
          country: group.country,
          city: item.city,
          typeLabel: item.risk_type_label_tr,
          severity: item.severity,
          items: [item],
        });
      }
    }

    const all = [...bucketMap.entries()];
    const maxCount = Math.max(1, ...all.map(([, b]) => b.items.length));

    const toPoint = ([key, b]: [string, MarkerBucket]): RiskPoint => ({
      name: b.country,
      value: [b.lon, b.lat, b.items.length],
      symbolSize: symbolSize(b.items.length, maxCount),
      itemStyle: {
        color: severityColor[b.severity] ?? theme.neutral,
        // Dimmed, never hidden, when another country is selected: the rest of
        // the world does not stop having events because one row is focused.
        opacity: selectedCountry && selectedCountry !== b.country ? 0.28 : 0.85,
        borderColor: theme.surface,
        borderWidth: 1.5,
      },
      meta: {
        key,
        country: b.country,
        city: b.city,
        typeLabel: b.typeLabel,
        severity: b.severity,
        count: b.items.length,
      },
    });

    const tooltipFor = (p: { data?: { meta?: RiskPoint["meta"] } }) => {
      const m = p.data?.meta;
      if (!m) return "";
      const place = m.city ? `${m.country} · ${m.city}` : m.country;
      const severity = SEVERITY_WORD[m.severity] ?? m.severity;
      return `<b>${place}</b><br/>${m.typeLabel} · ${severity} · ${m.count} haber<br/><span style="opacity:.7">Listeyi açmak için tıklayın</span>`;
    };

    const series = (family: string, symbol: string) => ({
      type: "scatter" as const,
      coordinateSystem: "geo" as const,
      symbol,
      data: all.filter(([, b]) => b.family === family).map(toPoint),
      tooltip: { formatter: tooltipFor },
      // Entrance only, and no per-point delay cascade -- the markers appear,
      // then the map is still.
      animationDuration: 500,
      zlevel: 2,
    });

    // Country polygons, filled by the SAME weighted score the ranking sorts by
    // (severity 3/2/1, summed) -- recomputed for the filtered view upstream, so
    // narrowing the page repaints the map rather than leaving it showing the
    // unfiltered world.
    const maxScore = Math.max(1, ...countries.map((c) => c.score));
    const regions = countries
      .flatMap((group) => {
        const feature = GEO_FEATURE_BY_COUNTRY[group.country.toLowerCase()];
        if (!feature) return [];
        const step = Math.min(
          FILL_STEPS.length - 1,
          Math.max(0, Math.ceil((group.score / maxScore) * FILL_STEPS.length) - 1),
        );
        return [
          {
            name: feature,
            itemStyle: {
              areaColor: withAlpha(theme.critical, FILL_STEPS[step]),
              borderColor: selectedCountry === group.country ? theme.primary : theme.surface,
              borderWidth: selectedCountry === group.country ? 1.6 : 0.6,
            },
          },
        ];
      });

    return {
      buckets: bucketMap,
      plotted: all.reduce((n, [, b]) => n + b.items.length, 0),
      unplaced: unplacedCount,
      option: {
        backgroundColor: "transparent",
        textStyle: { fontFamily: "inherit" },
        tooltip: {
          backgroundColor: theme.surface,
          borderColor: theme.gridline,
          borderWidth: 1,
          borderRadius: 10,
          padding: [8, 12],
          textStyle: { color: theme.inkStrong, fontSize: 12 },
        },
        geo: {
          map: "world",
          roam: true,
          center: [18, 28],
          zoom: 1.5,
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
          regions,
        },
        series: [series("natural", "triangle"), series("conflict", "diamond")],
      },
    };
  }, [countries, selectedCountry, theme]);

  // A bucket that no longer exists (the filters changed under an open popover)
  // closes it rather than rendering a stale list.
  const openBucket = popover ? buckets.get(popover.bucketKey) : undefined;

  if (!mapReady) {
    return (
      <div className="flex h-[280px] items-center justify-center rounded-xl border border-border bg-card sm:h-[420px]">
        <span className="text-xs text-muted-foreground">Harita yükleniyor…</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-border bg-card p-2">
      <div className="h-[280px] w-full sm:h-[420px]">
        <ReactECharts
          option={option}
          style={{ height: "100%", width: "100%" }}
          opts={{ renderer: "canvas" }}
          notMerge
          onEvents={{
            click: (params: {
              componentType?: string;
              name?: string;
              data?: { meta?: RiskPoint["meta"] };
              event?: { event?: MouseEvent };
            }) => {
              const meta = params.data?.meta;
              if (meta) {
                // A marker: "what are these?" -- the popover answers with the
                // actual events, each of which opens the drawer.
                const native = params.event?.event;
                setPopover({
                  bucketKey: meta.key,
                  anchor: {
                    x: native?.clientX ?? 0,
                    below: (native?.clientY ?? 0) + 10,
                    above: (native?.clientY ?? 0) - 10,
                  },
                });
                return;
              }
              // A polygon: "show me this country" -- same idiom as
              // region-map.tsx's region click, filtering rather than detailing.
              if (params.componentType === "geo" && params.name) {
                const match = countries.find(
                  (c) => GEO_FEATURE_BY_COUNTRY[c.country.toLowerCase()] === params.name,
                );
                if (match) {
                  setPopover(null);
                  onSelectCountry(match.country === selectedCountry ? null : match.country);
                }
              }
            },
          }}
        />
      </div>

      {popover && openBucket && (
        <RiskMapPopover
          anchor={popover.anchor}
          country={openBucket.country}
          city={openBucket.city}
          items={openBucket.items}
          onSelect={(item) => {
            setPopover(null);
            onOpenItem(item);
          }}
          onClose={() => setPopover(null)}
        />
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[11px] text-muted-foreground">
        {/* The legend spells out every encoding in words. Shape carries family,
            colour carries severity, fill carries the country's weighted score;
            none of the three is left to be inferred. */}
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="text-foreground">▲</span> Doğal afet
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="text-foreground">◆</span> Çatışma
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-2 rounded-full bg-critical" /> Yüksek
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-2 rounded-full bg-warning" /> Orta
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-2 rounded-full bg-muted-foreground/50" /> Düşük
        </span>
        <span className="flex items-center gap-1.5">
          Ülke dolgusu: az
          {FILL_STEPS.map((step) => (
            <span
              key={step}
              aria-hidden
              className="size-2 rounded-[2px]"
              style={{ backgroundColor: withAlpha(theme.critical, step) }}
            />
          ))}
          çok
        </span>
        <span className="ml-auto tabular-nums">
          {plotted} olay haritada
          {unplaced > 0 && ` · ${unplaced} olay konumlandırılamadı`}
        </span>
      </div>
      {/* The one thing a map of disasters must not let a reader assume. */}
      <p className="px-1 text-[11px] leading-relaxed text-muted-foreground">
        Konumlar ülke/şehir merkezidir, olay noktası değildir. Ülkeye tıklayın:
        sayfa o ülkeye daralır. İşarete tıklayın: o noktadaki olaylar listelenir.
      </p>
    </div>
  );
}
