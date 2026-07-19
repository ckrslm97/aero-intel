"use client";

import { useReducedMotion } from "framer-motion";
import * as echarts from "echarts";
import ReactECharts from "echarts-for-react";
import { useTheme } from "next-themes";
import { useMemo } from "react";

import { COUNTRY_REGION } from "@/lib/geo/region-countries";
import worldJson from "@/lib/geo/world.json";
import { worldRegions } from "@/lib/nav";

// Register once per module load; echarts natively decodes the compact
// encodeOffsets coordinate format this world.json (from echarts 4) uses.
let registered = false;
function ensureWorldMap() {
  if (!registered) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the encoded map JSON predates echarts' GeoJSON typings
    echarts.registerMap("world", worldJson as any);
    registered = true;
  }
}

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

const ISTANBUL: [number, number] = [28.98, 41.01];

// Visual anchor per region for the flight arc --[lon, lat].
const REGION_CENTER: Record<string, [number, number]> = {
  europe: [10, 50],
  "middle-east": [45, 27],
  africa: [20, 2],
  "north-america": [-100, 45],
  "central-america": [-88, 15],
  "south-america": [-60, -15],
  asia: [85, 35],
  "southeast-asia": [110, 5],
  oceania: [140, -25],
};

// The classic echarts plane glyph (path data, not artwork from any airline).
const PLANE =
  "path://M1705.06,1318.313v-89.254l-319.9-221.799l0.073-208.063c0.521-84.662-26.629-121.796-63.961-121.491c-37.332-0.305-64.482,36.829-63.961,121.491l0.073,208.063l-319.9,221.799v89.254l330.343-157.288l12.238,241.308l-134.449,92.931l0.531,42.034l175.125-42.917l175.125,42.917l0.531-42.034l-134.449-92.931l12.238-241.308L1705.06,1318.313z";

interface RegionMapProps {
  value: string | null;
  onChange: (slug: string | null) => void;
}

/** Clickable world map for the Gazete's region filter. Default view sits on
 * Istanbul (the home hub); picking a region -- here or via the chips -- sends
 * a plane flying from Istanbul to it. Selection state is binary (selected
 * blue vs neutral), deliberately not a 9-color categorical scheme: identity
 * comes from the hover tooltip and the click, color only marks selection. */
export function RegionMap({ value, onChange }: RegionMapProps) {
  ensureWorldMap();
  const reduceMotion = useReducedMotion();
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  // Same validated blue the site's other charts lead with.
  const accent = isDark ? "#3987e5" : "#2a78d6";
  const neutralFill = isDark ? "#262624" : "#eceae2";
  const hoverFill = isDark ? "#33332f" : "#dcdacf";
  const borderColor = isDark ? "#1a1a19" : "#fcfcfb";
  const ink = isDark ? "#c3c2b7" : "#52514e";
  const surface = isDark ? "#1a1a19" : "#fcfcfb";

  const option = useMemo(() => {
    const selectedCountries = value
      ? Object.entries(COUNTRY_REGION)
          .filter(([, region]) => region === value)
          .map(([name]) => ({
            name,
            itemStyle: { areaColor: accent, opacity: 0.55 },
          }))
      : [];

    const target = value ? REGION_CENTER[value] : null;

    return {
      backgroundColor: "transparent",
      tooltip: {
        backgroundColor: surface,
        borderColor: isDark ? "#2c2c2a" : "#e1e0d9",
        textStyle: { color: isDark ? "#ffffff" : "#0b0b0b", fontSize: 12 },
        formatter: (params: { name?: string }) => {
          const region = params.name ? COUNTRY_REGION[params.name] : undefined;
          return region ? REGION_NAME[region] : "";
        },
      },
      geo: {
        map: "world",
        roam: true,
        // Istanbul-centric default view: Europe, Middle East and Africa in frame.
        center: ISTANBUL,
        zoom: 3.2,
        scaleLimit: { min: 1, max: 10 },
        label: { show: false },
        itemStyle: { areaColor: neutralFill, borderColor, borderWidth: 0.6 },
        emphasis: {
          label: { show: false },
          itemStyle: { areaColor: hoverFill },
        },
        select: { disabled: true },
        regions: selectedCountries.map((c) => ({
          name: c.name,
          itemStyle: c.itemStyle,
        })),
      },
      series: [
        // Istanbul: the home marker, gently pulsing when nothing is selected.
        {
          type: "effectScatter",
          coordinateSystem: "geo",
          data: [{ name: "İstanbul", value: [...ISTANBUL, 1] }],
          symbolSize: 8,
          itemStyle: { color: accent },
          rippleEffect: reduceMotion
            ? { number: 0, scale: 1 }
            : { number: 2, scale: 3.2, brushType: "stroke" },
          tooltip: { formatter: "İstanbul (IST)" },
          zlevel: 2,
        },
        // Flight arc IST -> selected region, plane flying along it.
        ...(target
          ? [
              {
                type: "lines",
                coordinateSystem: "geo",
                data: [{ coords: [ISTANBUL, target] }],
                lineStyle: { color: accent, width: 1.6, opacity: 0.6, curveness: 0.3 },
                effect: reduceMotion
                  ? { show: false }
                  : {
                      show: true,
                      symbol: PLANE,
                      symbolSize: 16,
                      period: 4,
                      trailLength: 0,
                      color: accent,
                    },
                zlevel: 3,
                silent: true,
              },
            ]
          : []),
      ],
    };
  }, [value, accent, neutralFill, hoverFill, borderColor, surface, isDark, reduceMotion]);

  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-border bg-card p-2">
      <ReactECharts
        option={option}
        style={{ height: 340, width: "100%" }}
        // Canvas, not SVG: the world polygon set is heavy for the DOM.
        opts={{ renderer: "canvas" }}
        notMerge
        onEvents={{
          click: (params: { name?: string }) => {
            const region = params.name ? COUNTRY_REGION[params.name] : undefined;
            if (region) onChange(region === value ? null : region);
          },
        }}
      />
      <p className="px-1 text-[11px]" style={{ color: ink }}>
        Bir bölgeye tıklayın: uçak İstanbul&apos;dan o bölgeye uçar, haberler bölgeye göre
        filtrelenir. Tekrar tıklamak filtreyi kaldırır.
      </p>
    </div>
  );
}
