"use client";

import * as echarts from "echarts";
import ReactECharts from "echarts-for-react";
import { useReducedMotion } from "framer-motion";
import { useTheme } from "next-themes";
import { useEffect, useMemo, useState } from "react";

import type { HubOut, HubRouteOut } from "@/lib/types";

// Shared with region-map.tsx: the world outline is a fetched asset, not an
// import, so the 455KB of coordinates never enters the JS graph.
let mapPromise: Promise<void> | null = null;

function ensureWorldMap(): Promise<void> {
  if (!mapPromise) {
    mapPromise = fetch("/geo/world.json")
      .then((res) => res.json())
      .then((geoJson) => {
        echarts.registerMap("world", geoJson);
      })
      .catch(() => {
        mapPromise = null;
      });
  }
  return mapPromise;
}

const HOME = "IST";

// Marker area, not radius, tracks coverage: a hub with four times the articles
// should look four times as big, and radius would make it sixteen. Magnitude is
// carried by size alone -- one hue throughout, so nothing here needs a
// categorical palette or a legend of colors.
const MIN_SYMBOL = 7;
const MAX_SYMBOL = 26;

function symbolSize(count: number, max: number): number {
  if (max <= 0 || count <= 0) return MIN_SYMBOL;
  const area = (count / max) * (MAX_SYMBOL ** 2 - MIN_SYMBOL ** 2) + MIN_SYMBOL ** 2;
  return Math.sqrt(area);
}

interface HubMapProps {
  hubs: HubOut[];
  routes: HubRouteOut[];
  selected: string | null;
  onSelect: (code: string | null) => void;
}

/** The watched hubs on the world map, sized by how much the archive has to say
 * about each, with a line between airports that keep turning up in the same
 * story. Istanbul is always marked, selected or not -- it is the home hub and
 * the reference point every other marker is read against. */
export function HubMap({ hubs, routes, selected, onSelect }: HubMapProps) {
  const [mapReady, setMapReady] = useState(false);
  const reduceMotion = useReducedMotion();
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  useEffect(() => {
    let active = true;
    ensureWorldMap().then(() => {
      if (active) setMapReady(true);
    });
    return () => {
      active = false;
    };
  }, []);

  const accent = isDark ? "#3987e5" : "#2a78d6";
  const neutralFill = isDark ? "#262624" : "#eceae2";
  const hoverFill = isDark ? "#33332f" : "#dcdacf";
  const borderColor = isDark ? "#1a1a19" : "#fcfcfb";
  const ink = isDark ? "#c3c2b7" : "#52514e";
  const surface = isDark ? "#1a1a19" : "#fcfcfb";

  const option = useMemo(() => {
    const maxCount = Math.max(1, ...hubs.map((h) => h.article_count));
    const home = hubs.find((h) => h.code === HOME);

    const points = hubs
      .filter((h) => h.code !== HOME)
      .map((hub) => ({
        name: hub.code,
        value: [hub.lon, hub.lat, hub.article_count],
        symbolSize: symbolSize(hub.article_count, maxCount),
        itemStyle: {
          color: accent,
          opacity: hub.article_count === 0 ? 0.3 : selected && selected !== hub.code ? 0.45 : 0.9,
          // A 2px ring in the surface color so overlapping hubs stay countable.
          borderColor: surface,
          borderWidth: 2,
        },
        hub,
      }));

    return {
      backgroundColor: "transparent",
      tooltip: {
        backgroundColor: surface,
        borderColor: isDark ? "#2c2c2a" : "#e1e0d9",
        textStyle: { color: isDark ? "#ffffff" : "#0b0b0b", fontSize: 12 },
        formatter: (params: { data?: { hub?: HubOut } }) => {
          const hub = params.data?.hub;
          if (!hub) return "";
          return `<b>${hub.name}</b> (${hub.code})<br/>${hub.city} · ${hub.article_count} haber`;
        },
      },
      geo: {
        map: "world",
        roam: true,
        center: home ? [home.lon, home.lat] : [28.98, 41.01],
        zoom: 2.4,
        scaleLimit: { min: 1, max: 10 },
        label: { show: false },
        itemStyle: { areaColor: neutralFill, borderColor, borderWidth: 0.6 },
        emphasis: { label: { show: false }, itemStyle: { areaColor: hoverFill } },
        select: { disabled: true },
      },
      series: [
        {
          type: "lines",
          coordinateSystem: "geo",
          // Thin and recessive: the lines are context for the markers, not the
          // subject. Weight tracks how often the pair is discussed together.
          data: routes.map((route) => ({
            coords: [
              [route.from_lon, route.from_lat],
              [route.to_lon, route.to_lat],
            ],
            lineStyle: {
              width: 0.8 + Math.min(2, route.article_count / 6),
              opacity: selected && selected !== route.from && selected !== route.to ? 0.12 : 0.35,
            },
            route,
          })),
          lineStyle: { color: accent, curveness: 0.25 },
          tooltip: {
            formatter: (params: { data?: { route?: HubRouteOut } }) => {
              const route = params.data?.route;
              return route
                ? `${route.from} – ${route.to}<br/>${route.article_count} ortak haber`
                : "";
            },
          },
          zlevel: 1,
        },
        {
          type: "scatter",
          coordinateSystem: "geo",
          data: points,
          zlevel: 2,
        },
        // The home hub, always visible and always distinguishable.
        ...(home
          ? [
              {
                type: "effectScatter",
                coordinateSystem: "geo",
                data: [
                  {
                    name: HOME,
                    value: [home.lon, home.lat, home.article_count],
                    hub: home,
                  },
                ],
                symbolSize: Math.max(10, symbolSize(home.article_count, maxCount)),
                itemStyle: { color: accent, borderColor: surface, borderWidth: 2 },
                rippleEffect: reduceMotion
                  ? { number: 0, scale: 1 }
                  : { number: 2, scale: 3, brushType: "stroke" },
                zlevel: 3,
              },
            ]
          : []),
      ],
    };
  }, [hubs, routes, selected, accent, neutralFill, hoverFill, borderColor, surface, isDark, reduceMotion]);

  if (!mapReady) {
    return (
      <div className="flex h-[380px] items-center justify-center rounded-xl border border-border bg-card">
        <span className="text-xs text-muted-foreground">Harita yükleniyor…</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-border bg-card p-2">
      <ReactECharts
        option={option}
        style={{ height: 380, width: "100%" }}
        opts={{ renderer: "canvas" }}
        notMerge
        onEvents={{
          click: (params: { data?: { hub?: HubOut } }) => {
            const code = params.data?.hub?.code;
            if (code) onSelect(code === selected ? null : code);
          },
        }}
      />
      <p className="px-1 text-[11px]" style={{ color: ink }}>
        Nokta büyüklüğü o hub hakkında toplanan haber sayısını gösterir. Çizgiler, aynı
        haberde birlikte anılan havalimanı çiftleridir — tarife değil, arşivin gündemi.
      </p>
    </div>
  );
}
